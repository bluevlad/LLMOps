"""GET /api/comparisons — Phase 2 비교 실험 조회 (교사후보 스코어보드).

데이터는 scripts/run_comparison.py 가 적재한 comparison_runs / comparison_results.
집계(모델별 평균 품질·win-rate·속도·비용)는 결과 셋이 작으므로 (prompts × models)
서버측 Python 에서 계산한다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database.session import get_db
from app.models.comparison import ComparisonRun
from app.models.user import LlmopsUser

router = APIRouter(prefix="/comparisons", tags=["comparisons"])


class ComparisonRunOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    case_name: str
    prompt_set_id: str
    started_at: datetime
    ended_at: datetime | None
    judge_model: str | None
    note: str | None
    prompt_count: int
    model_count: int
    result_count: int


class ModelAggregateOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    provider: str
    result_count: int
    avg_quality: float | None
    dimensions: dict[str, float]
    win_count: int
    win_rate: float | None
    avg_duration_ms: int | None
    tokens_out_per_sec: float | None
    total_cost_usd: float | None


class ResultPointOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    prompt_id: str
    model_id: str
    provider: str
    quality_score: float | None
    quality_dimensions: dict[str, Any] | None
    tokens_in: int | None
    tokens_out: int | None
    duration_ms: int | None
    cost_usd: float | None


class ComparisonDetailOut(BaseModel):
    run: ComparisonRunOut
    summary: dict[str, Any] | None
    aggregates: list[ModelAggregateOut]
    results: list[ResultPointOut]


def _run_out(r: ComparisonRun) -> ComparisonRunOut:
    return ComparisonRunOut(
        id=r.id,
        case_name=r.case_name,
        prompt_set_id=r.prompt_set_id,
        started_at=r.started_at,
        ended_at=r.ended_at,
        judge_model=r.judge_model,
        note=r.note,
        prompt_count=len({x.prompt_id for x in r.results}),
        model_count=len({(x.model_id, x.provider) for x in r.results}),
        result_count=len(r.results),
    )


@router.get("", response_model=list[ComparisonRunOut])
async def list_comparisons(
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(get_current_user),
) -> list[ComparisonRunOut]:
    stmt = select(ComparisonRun).order_by(ComparisonRun.started_at.desc())
    runs = (await db.execute(stmt)).scalars().all()
    return [_run_out(r) for r in runs]


def build_detail(run: ComparisonRun) -> ComparisonDetailOut:
    """run.results → 모델별 집계 + 산점용 결과 포인트. (순수 함수 — 단위 테스트 대상)"""
    # prompt 별 승자: quality_score 최대 모델 (동점이면 공동 승자)
    by_prompt: dict[str, list] = defaultdict(list)
    for x in run.results:
        if x.quality_score is not None:
            by_prompt[x.prompt_id].append(x)
    wins: dict[tuple[str, str], int] = defaultdict(int)
    for entries in by_prompt.values():
        top = max(float(x.quality_score) for x in entries)
        for x in entries:
            if float(x.quality_score) == top:
                wins[(x.model_id, x.provider)] += 1

    by_model: dict[tuple[str, str], list] = defaultdict(list)
    for x in run.results:
        by_model[(x.model_id, x.provider)].append(x)

    n_prompts = len({x.prompt_id for x in run.results})
    aggregates: list[ModelAggregateOut] = []
    for (model_id, provider), entries in by_model.items():
        qualities = [float(x.quality_score) for x in entries if x.quality_score is not None]
        durations = [x.duration_ms for x in entries if x.duration_ms is not None]
        costs = [float(x.cost_usd) for x in entries if x.cost_usd is not None]

        # 차원별 평균 (factuality/helpfulness/safety 등 — judge 가 준 dict 평탄 평균)
        dim_values: dict[str, list[float]] = defaultdict(list)
        for x in entries:
            for k, v in (x.quality_dimensions or {}).items():
                if isinstance(v, (int, float)):
                    dim_values[k].append(float(v))

        # tokens/sec: duration 이 함께 있는 결과만으로 계산
        tok, dur_s = 0, 0.0
        for x in entries:
            if x.tokens_out is not None and x.duration_ms:
                tok += x.tokens_out
                dur_s += x.duration_ms / 1000.0

        w = wins.get((model_id, provider), 0)
        aggregates.append(ModelAggregateOut(
            model_id=model_id,
            provider=provider,
            result_count=len(entries),
            avg_quality=round(sum(qualities) / len(qualities), 3) if qualities else None,
            dimensions={k: round(sum(v) / len(v), 3) for k, v in dim_values.items()},
            win_count=w,
            win_rate=round(w / n_prompts, 3) if n_prompts else None,
            avg_duration_ms=round(sum(durations) / len(durations)) if durations else None,
            tokens_out_per_sec=round(tok / dur_s, 1) if dur_s > 0 else None,
            total_cost_usd=round(sum(costs), 6) if costs else None,
        ))
    aggregates.sort(key=lambda a: (a.avg_quality is None, -(a.avg_quality or 0)))

    results = [
        ResultPointOut(
            prompt_id=x.prompt_id,
            model_id=x.model_id,
            provider=x.provider,
            quality_score=float(x.quality_score) if x.quality_score is not None else None,
            quality_dimensions=x.quality_dimensions,
            tokens_in=x.tokens_in,
            tokens_out=x.tokens_out,
            duration_ms=x.duration_ms,
            cost_usd=float(x.cost_usd) if x.cost_usd is not None else None,
        )
        for x in run.results
    ]

    return ComparisonDetailOut(
        run=_run_out(run),
        summary=run.summary,
        aggregates=aggregates,
        results=results,
    )


@router.get("/{comparison_id}", response_model=ComparisonDetailOut)
async def get_comparison(
    comparison_id: int,
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(get_current_user),
) -> ComparisonDetailOut:
    run = (await db.execute(
        select(ComparisonRun).where(ComparisonRun.id == comparison_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "comparison run not found")
    return build_detail(run)
