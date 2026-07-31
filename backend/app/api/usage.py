"""GET /api/usage — 사용량 통계 (일별/월별 토큰·호출·성공률·피드백).

데이터원: batch_runs + batch_run_stages (Phase A 읽기 계층의 연장).
피드백은 quality_judge='user-feedback' 스테이지를 집계 — consumer 가
좋아요/싫어요를 quality.score(1.0/0.0)로 보고하는 표준 v0.2.0 계약 전제.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_member
from app.database.session import get_db
from app.models.batch_run import BatchRun, BatchRunStage
from app.models.user import LlmopsUser

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageBucketOut(BaseModel):
    bucket: str                 # 'YYYY-MM-DD' (day) / 'YYYY-MM' (month)
    runs: int
    runs_success: int
    stages: int                 # LLM 호출 횟수 (stage 단위)
    tokens_in: int
    tokens_out: int
    feedback_up: int
    feedback_down: int


class ConsumerUsageOut(BaseModel):
    consumer_id: str
    runs: int
    stages: int
    tokens_in: int
    tokens_out: int


class UsageOut(BaseModel):
    granularity: str
    since: datetime
    series: list[UsageBucketOut]
    by_consumer: list[ConsumerUsageOut]


@router.get("", response_model=UsageOut)
async def usage_stats(
    days: int = Query(30, ge=1, le=730),
    granularity: str = Query("day", pattern="^(day|month)$"),
    consumer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member),
) -> UsageOut:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trunc = func.date_trunc(granularity, BatchRun.started_at)
    fmt = "YYYY-MM-DD" if granularity == "day" else "YYYY-MM"

    run_filter = [BatchRun.started_at >= since]
    if consumer_id:
        run_filter.append(BatchRun.consumer_id == consumer_id)

    # run 단위 (건수/성공) — stage join 시 중복 카운트되므로 분리 집계
    run_rows = (await db.execute(
        select(
            func.to_char(trunc, fmt).label("bucket"),
            func.count(BatchRun.id),
            func.count(BatchRun.id).filter(BatchRun.status == "success"),
        )
        .where(*run_filter)
        .group_by("bucket")
    )).all()
    runs_by_bucket = {b: (total, ok) for b, total, ok in run_rows}

    # stage 단위 (호출수/토큰/피드백)
    is_up = BatchRunStage.quality_judge == "user-feedback"
    stage_rows = (await db.execute(
        select(
            func.to_char(trunc, fmt).label("bucket"),
            func.count(BatchRunStage.id),
            func.coalesce(func.sum(BatchRunStage.tokens_in), 0),
            func.coalesce(func.sum(BatchRunStage.tokens_out), 0),
            func.count(BatchRunStage.id).filter(is_up, BatchRunStage.quality_score >= 0.5),
            func.count(BatchRunStage.id).filter(is_up, BatchRunStage.quality_score < 0.5),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(*run_filter)
        .group_by("bucket")
    )).all()
    stages_by_bucket = {row[0]: row for row in stage_rows}

    buckets = sorted(set(runs_by_bucket) | set(stages_by_bucket))
    series = []
    for b in buckets:
        total, ok = runs_by_bucket.get(b, (0, 0))
        st = stages_by_bucket.get(b)
        series.append(UsageBucketOut(
            bucket=b,
            runs=total,
            runs_success=ok,
            stages=st[1] if st else 0,
            tokens_in=int(st[2]) if st else 0,
            tokens_out=int(st[3]) if st else 0,
            feedback_up=st[4] if st else 0,
            feedback_down=st[5] if st else 0,
        ))

    consumer_rows = (await db.execute(
        select(
            BatchRun.consumer_id,
            func.count(func.distinct(BatchRun.id)),
            func.count(BatchRunStage.id),
            func.coalesce(func.sum(BatchRunStage.tokens_in), 0),
            func.coalesce(func.sum(BatchRunStage.tokens_out), 0),
        )
        .join(BatchRunStage, BatchRunStage.batch_run_id == BatchRun.id, isouter=True)
        .where(*run_filter)
        .group_by(BatchRun.consumer_id)
        .order_by(func.coalesce(func.sum(BatchRunStage.tokens_out), 0).desc())
    )).all()
    by_consumer = [
        ConsumerUsageOut(
            consumer_id=c, runs=r, stages=s, tokens_in=int(ti), tokens_out=int(to)
        )
        for c, r, s, ti, to in consumer_rows
    ]

    return UsageOut(granularity=granularity, since=since, series=series, by_consumer=by_consumer)


# --- 수집·축적 추이 (BATCH_RUN_REPORTING §2-γ metrics 권장 키) --------------

# 증분 키만 합산한다. *_total 스냅샷 키는 합산하면 왜곡되므로 제외.
_ACCUM_KEYS = (
    "items_crawled",
    "items_ingested",
    "items_processed",
    "items_fallback",
    "corpus_added",
    "golden_candidates",
    "golden_added",
    "review_approved",
    "review_rejected",
    "review_abstained",
)


class AccumBucketOut(BaseModel):
    bucket: str
    values: dict[str, int]


class AccumConsumerOut(BaseModel):
    consumer_id: str
    values: dict[str, int]


class AccumulationOut(BaseModel):
    granularity: str
    since: datetime
    keys: list[str]
    series: list[AccumBucketOut]
    totals: dict[str, int]
    by_consumer: list[AccumConsumerOut]


def _metric_sum(key: str):
    return func.coalesce(
        func.sum(cast(BatchRun.metrics[key].astext, Integer)), 0
    ).label(key)


@router.get("/accumulation", response_model=AccumulationOut)
async def accumulation_stats(
    days: int = Query(30, ge=1, le=730),
    granularity: str = Query("day", pattern="^(day|month)$"),
    consumer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member),
) -> AccumulationOut:
    """크롤링 수집·RAG corpus·골든셋 축적 추이 — batch_runs.metrics 집계."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trunc = func.date_trunc(granularity, BatchRun.started_at)
    fmt = "YYYY-MM-DD" if granularity == "day" else "YYYY-MM"

    run_filter = [BatchRun.started_at >= since, BatchRun.metrics.isnot(None)]
    if consumer_id:
        run_filter.append(BatchRun.consumer_id == consumer_id)

    sums = [_metric_sum(k) for k in _ACCUM_KEYS]

    bucket_rows = (await db.execute(
        select(func.to_char(trunc, fmt).label("bucket"), *sums)
        .where(*run_filter)
        .group_by("bucket")
        .order_by("bucket")
    )).all()
    series = [
        AccumBucketOut(
            bucket=row[0],
            values={k: int(v) for k, v in zip(_ACCUM_KEYS, row[1:])},
        )
        for row in bucket_rows
    ]

    totals = {k: 0 for k in _ACCUM_KEYS}
    for b in series:
        for k, v in b.values.items():
            totals[k] += v

    consumer_rows = (await db.execute(
        select(BatchRun.consumer_id, *sums)
        .where(*run_filter)
        .group_by(BatchRun.consumer_id)
    )).all()
    by_consumer = [
        AccumConsumerOut(
            consumer_id=row[0],
            values={k: int(v) for k, v in zip(_ACCUM_KEYS, row[1:])},
        )
        for row in consumer_rows
        if any(int(v) for v in row[1:])
    ]

    return AccumulationOut(
        granularity=granularity,
        since=since,
        keys=list(_ACCUM_KEYS),
        series=series,
        totals=totals,
        by_consumer=by_consumer,
    )
