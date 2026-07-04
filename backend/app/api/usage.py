"""GET /api/usage — 사용량 통계 (일별/월별 토큰·호출·성공률·피드백).

데이터원: batch_runs + batch_run_stages (Phase A 읽기 계층의 연장).
피드백은 quality_judge='user-feedback' 스테이지를 집계 — consumer 가
좋아요/싫어요를 quality.score(1.0/0.0)로 보고하는 표준 v0.2.0 계약 전제.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
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
    _user: LlmopsUser = Depends(get_current_user),
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
