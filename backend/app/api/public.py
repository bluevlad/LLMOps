"""공개 read-only API — 관리자 로그인 전 홈 화면용 (인증 없음).

공개 범위는 화이트리스트: 모델 관제 KPI 집계 숫자만 (v0.3.0).
모델 목록·호출 내용 등 상세는 기존 인증 API 로만 접근.
익명 트래픽으로부터 DB 를 보호하기 위해 응답을 60초 in-memory 캐시.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.model_monitor import anomaly_rows, fetch_live
from app.database.session import get_db
from app.models.batch_run import BatchRun, BatchRunStage
from app.models.llm_model import LlmModel

router = APIRouter(prefix="/public", tags=["public"])

PUBLIC_DAYS = 30
_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, Any]] = {}


async def _cached(key: str, loader: Callable[[], Awaitable[Any]]) -> Any:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    value = await loader()
    _cache[key] = (now, value)
    return value


class KpiOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_count: int            # 활성 모델 수 (deprecated 제외)
    resident_count: int | None  # 지금 Ollama 메모리에 올라온 모델 수 (None = Ollama 도달 불가)
    calls_30d: int              # 최근 30일 LLM 호출 수 (batch_run_stages)
    anomaly_count_30d: int      # 최근 30일 이상 징후 건수


class OverviewOut(BaseModel):
    days: int
    kpi: KpiOut
    ollama_reachable: bool
    generated_at: datetime


async def load_overview(db: AsyncSession) -> OverviewOut:
    since = datetime.now(timezone.utc) - timedelta(days=PUBLIC_DAYS)
    model_count = (
        await db.execute(
            select(func.count()).select_from(LlmModel).where(LlmModel.deprecated_at.is_(None))
        )
    ).scalar_one()
    calls = (
        await db.execute(
            select(func.count(BatchRunStage.id))
            .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
            .where(BatchRun.started_at >= since)
        )
    ).scalar_one()
    anomalies = await anomaly_rows(db, PUBLIC_DAYS)
    live = await fetch_live()
    return OverviewOut(
        days=PUBLIC_DAYS,
        kpi=KpiOut(
            model_count=model_count,
            resident_count=len(live.models) if live.reachable else None,
            calls_30d=int(calls),
            anomaly_count_30d=len(anomalies),
        ),
        ollama_reachable=live.reachable,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/overview", response_model=OverviewOut)
async def public_overview(db: AsyncSession = Depends(get_db)) -> OverviewOut:
    return await _cached("overview", lambda: load_overview(db))
