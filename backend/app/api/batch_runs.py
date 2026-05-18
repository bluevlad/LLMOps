"""POST /api/batch-runs — consumer 서비스에서 LLM 실행 결과 수신.

표준: standards/observability/BATCH_RUN_REPORTING.md
- 202 Accepted 즉시 ACK (fire-and-forget 서버측 보장)
- X-LLMOps-Key + X-Consumer-Id 검증
- 같은 (consumer_id, run_id) 재전송은 idempotent (409 → 무시 가능)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.session import AsyncSessionLocal
from app.models.batch_run import BatchRun, BatchRunStage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batch-runs", tags=["batch-runs"])


def _load_ingest_keys() -> dict[str, str]:
    """LLMOPS_INGEST_KEYS env (JSON object {consumer_id: api_key})."""
    raw = os.environ.get("LLMOPS_INGEST_KEYS", "{}").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLMOPS_INGEST_KEYS is not valid JSON; ignoring all keys")
        return {}


class StageIn(BaseModel):
    name: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int | None = None


class BatchRunIn(BaseModel):
    consumer_id: str
    run_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str = Field(pattern="^(success|failure|partial)$")
    stages: list[StageIn] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def receive_batch_run(
    body: BatchRunIn,
    x_llmops_key: str = Header(..., alias="X-LLMOps-Key"),
    x_consumer_id: str = Header(..., alias="X-Consumer-Id"),
) -> dict[str, str]:
    # 1) Header consumer_id 와 body consumer_id 일치 검증
    if x_consumer_id != body.consumer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Header X-Consumer-Id mismatch")

    # 2) API key 검증
    expected = _load_ingest_keys().get(body.consumer_id)
    if not expected or expected != x_llmops_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid X-LLMOps-Key")

    # 3) Insert (idempotent on uq_batch_runs_consumer_run)
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(BatchRun.id).where(
                    BatchRun.consumer_id == body.consumer_id,
                    BatchRun.run_id == body.run_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {"status": "duplicate", "id": str(existing)}

        run = BatchRun(
            consumer_id=body.consumer_id,
            run_id=body.run_id,
            started_at=body.started_at,
            ended_at=body.ended_at,
            status=body.status,
            metrics=body.metrics,
            error=body.error,
            extra=body.extra,
        )
        run.stages = [
            BatchRunStage(
                stage_order=i,
                name=s.name,
                model=s.model,
                tokens_in=s.tokens_in,
                tokens_out=s.tokens_out,
                duration_ms=s.duration_ms,
            )
            for i, s in enumerate(body.stages)
        ]
        db.add(run)
        try:
            await db.commit()
        except IntegrityError:
            # 동시 중복 — 무시
            await db.rollback()
            return {"status": "duplicate"}
        return {"status": "accepted", "id": str(run.id)}
