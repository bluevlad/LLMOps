"""Slack incoming webhook 발송 — 실패해도 호출부를 막지 않는다 (fire-and-forget, 5초 타임아웃)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SEVERITY_ICON = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
EVENT_LABEL = {"discovered": "신규 설치", "removed": "제거됨 (auto deprecated)", "reappeared": "복귀"}


def configured() -> bool:
    return bool(settings.slack_webhook_url)


def format_alert(alert: Any, event: str) -> str:
    """alert: LlmAlert 또는 동일 속성 객체. event: opened | resolved."""
    icon = SEVERITY_ICON.get(alert.severity, "⚪")
    if event == "resolved":
        return f"✅ [LLMOps] 해결 — {alert.title}"
    return f"{icon} [LLMOps] {alert.title}\n{alert.message}"


def format_events(events: list[dict[str, Any]]) -> str:
    lines = ["🗂 [LLMOps] 인벤토리 변경"]
    for e in events:
        lines.append(f"• {EVENT_LABEL.get(e['kind'], e['kind'])}: {e['provider']}/{e['model_id']}")
    return "\n".join(lines)


async def send(text: str) -> bool:
    if not configured():
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(settings.slack_webhook_url, json={"text": text})
            if res.status_code >= 300:
                logger.warning("Slack webhook rejected (%s): %s", res.status_code, res.text[:120])
                return False
            return True
    except httpx.HTTPError as exc:
        logger.warning("Slack webhook failed: %s", exc)
        return False


async def send_inventory_events(events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    return await send(format_events(events))
