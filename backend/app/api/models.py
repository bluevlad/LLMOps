"""GET /api/models — 인벤토리 조회 (인증 필요).

Phase 1b 는 단순 리스트만. Phase 3 에서 service-registry 의 llm_consumers 와 join.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database.session import get_db
from app.models.llm_model import LlmModel
from app.models.user import LlmopsUser
from app.pollers import mlx as mlx_poller
from app.pollers import ollama as ollama_poller

router = APIRouter(prefix="/models", tags=["models"])


class ModelOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    provider: str
    host: str
    size_bytes: int | None
    family: str | None
    parameter_size: str | None
    quantization: str | None
    format: str | None
    source_modified_at: datetime | None
    role_tags: list[str]
    adopted_at: date | None
    deprecated_at: date | None
    first_seen_at: datetime
    last_seen_at: datetime


class RefreshResult(BaseModel):
    ollama_upserted: int
    mlx_upserted: int


@router.get("", response_model=list[ModelOut])
async def list_models(
    include_deprecated: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(get_current_user),
) -> list[ModelOut]:
    stmt = select(LlmModel)
    if not include_deprecated:
        stmt = stmt.where(LlmModel.deprecated_at.is_(None))
    stmt = stmt.order_by(LlmModel.provider, LlmModel.model_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        ModelOut(
            model_id=r.model_id,
            provider=r.provider,
            host=r.host,
            size_bytes=r.size_bytes,
            family=r.family,
            parameter_size=r.parameter_size,
            quantization=r.quantization,
            format=r.format,
            source_modified_at=r.source_modified_at,
            role_tags=r.role_tags or [],
            adopted_at=r.adopted_at,
            deprecated_at=r.deprecated_at,
            first_seen_at=r.first_seen_at,
            last_seen_at=r.last_seen_at,
        )
        for r in rows
    ]


@router.post("/refresh", response_model=RefreshResult)
async def refresh_inventory(
    _user: LlmopsUser = Depends(get_current_user),
) -> RefreshResult:
    """수동 폴링 트리거 (정기 잡과 별개로 즉시 갱신)."""
    n_ollama = await ollama_poller.run_once()
    n_mlx = await mlx_poller.run_once()
    return RefreshResult(ollama_upserted=n_ollama, mlx_upserted=n_mlx)
