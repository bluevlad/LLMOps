"""모델 파일 디스크 사용량 — llm_models.size_bytes 집계 (호스트 디스크 자체는 InfraWatcher 몫)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LlmModel

INSTALLED_WINDOW = timedelta(hours=3)   # 마지막 폴링(MLX 1h) 이내에 보였으면 "아직 설치됨"


class DiskProviderOut(BaseModel):
    provider: str
    active_count: int
    active_bytes: int
    deprecated_installed_count: int   # deprecated 마크됐지만 파일은 남아 있음 → 회수 가능
    deprecated_installed_bytes: int


class DiskModelOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    provider: str
    size_bytes: int
    deprecated: bool
    installed: bool
    last_seen_at: datetime


class DiskOut(BaseModel):
    generated_at: datetime
    total_installed_bytes: int
    reclaimable_bytes: int
    providers: list[DiskProviderOut]
    top_models: list[DiskModelOut]


def build_disk_out(rows: list[Any], now: datetime, top: int = 10) -> DiskOut:
    """순수 함수 — rows: LlmModel 유사 (model_id/provider/size_bytes/deprecated_at/last_seen_at)."""
    per: dict[str, DiskProviderOut] = {}
    models: list[DiskModelOut] = []
    total = reclaimable = 0
    for m in rows:
        installed = (now - (m.last_seen_at if m.last_seen_at.tzinfo else m.last_seen_at.replace(tzinfo=timezone.utc))) <= INSTALLED_WINDOW
        deprecated = m.deprecated_at is not None
        p = per.setdefault(m.provider, DiskProviderOut(
            provider=m.provider, active_count=0, active_bytes=0,
            deprecated_installed_count=0, deprecated_installed_bytes=0))
        size = int(m.size_bytes or 0)
        if installed:
            total += size
            if deprecated:
                p.deprecated_installed_count += 1
                p.deprecated_installed_bytes += size
                reclaimable += size
            else:
                p.active_count += 1
                p.active_bytes += size
        models.append(DiskModelOut(model_id=m.model_id, provider=m.provider, size_bytes=size,
                                   deprecated=deprecated, installed=installed, last_seen_at=m.last_seen_at))
    models.sort(key=lambda x: (-int(x.installed), -x.size_bytes))
    return DiskOut(
        generated_at=now, total_installed_bytes=total, reclaimable_bytes=reclaimable,
        providers=sorted(per.values(), key=lambda x: x.provider), top_models=models[:top],
    )


async def disk_usage(db: AsyncSession, top: int = 10) -> DiskOut:
    rows = (await db.execute(select(LlmModel).where(LlmModel.size_bytes.isnot(None)))).scalars().all()
    return build_disk_out(list(rows), datetime.now(timezone.utc), top=top)
