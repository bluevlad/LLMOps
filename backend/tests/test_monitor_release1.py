"""1차 관제: API validation/권한 및 최소 재시도 정책 (DB 없이)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.alert_actions import ActionIn, CancelIn
from app.core.config import settings
from app.core.security import get_current_user
from app.main import app
from app.models.user import LlmopsUser
from app.monitor.alerts import notification_due


def payload(**changes):
    return dict(request_id=uuid4(), action_type="모델 교체", note="교체 수행",
                discovery_source="alert", outcome="pending", **changes)


@pytest.mark.parametrize("field", ["note", "action_type"])
def test_action_rejects_blank(field):
    data = payload(); data[field] = "   "
    with pytest.raises(ValidationError):
        ActionIn(**data)


def test_action_requires_result_and_safe_evidence():
    data = payload(); data["outcome"] = "improved"
    with pytest.raises(ValidationError):
        ActionIn(**data)
    data["result_note"] = "실패율 감소 확인"
    assert ActionIn(**data).result_note
    data["evidence_url"] = "javascript:alert(1)"
    with pytest.raises(ValidationError):
        ActionIn(**data)
    with pytest.raises(ValidationError):
        CancelIn(request_id=uuid4(), note=" ")


@pytest.mark.parametrize("role", ["llmops_guest", "llmops_viewer"])
def test_actions_write_rejects_non_admin(role):
    app.dependency_overrides[get_current_user] = lambda: LlmopsUser(email="test@example.com", role=role)
    try:
        client = TestClient(app)
        data = payload(); data["request_id"] = str(data["request_id"])
        assert client.post("/api/monitor/alerts/1/actions", json=data).status_code == 403
        assert client.post("/api/monitor/alerts/1/actions/1/cancel", json={"request_id": str(uuid4()), "note": "취소"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/api/monitor/alerts/1/actions", "/api/monitor/actions/summary"])
def test_actions_read_requires_auth(path):
    assert TestClient(app).get(path).status_code == 401


def test_retry_limits_and_interval(monkeypatch):
    monkeypatch.setattr(settings, "alert_notify_max_attempts", 3)
    monkeypatch.setattr(settings, "alert_notify_retry_seconds", 600)
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(resolved_at=None, notified_at=None, severity="critical",
                          notification_attempts=1, last_notification_attempt_at=now)
    assert not notification_due(row, now)
    assert notification_due(row, now + timedelta(seconds=600))
    row.notification_attempts = 3
    assert not notification_due(row, now + timedelta(days=1))
    row.notification_attempts = 0; row.last_notification_attempt_at = None
    row.severity = "info"
    assert not notification_due(row, now)
    assert notification_due(row, now, new=True)
    row.notified_at = now
    assert not notification_due(row, now, new=True)
    row.notified_at = None; row.resolved_at = now
    assert not notification_due(row, now, new=True)
