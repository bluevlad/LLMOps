"""generate_report.py — comparison_run_id → 마크다운 리포트.

표준: services/llmops/PHASE_2_DESIGN.md §7 (Claude-Opus-bluevlad)

운영자가 이 리포트를 보고 "어느 task 를 어느 모델로 옮길지" 의사결정해야 함.
의사결정 가능한 형태가 되도록 Pareto front + per-prompt winner 모두 포함.

사용:
    python -m scripts.generate_report --run-id 1
    python -m scripts.generate_report --run-id 1 --output reports/foo.md
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.comparison import ComparisonResult, ComparisonRun


def _fmt(v, fmt: str = "{:.3f}") -> str:
    if v is None:
        return "—"
    return fmt.format(v)


def _pareto_front(model_stats: dict[str, dict]) -> list[str]:
    """quality 높고 cost 낮은 모델이 Pareto 최적. 다른 모델에 dominate 안 되는 모델만."""
    front = []
    items = [
        (m, s["avg_quality"] or 0, s["total_cost_usd"] or 0)
        for m, s in model_stats.items()
        if s["avg_quality"] is not None
    ]
    for m, q, c in items:
        dominated = any(
            (q2 >= q and c2 <= c and (q2 > q or c2 < c)) for m2, q2, c2 in items if m2 != m
        )
        if not dominated:
            front.append(m)
    return front


def render(run: ComparisonRun, results: list[ComparisonResult]) -> str:
    summary = run.summary or {}
    models = summary.get("models", {})
    winner = summary.get("overall_winner", "—")
    pareto = _pareto_front(models) if models else []

    lines: list[str] = []
    lines.append(f"# 비교 리포트 — {run.case_name}")
    lines.append("")
    lines.append(f"- **run_id**: {run.id}")
    lines.append(f"- **prompt_set**: `{run.prompt_set_id}`")
    lines.append(f"- **judge_model**: `{run.judge_model or '(skipped)'}`")
    lines.append(f"- **실행 시각**: {run.started_at:%Y-%m-%d %H:%M %Z} → "
                 f"{run.ended_at:%H:%M %Z}" if run.ended_at else "")
    lines.append(f"- **overall winner**: **`{winner}`**")
    lines.append(f"- **Pareto front (quality × cost)**: {', '.join(f'`{m}`' for m in pareto) or '—'}")
    lines.append("")

    # 모델 요약 표
    lines.append("## 모델 요약")
    lines.append("")
    lines.append("| 모델 | provider | n | wins | win_rate | avg_quality | total_cost($) | avg_latency(ms) | $/quality |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for m, s in sorted(models.items(), key=lambda kv: -(kv[1].get("avg_quality") or 0)):
        q = s.get("avg_quality")
        c = s.get("total_cost_usd") or 0
        qpc = (c / q) if q and q > 0 else None
        lines.append(
            f"| `{m}` | {s['provider']} | {s['n']} | {s['wins']} | "
            f"{_fmt(s['win_rate'])} | {_fmt(q)} | {_fmt(c, '{:.6f}')} | "
            f"{_fmt(s['avg_duration_ms'], '{:.0f}')} | {_fmt(qpc, '{:.6f}')} |"
        )
    lines.append("")

    # prompt 별 winner
    by_prompt: dict[str, list[ComparisonResult]] = {}
    for r in results:
        by_prompt.setdefault(r.prompt_id, []).append(r)
    lines.append("## Prompt 별 winner")
    lines.append("")
    lines.append("| prompt_id | winner | score | runner-up | gap |")
    lines.append("|---|---|---:|---|---:|")
    for pid, prs in sorted(by_prompt.items()):
        scored = [r for r in prs if r.quality_score is not None]
        if not scored:
            lines.append(f"| {pid} | — | — | — | — |")
            continue
        scored.sort(key=lambda r: r.quality_score, reverse=True)
        top = scored[0]
        runner = scored[1] if len(scored) > 1 else None
        gap = float(top.quality_score - runner.quality_score) if runner else 0
        lines.append(
            f"| {pid} | `{top.model_id}` | {top.quality_score} | "
            f"{'`' + runner.model_id + '`' if runner else '—'} | {gap:.3f} |"
        )
    lines.append("")

    # 결론 / 권고
    lines.append("## 권고")
    lines.append("")
    if not models:
        lines.append("판정 결과 없음 — `--no-judge` 로 실행됐거나 judge 호출이 모두 실패.")
    else:
        winner_stats = models.get(winner, {})
        lines.append(
            f"- **overall winner `{winner}`** 가 {winner_stats.get('wins')}/{winner_stats.get('n')} "
            f"prompt 에서 최고 점수. avg_quality = {_fmt(winner_stats.get('avg_quality'))}, "
            f"total_cost = ${_fmt(winner_stats.get('total_cost_usd'), '{:.6f}')}."
        )
        if pareto and winner not in pareto:
            lines.append(
                f"- ⚠️ winner 가 Pareto front 밖. **Pareto: {', '.join(pareto)}** — "
                f"비용 대비 효율은 이쪽이 우수."
            )
        elif len(pareto) > 1:
            lines.append(
                f"- Pareto front 다중 ({', '.join(pareto)}). 비용 vs 품질 트레이드오프 의사결정 필요."
            )
    lines.append("")
    lines.append("---")
    lines.append("> 본 리포트는 `scripts.generate_report` 자동 생성. "
                 "운영자 검토 후 `services/llmops/reports/` 에 commit 권장 (Sunset KPI 산출물).")

    return "\n".join(lines) + "\n"


async def main_async(run_id: int, output: Path | None) -> None:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        run = await session.get(ComparisonRun, run_id)
        if run is None:
            raise SystemExit(f"comparison_run id={run_id} 없음")
        results = (await session.execute(
            select(ComparisonResult).where(ComparisonResult.comparison_run_id == run_id)
        )).scalars().all()
    await engine.dispose()

    md = render(run, results)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        print(f"wrote {output}")
    else:
        print(md)


def main() -> None:
    parser = argparse.ArgumentParser(description="comparison_run → 마크다운 리포트")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--output", type=Path, default=None, help="없으면 stdout")
    args = parser.parse_args()
    asyncio.run(main_async(args.run_id, args.output))


if __name__ == "__main__":
    main()
