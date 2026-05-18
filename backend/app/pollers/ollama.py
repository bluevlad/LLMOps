"""Ollama poller — GET {OLLAMA_BASE_URL}/api/tags 를 주기적으로 호출하여 llm_models 에 upsert.

표준: standards/ai/LLM_INVENTORY_SCHEMA.md §3-2 Ollama 필드 매핑
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.llm_model import LlmModel

logger = logging.getLogger(__name__)


async def fetch_ollama_tags() -> list[dict[str, Any]]:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(url)
        res.raise_for_status()
        return res.json().get("models", [])


def _to_row(item: dict[str, Any]) -> dict[str, Any]:
    details = item.get("details") or {}
    modified = item.get("modified_at")
    if isinstance(modified, str):
        try:
            modified_dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except ValueError:
            modified_dt = None
    else:
        modified_dt = None
    return {
        "model_id": item["name"],
        "provider": "ollama",
        "host": "macbook-mac1",
        "size_bytes": item.get("size"),
        "digest": item.get("digest"),
        "source_modified_at": modified_dt,
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "format": details.get("format"),
        "raw": item,
    }


async def upsert_models(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    now = datetime.utcnow()
    for r in rows:
        r["last_seen_at"] = now
    stmt = pg_insert(LlmModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["model_id", "provider", "host"],
        set_={
            "size_bytes": stmt.excluded.size_bytes,
            "digest": stmt.excluded.digest,
            "source_modified_at": stmt.excluded.source_modified_at,
            "family": stmt.excluded.family,
            "parameter_size": stmt.excluded.parameter_size,
            "quantization": stmt.excluded.quantization,
            "format": stmt.excluded.format,
            "raw": stmt.excluded.raw,
            "last_seen_at": stmt.excluded.last_seen_at,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return len(rows)


async def run_once() -> int:
    """폴러 1회 실행 — APScheduler 가 호출."""
    try:
        items = await fetch_ollama_tags()
    except Exception as exc:
        logger.warning("Ollama tags fetch failed: %s", exc)
        return 0

    rows = [_to_row(it) for it in items]
    async with AsyncSessionLocal() as db:
        n = await upsert_models(db, rows)
    logger.info("Ollama poller upserted %d models", n)
    return n
