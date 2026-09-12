"""인벤토리 diff — 폴러 결과와 llm_models 를 비교해 변경 이벤트를 만들고 사라짐/복귀를 적용.

표준 LLM_INVENTORY_SCHEMA §5 "모델 사라짐 처리": DELETE 금지, deprecated_at=today + notes 마크.
§3-5 Layer 4: discovered / removed / reappeared / digest_changed / size_changed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LlmModel
from app.models.monitor import LlmModelEvent

logger = logging.getLogger(__name__)

AUTO_REMOVED_MARK = "auto: removed from"
SIZE_CHANGE_MIN_BYTES = 1_000_000  # MLX 디렉토리 크기의 사소한 흔들림 무시


@dataclass
class ExistingModel:
    model_id: str
    digest: str | None
    size_bytes: int | None
    deprecated_at: date | None
    notes: str | None


@dataclass
class DiffResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    deprecate: list[str] = field(default_factory=list)   # model_id — 사라짐 → auto deprecate
    revive: list[str] = field(default_factory=list)      # model_id — auto deprecated 였는데 복귀

    @property
    def notable(self) -> list[dict[str, Any]]:
        """Slack 등으로 알릴 만한 이벤트 (discovered / removed / reappeared)."""
        return [e for e in self.events if e["kind"] in ("discovered", "removed", "reappeared")]


def diff_inventory(
    provider: str,
    host: str,
    existing: list[ExistingModel],
    incoming: list[dict[str, Any]],
    now: datetime | None = None,
) -> DiffResult:
    """순수 함수 — 단위 테스트 대상. incoming 은 폴러 row(dict, model_id/digest/size_bytes 포함).

    안전장치: incoming 이 비어 있으면 removed 를 내지 않는다. 소스가 일시적으로 빈 응답을
    돌려줄 때 인벤토리 전체가 auto-deprecated 되는 사고를 막는다 (마지막 1개 제거는 다음
    실행에서도 감지되지 않지만, 화면에서 last_seen_at 으로 확인 가능).
    """
    now = now or datetime.now(timezone.utc)
    res = DiffResult()
    by_id = {e.model_id: e for e in existing}
    seen = {r["model_id"] for r in incoming}

    def ev(kind: str, model_id: str, detail: dict[str, Any] | None = None) -> None:
        res.events.append({
            "model_id": model_id, "provider": provider, "host": host,
            "kind": kind, "detail": detail, "at": now,
        })

    for r in incoming:
        mid = r["model_id"]
        prev = by_id.get(mid)
        if prev is None:
            ev("discovered", mid, {"size_bytes": r.get("size_bytes"), "digest": r.get("digest")})
            continue
        if prev.deprecated_at is not None and prev.notes and AUTO_REMOVED_MARK in prev.notes:
            ev("reappeared", mid, {"deprecated_at": prev.deprecated_at.isoformat()})
            res.revive.append(mid)
        new_digest, old_digest = r.get("digest"), prev.digest
        if new_digest and old_digest and new_digest != old_digest:
            ev("digest_changed", mid, {"before": old_digest, "after": new_digest,
                                       "size_before": prev.size_bytes, "size_after": r.get("size_bytes")})
            continue
        new_size, old_size = r.get("size_bytes"), prev.size_bytes
        if new_size is not None and old_size is not None and abs(new_size - old_size) >= SIZE_CHANGE_MIN_BYTES:
            ev("size_changed", mid, {"before": old_size, "after": new_size})

    for prev in existing:
        if not incoming or prev.model_id in seen or prev.deprecated_at is not None:
            continue
        ev("removed", prev.model_id, {"size_bytes": prev.size_bytes, "digest": prev.digest})
        res.deprecate.append(prev.model_id)
    return res


async def load_existing(db: AsyncSession, provider: str, host: str) -> list[ExistingModel]:
    rows = (await db.execute(
        select(LlmModel.model_id, LlmModel.digest, LlmModel.size_bytes, LlmModel.deprecated_at, LlmModel.notes)
        .where(LlmModel.provider == provider, LlmModel.host == host)
    )).all()
    return [ExistingModel(*r) for r in rows]


async def apply_diff(db: AsyncSession, provider: str, host: str, diff: DiffResult) -> None:
    """이벤트 insert + 사라짐 deprecate + 복귀 해제. commit 은 호출자가."""
    today = date.today()
    if diff.deprecate:
        rows = (await db.execute(
            select(LlmModel).where(LlmModel.provider == provider, LlmModel.host == host,
                                   LlmModel.model_id.in_(diff.deprecate))
        )).scalars().all()
        for m in rows:
            m.deprecated_at = today
            mark = f"{AUTO_REMOVED_MARK} {provider} ({today.isoformat()})"
            m.notes = f"{m.notes}\n{mark}" if m.notes else mark
    if diff.revive:
        rows = (await db.execute(
            select(LlmModel).where(LlmModel.provider == provider, LlmModel.host == host,
                                   LlmModel.model_id.in_(diff.revive))
        )).scalars().all()
        for m in rows:
            m.deprecated_at = None
            m.notes = f"{m.notes}\nauto: reappeared in {provider} ({today.isoformat()})" if m.notes else None
    for e in diff.events:
        db.add(LlmModelEvent(**e))
    if diff.events:
        logger.info("%s inventory diff: %s", provider,
                    ", ".join(f"{e['kind']}={e['model_id']}" for e in diff.events))
