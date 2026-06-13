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

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.batch_run import BatchRun, BatchRunStage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batch-runs", tags=["batch-runs"])


def _truncate(text: str | None, limit: int) -> tuple[str | None, bool]:
    """서버측 방어 truncation. (잘린본문, 잘림여부) 반환."""
    if text is None:
        return None, False
    if len(text) > limit:
        return text[:limit], True
    return text, False


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


class QualityIn(BaseModel):
    score: float | None = None
    judge: str | None = None
    judge_model: str | None = None
    dimensions: dict[str, float] | None = None
    note: str | None = None


class StageIn(BaseModel):
    name: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int | None = None
    # quality (표준 v0.2.0 §2-α) — inline 평가
    quality: QualityIn | None = None
    # content capture (표준 v0.3.0 §2-β) — consumer 가 샘플링/truncate 후 보고
    prompt: str | None = None
    response: str | None = None
    params: dict[str, Any] | None = None
    ok: bool | None = None
    retries: int | None = None
    error: str | None = None
    prompt_chars: int | None = None
    response_chars: int | None = None
    content_truncated: bool | None = None
    content_sampled: bool | None = None


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


def _build_stage(order: int, s: "StageIn") -> BatchRunStage:
    """StageIn → BatchRunStage. content 는 서버측 max_chars 로 방어 truncate,
    quality inline 평가는 typed 컬럼 + raw 로 분해 저장."""
    limit = settings.batch_content_max_chars
    prompt, p_trunc = _truncate(s.prompt, limit)
    response, r_trunc = _truncate(s.response, limit)

    # 원본 길이: consumer 가 보냈으면 그 값(truncate 전 실제 길이), 없으면 수신값 기준
    prompt_chars = s.prompt_chars if s.prompt_chars is not None else (
        len(s.prompt) if s.prompt is not None else None
    )
    response_chars = s.response_chars if s.response_chars is not None else (
        len(s.response) if s.response is not None else None
    )
    truncated = bool(s.content_truncated) or p_trunc or r_trunc

    q = s.quality
    quality_score = q.score if q else None
    quality_judge = q.judge if q else None
    # judge_model/dimensions/note 는 raw 로 보존 (재현·비교 분석용)
    quality_raw = q.model_dump(exclude_none=True) if q else None

    return BatchRunStage(
        stage_order=order,
        name=s.name,
        model=s.model,
        tokens_in=s.tokens_in,
        tokens_out=s.tokens_out,
        duration_ms=s.duration_ms,
        quality_score=quality_score,
        quality_judge=quality_judge,
        quality_raw=quality_raw,
        prompt=prompt,
        response=response,
        params=s.params,
        ok=s.ok,
        retries=s.retries,
        stage_error=s.error,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        content_truncated=truncated if (s.prompt or s.response) else None,
        content_sampled=s.content_sampled,
    )


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
            _build_stage(i, s) for i, s in enumerate(body.stages)
        ]
        db.add(run)
        try:
            await db.commit()
        except IntegrityError:
            # 동시 중복 — 무시
            await db.rollback()
            return {"status": "duplicate"}
        return {"status": "accepted", "id": str(run.id)}
