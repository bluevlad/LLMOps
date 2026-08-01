"""공개 read-only API — 관리자 로그인 전 홈 화면용 (인증 없음).

공개 범위는 화이트리스트: KPI 집계 숫자 + 파이프라인 Flow Map(집계 통계만).
모델 목록·비교 결과·프롬프트/응답 내용 등 상세는 기존 인증 API 로만 접근.
익명 트래픽으로부터 DB 를 보호하기 위해 응답을 60초 in-memory 캐시.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pipeline import FlowOut, build_flow
from app.database.session import get_db
from app.models.comparison import ComparisonRun
from app.models.llm_model import LlmModel

router = APIRouter(prefix="/public", tags=["public"])

PUBLIC_FLOW_DAYS = 30
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
    model_count: int          # 활성 모델 수 (deprecated 제외)
    comparison_count: int     # 비교 실험 수


class OverviewOut(BaseModel):
    kpi: KpiOut
    generated_at: datetime


async def load_overview(db: AsyncSession) -> OverviewOut:
    model_count = (
        await db.execute(
            select(func.count()).select_from(LlmModel).where(LlmModel.deprecated_at.is_(None))
        )
    ).scalar_one()
    comparison_count = (
        await db.execute(select(func.count()).select_from(ComparisonRun))
    ).scalar_one()
    return OverviewOut(
        kpi=KpiOut(model_count=model_count, comparison_count=comparison_count),
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/overview", response_model=OverviewOut)
async def public_overview(db: AsyncSession = Depends(get_db)) -> OverviewOut:
    return await _cached("overview", lambda: load_overview(db))


@router.get("/flow", response_model=FlowOut)
async def public_flow(db: AsyncSession = Depends(get_db)) -> FlowOut:
    # days 는 30일 고정 — 공개 화면 명세(최근 30일) 외 파라미터를 열지 않음
    return await _cached("flow", lambda: build_flow(db, PUBLIC_FLOW_DAYS))
