"""run_comparison.py — Phase 2 (γ) 무료 vs 유료 비교 실험 CLI.

표준: services/llmops/PHASE_2_DESIGN.md (Claude-Opus-bluevlad)

흐름:
  1. yaml prompt set 로드
  2. comparison_runs 행 생성
  3. for each (prompt × model): provider 호출 → comparison_results insert
  4. (옵션) LLM-as-judge 로 quality eval → result 갱신
  5. summary (winner per prompt, totals) 계산 후 comparison_runs.summary 갱신

사용:
    python -m scripts.run_comparison --prompt-set scripts/prompts/foo.yaml
    python -m scripts.run_comparison --prompt-set foo.yaml --no-judge
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.comparison import ComparisonResult, ComparisonRun


# ---------- Provider 호출 ----------


async def call_ollama(model: str, prompt: str) -> dict[str, Any]:
    """Ollama /api/generate 호출. duration 은 wallclock 측정."""
    url = f"{settings.ollama_base_url}/api/generate"
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json={"model": model, "prompt": prompt, "stream": False})
        r.raise_for_status()
        data = r.json()
    duration_ms = int((time.perf_counter() - start) * 1000)
    return {
        "output_text": data.get("response", ""),
        "tokens_in": data.get("prompt_eval_count"),
        "tokens_out": data.get("eval_count"),
        "duration_ms": duration_ms,
        "raw": {k: data.get(k) for k in ("done", "total_duration", "load_duration")},
    }


async def call_claude(model: str, prompt: str) -> dict[str, Any]:
    """Anthropic Claude API. SDK 는 sync 라 to_thread 로 비동기화."""
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    start = time.perf_counter()
    msg = await asyncio.to_thread(
        client.messages.create,
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    text = "".join(block.text for block in msg.content if hasattr(block, "text"))
    return {
        "output_text": text,
        "tokens_in": msg.usage.input_tokens,
        "tokens_out": msg.usage.output_tokens,
        "duration_ms": duration_ms,
        "raw": {"stop_reason": msg.stop_reason, "id": msg.id},
    }


async def call_openai(model: str, prompt: str) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    start = time.perf_counter()
    completion = await asyncio.to_thread(
        client.chat.completions.create,
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    return {
        "output_text": completion.choices[0].message.content or "",
        "tokens_in": completion.usage.prompt_tokens,
        "tokens_out": completion.usage.completion_tokens,
        "duration_ms": duration_ms,
        "raw": {"id": completion.id, "finish_reason": completion.choices[0].finish_reason},
    }


PROVIDER_CALL = {
    "ollama": call_ollama,
    "claude-api": call_claude,
    "openai-api": call_openai,
}


def calc_cost(tokens_in: int | None, tokens_out: int | None, model_spec: dict) -> Decimal:
    """yaml model 항목의 cost_per_1m_tokens_in/out 으로 USD 계산. 로컬은 0."""
    if model_spec["provider"] == "ollama":
        return Decimal("0")
    cin = Decimal(str(model_spec.get("cost_per_1m_tokens_in", 0)))
    cout = Decimal(str(model_spec.get("cost_per_1m_tokens_out", 0)))
    ti = Decimal(tokens_in or 0)
    to = Decimal(tokens_out or 0)
    return ((ti * cin) + (to * cout)) / Decimal("1000000")


# ---------- LLM-as-judge ----------


JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator. Return ONLY valid JSON.
Schema: {"score": <0.0-1.0 float>, "dimensions": {<dim>: <0.0-1.0>, ...}}
No prose, no markdown, no code fences. JSON only."""


async def call_judge(
    judge_model: str, rubric: str, prompt: str, output: str, dim_names: list[str]
) -> dict[str, Any]:
    from anthropic import Anthropic

    user_msg = (
        f"# Rubric\n{rubric}\n\n"
        f"# Dimensions to score (each 0.0-1.0): {', '.join(dim_names)}\n\n"
        f"# Input prompt\n{prompt}\n\n"
        f"# Model output to evaluate\n{output}"
    )
    client = Anthropic(api_key=settings.anthropic_api_key)
    msg = await asyncio.to_thread(
        client.messages.create,
        model=judge_model,
        max_tokens=512,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(block.text for block in msg.content if hasattr(block, "text")).strip()
    # Claude 가 가끔 ```json 으로 감싸므로 방어
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    return json.loads(text)


# ---------- Orchestration ----------


async def run(yaml_path: Path, no_judge: bool, case_override: str | None) -> int:
    spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    case_name = case_override or spec["case_name"]
    prompt_set_id = spec.get("prompt_set_id", yaml_path.stem)
    judge_cfg = spec.get("judge", {})
    judge_model = judge_cfg.get("model", "claude-opus-4-7")
    rubric = judge_cfg.get("rubric", "Score output quality 0~1.")
    dim_names = judge_cfg.get("dimensions", ["overall"])

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        run_row = ComparisonRun(
            case_name=case_name,
            prompt_set_id=prompt_set_id,
            judge_model=judge_model if not no_judge else None,
            note=spec.get("description"),
        )
        session.add(run_row)
        await session.flush()
        run_id = run_row.id
        print(f"[run] comparison_run_id={run_id} case={case_name}")

        # 1) provider 실행
        for prompt_spec in spec["prompts"]:
            prompt_id = prompt_spec["id"]
            prompt_text = prompt_spec["input"]
            for model_spec in spec["models"]:
                provider = model_spec["provider"]
                model_id = model_spec["id"]
                print(f"  [exec] {prompt_id} × {model_id} ...", flush=True)
                try:
                    call_fn = PROVIDER_CALL[provider]
                    out = await call_fn(model_id, prompt_text)
                    cost = calc_cost(out["tokens_in"], out["tokens_out"], model_spec)
                    session.add(ComparisonResult(
                        comparison_run_id=run_id,
                        prompt_id=prompt_id,
                        model_id=model_id,
                        provider=provider,
                        output_text=out["output_text"],
                        tokens_in=out["tokens_in"],
                        tokens_out=out["tokens_out"],
                        duration_ms=out["duration_ms"],
                        cost_usd=cost,
                        raw=out.get("raw"),
                    ))
                except Exception as e:
                    print(f"    ✗ failed: {type(e).__name__}: {e}")
                    session.add(ComparisonResult(
                        comparison_run_id=run_id,
                        prompt_id=prompt_id,
                        model_id=model_id,
                        provider=provider,
                        raw={"error": f"{type(e).__name__}: {e}"},
                    ))
                await session.commit()

        # 2) LLM-as-judge
        if not no_judge:
            print(f"[judge] using {judge_model}")
            results = (await session.execute(
                select(ComparisonResult).where(ComparisonResult.comparison_run_id == run_id)
            )).scalars().all()
            for res in results:
                if not res.output_text:
                    continue
                prompt_text = next(
                    p["input"] for p in spec["prompts"] if p["id"] == res.prompt_id
                )
                try:
                    j = await call_judge(judge_model, rubric, prompt_text, res.output_text, dim_names)
                    res.quality_score = Decimal(str(j["score"]))
                    res.quality_dimensions = j.get("dimensions")
                    res.quality_judge = "llm-judge"
                    print(f"  [judge] {res.prompt_id} × {res.model_id} → {res.quality_score}")
                except Exception as e:
                    print(f"  ✗ judge failed for {res.prompt_id} × {res.model_id}: {e}")
            await session.commit()

        # 3) summary 갱신
        results = (await session.execute(
            select(ComparisonResult).where(ComparisonResult.comparison_run_id == run_id)
        )).scalars().all()
        summary = compute_summary(results)
        await session.execute(
            update(ComparisonRun)
            .where(ComparisonRun.id == run_id)
            .values(summary=summary, ended_at=datetime.now(timezone.utc))
        )
        await session.commit()
        print(f"[done] run_id={run_id} winner={summary.get('overall_winner')}")

    await engine.dispose()
    return run_id


def compute_summary(results: list[ComparisonResult]) -> dict[str, Any]:
    """간단한 win-rate / cost / latency 집계."""
    by_model: dict[str, dict[str, Any]] = {}
    for r in results:
        m = r.model_id
        slot = by_model.setdefault(m, {
            "provider": r.provider, "n": 0, "wins": 0,
            "quality_sum": Decimal("0"), "cost_sum": Decimal("0"),
            "duration_sum": 0, "quality_n": 0,
        })
        slot["n"] += 1
        if r.quality_score is not None:
            slot["quality_sum"] += r.quality_score
            slot["quality_n"] += 1
        if r.cost_usd is not None:
            slot["cost_sum"] += r.cost_usd
        if r.duration_ms is not None:
            slot["duration_sum"] += r.duration_ms

    # winner per prompt
    by_prompt: dict[str, list[ComparisonResult]] = {}
    for r in results:
        by_prompt.setdefault(r.prompt_id, []).append(r)
    for prompt_id, prompt_results in by_prompt.items():
        scored = [r for r in prompt_results if r.quality_score is not None]
        if scored:
            winner = max(scored, key=lambda r: r.quality_score)
            by_model[winner.model_id]["wins"] += 1

    # finalize
    out_models = {}
    for m, slot in by_model.items():
        out_models[m] = {
            "provider": slot["provider"],
            "n": slot["n"],
            "wins": slot["wins"],
            "win_rate": round(slot["wins"] / slot["n"], 3) if slot["n"] else None,
            "avg_quality": (
                float(slot["quality_sum"] / slot["quality_n"]) if slot["quality_n"] else None
            ),
            "total_cost_usd": float(slot["cost_sum"]),
            "avg_duration_ms": (
                int(slot["duration_sum"] / slot["n"]) if slot["n"] else None
            ),
        }
    overall_winner = max(
        out_models.items(),
        key=lambda kv: (kv[1]["wins"], kv[1]["avg_quality"] or 0),
    )[0]
    return {"models": out_models, "overall_winner": overall_winner}


def main() -> None:
    parser = argparse.ArgumentParser(description="LLMOps Phase 2 비교 실험 CLI")
    parser.add_argument("--prompt-set", required=True, type=Path, help="yaml prompt set 경로")
    parser.add_argument("--no-judge", action="store_true", help="LLM-as-judge 건너뜀")
    parser.add_argument("--case", default=None, help="case_name override")
    args = parser.parse_args()
    asyncio.run(run(args.prompt_set, args.no_judge, args.case))


if __name__ == "__main__":
    main()
