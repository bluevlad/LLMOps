"""MLX scanner — ~/.cache/huggingface/hub/ 디렉토리를 스캔하여 llm_models 에 upsert.

표준: standards/ai/LLM_INVENTORY_SCHEMA.md §3-2 MLX 필드 매핑
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.llm_model import LlmModel

logger = logging.getLogger(__name__)


def _dir_size(p: Path) -> int:
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def scan_mlx_dirs(base: Path) -> list[dict[str, Any]]:
    if not base.exists():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not child.name.startswith("models--"):
            continue
        # models--<org>--<repo> → org/repo
        repo_id = child.name.removeprefix("models--").replace("--", "/")
        if "mlx" not in repo_id.lower():
            continue
        try:
            mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        except OSError:
            mtime = None
        rows.append({
            "model_id": repo_id,
            "provider": "mlx",
            "host": "macbook-mac1",
            "size_bytes": _dir_size(child),
            "source_modified_at": mtime,
            "raw": {"dir": str(child)},
        })
    return rows


async def run_once() -> int:
    base = Path(settings.mlx_model_dir)
    rows = scan_mlx_dirs(base)
    if not rows:
        logger.info("MLX scanner found 0 models at %s", base)
        return 0

    now = datetime.utcnow()
    for r in rows:
        r["last_seen_at"] = now

    stmt = pg_insert(LlmModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["model_id", "provider", "host"],
        set_={
            "size_bytes": stmt.excluded.size_bytes,
            "source_modified_at": stmt.excluded.source_modified_at,
            "raw": stmt.excluded.raw,
            "last_seen_at": stmt.excluded.last_seen_at,
        },
    )
    async with AsyncSessionLocal() as db:
        await db.execute(stmt)
        await db.commit()
    logger.info("MLX scanner upserted %d models", len(rows))
    return len(rows)
