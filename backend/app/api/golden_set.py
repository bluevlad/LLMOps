"""/api/golden-set — 골든셋 승격·큐레이션 (Phase C).

batch_run_stages 의 content 샘플(prompt/response 보고된 stage)을 골든셋 후보로
승격하고, 큐레이터가 approve/reject/편집한다. LLMOps 는 축적·추이 관측까지만 —
파인튜닝 실행은 별도 consumer(model-tuner)가 export 를 소비한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_member_or_s2s
from app.database.session import get_db
from app.models.batch_run import BatchRun, BatchRunStage
from app.models.golden_set import GoldenSetItem
from app.models.user import LlmopsUser

router = APIRouter(prefix="/golden-set", tags=["golden-set"])

_STATUSES = ("candidate", "approved", "rejected")


class GoldenSetItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    source_stage_id: int | None
    consumer_id: str
    model: str | None
    prompt: str
    response: str
    gold_response: str | None
    status: str
    labels: dict[str, Any] | None
    note: str | None
    curated_by: str | None
    created_at: datetime
    updated_at: datetime


class GoldenSetListOut(BaseModel):
    total: int
    items: list[GoldenSetItemOut]


class PromoteIn(BaseModel):
    stage_id: int
    note: str | None = None
    labels: dict[str, Any] | None = None


class CurateIn(BaseModel):
    status: str | None = None
    gold_response: str | None = None
    note: str | None = None
    labels: dict[str, Any] | None = None


class GoldenSetSummaryOut(BaseModel):
    by_status: dict[str, int]
    by_consumer: list[dict[str, Any]]
    promotable_stages: int  # content 샘플 보유 + 미승격 stage 수 (승격 후보 풀)


@router.post("/promote", response_model=GoldenSetItemOut, status_code=201)
async def promote_stage(
    body: PromoteIn,
    db: AsyncSession = Depends(get_db),
    user: LlmopsUser = Depends(require_member_or_s2s),
) -> GoldenSetItemOut:
    """content 샘플이 보고된 stage 를 골든셋 후보로 승격."""
    row = (await db.execute(
        select(BatchRunStage, BatchRun.consumer_id)
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRunStage.id == body.stage_id)
    )).first()
    if row is None:
        raise HTTPException(404, "stage not found")
    stage, consumer_id = row
    if not stage.prompt or not stage.response:
        raise HTTPException(
            422, "stage has no content sample (prompt/response) — content_sampled 된 stage 만 승격 가능"
        )

    exists = (await db.execute(
        select(GoldenSetItem.id).where(GoldenSetItem.source_stage_id == stage.id)
    )).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, f"already promoted (golden_set_items.id={exists})")

    item = GoldenSetItem(
        source_stage_id=stage.id,
        consumer_id=consumer_id,
        model=stage.model,
        prompt=stage.prompt,
        response=stage.response,
        status="candidate",
        labels=body.labels,
        note=body.note,
        curated_by=user.email,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return GoldenSetItemOut.model_validate(item)


@router.get("", response_model=GoldenSetListOut)
async def list_items(
    status: str | None = Query(None, pattern="^(candidate|approved|rejected)$"),
    consumer_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> GoldenSetListOut:
    filters = []
    if status:
        filters.append(GoldenSetItem.status == status)
    if consumer_id:
        filters.append(GoldenSetItem.consumer_id == consumer_id)

    total = (await db.execute(
        select(func.count(GoldenSetItem.id)).where(*filters)
    )).scalar_one()
    rows = (await db.execute(
        select(GoldenSetItem)
        .where(*filters)
        .order_by(GoldenSetItem.created_at.desc())
        .limit(limit)
        .offset(offset)
    )).scalars().all()
    return GoldenSetListOut(
        total=total,
        items=[GoldenSetItemOut.model_validate(r) for r in rows],
    )


@router.get("/summary", response_model=GoldenSetSummaryOut)
async def summary(
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> GoldenSetSummaryOut:
    status_rows = (await db.execute(
        select(GoldenSetItem.status, func.count(GoldenSetItem.id))
        .group_by(GoldenSetItem.status)
    )).all()
    by_status = {s: 0 for s in _STATUSES}
    by_status.update(dict(status_rows))

    consumer_rows = (await db.execute(
        select(
            GoldenSetItem.consumer_id,
            func.count(GoldenSetItem.id),
            func.count(GoldenSetItem.id).filter(GoldenSetItem.status == "approved"),
        )
        .group_by(GoldenSetItem.consumer_id)
        .order_by(func.count(GoldenSetItem.id).desc())
    )).all()

    promotable = (await db.execute(
        select(func.count(BatchRunStage.id))
        .where(
            BatchRunStage.prompt.isnot(None),
            BatchRunStage.response.isnot(None),
            ~select(GoldenSetItem.id)
            .where(GoldenSetItem.source_stage_id == BatchRunStage.id)
            .exists(),
        )
    )).scalar_one()

    return GoldenSetSummaryOut(
        by_status=by_status,
        by_consumer=[
            {"consumer_id": c, "total": t, "approved": a} for c, t, a in consumer_rows
        ],
        promotable_stages=promotable,
    )


class PromotableStageOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    stage_id: int
    consumer_id: str
    run_started_at: datetime
    stage_name: str | None
    model: str | None
    ok: bool | None
    quality_score: float | None
    prompt_preview: str
    response_preview: str


@router.get("/promotable", response_model=list[PromotableStageOut])
async def list_promotable(
    consumer_id: str | None = None,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> list[PromotableStageOut]:
    """content 샘플 보유 + 아직 승격되지 않은 stage 목록 (승격 후보 풀)."""
    from datetime import timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    filters = [
        BatchRunStage.prompt.isnot(None),
        BatchRunStage.response.isnot(None),
        BatchRun.started_at >= since,
        ~select(GoldenSetItem.id)
        .where(GoldenSetItem.source_stage_id == BatchRunStage.id)
        .exists(),
    ]
    if consumer_id:
        filters.append(BatchRun.consumer_id == consumer_id)

    rows = (await db.execute(
        select(BatchRunStage, BatchRun.consumer_id, BatchRun.started_at)
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(*filters)
        .order_by(BatchRun.started_at.desc())
        .limit(limit)
    )).all()
    return [
        PromotableStageOut(
            stage_id=st.id,
            consumer_id=cid,
            run_started_at=started,
            stage_name=st.name,
            model=st.model,
            ok=st.ok,
            quality_score=float(st.quality_score) if st.quality_score is not None else None,
            prompt_preview=(st.prompt or "")[:300],
            response_preview=(st.response or "")[:300],
        )
        for st, cid, started in rows
    ]


@router.patch("/{item_id}", response_model=GoldenSetItemOut)
async def curate_item(
    item_id: int,
    body: CurateIn,
    db: AsyncSession = Depends(get_db),
    user: LlmopsUser = Depends(require_member_or_s2s),
) -> GoldenSetItemOut:
    item = await db.get(GoldenSetItem, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(422, f"status must be one of {_STATUSES}")
        item.status = body.status
    if body.gold_response is not None:
        item.gold_response = body.gold_response.strip() or None
    if body.note is not None:
        item.note = body.note
    if body.labels is not None:
        item.labels = body.labels
    item.curated_by = user.email
    await db.commit()
    await db.refresh(item)
    return GoldenSetItemOut.model_validate(item)


@router.get("/export")
async def export_jsonl(
    status: str = Query("approved", pattern="^(candidate|approved|rejected)$"),
    consumer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> StreamingResponse:
    """SFT 용 JSONL export — gold_response 없으면 response(초안 채택)를 골든으로."""
    filters = [GoldenSetItem.status == status]
    if consumer_id:
        filters.append(GoldenSetItem.consumer_id == consumer_id)
    rows = (await db.execute(
        select(GoldenSetItem).where(*filters).order_by(GoldenSetItem.id)
    )).scalars().all()

    async def _gen() -> AsyncIterator[bytes]:
        for r in rows:
            rec = {
                "id": r.id,
                "consumer_id": r.consumer_id,
                "model": r.model,
                "prompt": r.prompt,
                "response": r.gold_response or r.response,
                "edited": bool(r.gold_response),
                "labels": r.labels or {},
            }
            yield (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(
        _gen(),
        media_type="application/jsonl",
        headers={
            "Content-Disposition": f"attachment; filename=golden_set_{status}.jsonl"
        },
    )
