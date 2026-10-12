"""전용 PostgreSQL 테스트 DB에서만 실행. 먼저 alembic upgrade head 필요.

LLMOPS_TEST_DATABASE_URL=postgresql+asyncpg://.../llmops_test pytest -q
운영 DB 사용 방지를 위해 loopback 주소와 *_test DB 이름을 강제한다.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import alert_actions
from app.core.config import settings
from app.core.security import get_current_user, require_member_or_s2s
from app.database.session import get_db
from app.main import app
from app.models.audit import LlmopsAuditLog
from app.models.monitor import LlmAlert, LlmAlertAction
from app.models.user import LlmopsUser
from app.monitor import alerts, notify

TEST_URL = os.getenv("LLMOPS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="전용 PostgreSQL URL 미설정")


@pytest_asyncio.fixture
async def store(monkeypatch):
    url = make_url(TEST_URL)
    assert url.host in ("127.0.0.1", "localhost") and url.database.endswith("_test"), "전용 로컬 테스트 DB만 허용"
    engine = create_async_engine(TEST_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        await db.execute(text("TRUNCATE llm_alert_actions, llm_alerts, llmops_audit_log RESTART IDENTITY CASCADE"))
        user = (await db.execute(select(LlmopsUser).where(LlmopsUser.email == "release1@example.com"))).scalar_one_or_none()
        if user is None:
            user = LlmopsUser(email="release1@example.com", role="llmops_admin")
            db.add(user)
        await db.commit()
    async def dependency():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_member_or_s2s] = lambda: user
    monkeypatch.setattr(notify, "send", AsyncMock(return_value=True))
    monkeypatch.setattr(settings, "slack_webhook_url", "")
    try:
        yield sessions
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def seed(sessions, **changes):
    now = datetime.now(timezone.utc)
    values = dict(kind="failure_spike", severity="warning", fingerprint=str(uuid4()),
                  title="test", message="test", first_seen_at=now, last_seen_at=now)
    values.update(changes)
    async with sessions() as db:
        row = LlmAlert(**values); db.add(row); await db.commit()
        return row.id


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def action_payload(**changes):
    data = dict(request_id=str(uuid4()), action_type="모델 교체", note="교체 수행",
                discovery_source="alert", outcome="improved", result_note="오류 감소 확인")
    data.update(changes)
    return data


@pytest.mark.asyncio
async def test_ack_preserves_legacy_note_and_never_counts_action(store):
    alert_id = await seed(store, action_note="기존 메모")
    async with client() as api:
        for undo in [False, True]:
            response = await api.post(f"/api/monitor/alerts/{alert_id}/ack", json={"undo": undo})
            assert response.status_code == 200, response.text
            assert response.json()["action_note"] == "기존 메모"
        assert (await api.get("/api/monitor/actions/summary")).json()["action_count"] == 0
    async with store() as db:
        history = (await db.execute(select(LlmopsAuditLog).order_by(LlmopsAuditLog.id))).scalars().all()
        assert len(history) == 2
        assert history[1].payload["before"]["acknowledged_by"] == "release1@example.com"
        assert history[1].payload["after"]["acknowledged_at"] is None


@pytest.mark.asyncio
async def test_action_idempotency_cancel_history_and_kpi(store):
    alert_id = await seed(store, resolved_at=datetime.now(timezone.utc))
    path = f"/api/monitor/alerts/{alert_id}/actions"
    data = action_payload()
    async with client() as api:
        first, duplicate = await asyncio.gather(api.post(path, json=data), api.post(path, json=data))
        assert first.status_code == duplicate.status_code == 200
        assert first.json()["id"] == duplicate.json()["id"]
        assert (await api.post(path, json={**data, "note": "different"})).status_code == 409
        summary = (await api.get("/api/monitor/actions/summary")).json()
        assert summary == {"action_count": 1, "verified_action_count": 1, "llmops_first_verified_count": 1}
        cancel_path = f'{path}/{first.json()["id"]}/cancel'
        cancel = {"request_id": str(uuid4()), "note": "결과 판단 정정"}
        original = first.json()
        r = await api.post(cancel_path, json=cancel)
        assert r.status_code == 200, r.text
        assert (await api.post(cancel_path, json=cancel)).json()["id"] == r.json()["id"]
        assert (await api.post(cancel_path, json={**cancel, "request_id": str(uuid4())})).status_code == 409
        assert (await api.get("/api/monitor/actions/summary")).json()["action_count"] == 0
        history = (await api.get(path)).json()
        assert len(history) == 2 and history[1] == original
        assert history[0]["target_action_id"] == original["id"]
        assert len((await api.get(path, params={"before_id": history[0]["id"], "limit": 1})).json()) == 1


@pytest.mark.asyncio
async def test_pending_manual_and_cross_alert_cancel(store):
    first, other = await seed(store), await seed(store)
    async with client() as api:
        path = f"/api/monitor/alerts/{first}/actions"
        r = await api.post(path, json=action_payload(outcome="pending", result_note=None, discovery_source="manual"))
        assert r.status_code == 200
        result = (await api.get("/api/monitor/actions/summary")).json()
        assert result == {"action_count": 1, "verified_action_count": 0, "llmops_first_verified_count": 0}
        r = await api.post(f'/api/monitor/alerts/{other}/actions/{r.json()["id"]}/cancel',
                           json={"request_id": str(uuid4()), "note": "wrong alert"})
        assert r.status_code == 404
        assert (await api.post("/api/monitor/alerts/99999/actions", json=action_payload())).status_code == 404


@pytest.mark.asyncio
async def test_s2s_reads_but_cannot_write(store, monkeypatch):
    alert_id = await seed(store)
    app.dependency_overrides.pop(get_current_user)
    app.dependency_overrides.pop(require_member_or_s2s)
    monkeypatch.setattr(settings, "llmops_read_keys", '{"test": "read-only-test"}')
    async with client() as api:
        headers = {"X-API-Key": "read-only-test"}
        assert (await api.get(f"/api/monitor/alerts/{alert_id}/actions", headers=headers)).status_code == 200
        assert (await api.get("/api/monitor/actions/summary", headers=headers)).status_code == 200
        assert (await api.post(f"/api/monitor/alerts/{alert_id}/actions", headers=headers, json=action_payload())).status_code == 401


async def use_signal(monkeypatch, severity="warning"):
    signal = alerts.Signal(kind="failure_spike", severity=severity, fingerprint="stable", title="test", message="test")
    monkeypatch.setattr(alerts, "collect_signals", AsyncMock(return_value=[signal]))
    monkeypatch.setattr(settings, "slack_webhook_url", "https://example.invalid/test")
    return signal


@pytest.mark.asyncio
async def test_retry_after_failure_persists_across_sessions(store, monkeypatch):
    await use_signal(monkeypatch)
    send = AsyncMock(side_effect=[False, True]); monkeypatch.setattr(notify, "send", send)
    async with store() as db:
        result = await alerts.evaluate_and_store(db)
        assert result["opened"] == 1
    async with store() as db:
        row = (await db.execute(select(LlmAlert))).scalar_one()
        assert row.notification_attempts == 1 and row.notified_at is None
        # 강제 재평가가 간격 제한을 우회하지 않는다.
        await alerts.evaluate_and_store(db)
        assert send.await_count == 1
        row.last_notification_attempt_at -= timedelta(seconds=settings.alert_notify_retry_seconds + 1)
        await db.commit()
    async with store() as db:
        await alerts.evaluate_and_store(db)
        row = (await db.execute(select(LlmAlert))).scalar_one()
        assert row.notification_attempts == 2 and row.notified_at is not None
    async with store() as db:
        await alerts.evaluate_and_store(db)
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_retry_cap_dry_run_and_unconfigured(store, monkeypatch):
    await use_signal(monkeypatch)
    send = AsyncMock(return_value=False); monkeypatch.setattr(notify, "send", send)
    async with store() as db:
        await alerts.evaluate_and_store(db, send_notifications=False)
    monkeypatch.setattr(settings, "slack_webhook_url", "")
    async with store() as db:
        await alerts.evaluate_and_store(db)
        row = (await db.execute(select(LlmAlert))).scalar_one()
        assert row.notification_attempts == 0
    monkeypatch.setattr(settings, "slack_webhook_url", "https://example.invalid/test")
    monkeypatch.setattr(settings, "alert_notify_max_attempts", 2)
    for _ in range(4):
        async with store() as db:
            row = (await db.execute(select(LlmAlert))).scalar_one()
            row.last_notification_attempt_at = datetime.now(timezone.utc) - timedelta(days=1)
            await db.commit()
            await alerts.evaluate_and_store(db)
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_evaluators_and_committed_before_send(store, monkeypatch):
    await use_signal(monkeypatch)
    async def send(_):
        # 외부 발송 전에 별도 연결에서 저장된 알림을 읽을 수 있어야 한다.
        async with store() as other:
            assert len((await other.execute(select(LlmAlert))).scalars().all()) == 1
        await asyncio.sleep(0.05)
        return True
    mock = AsyncMock(side_effect=send); monkeypatch.setattr(notify, "send", mock)
    async def run():
        async with store() as db:
            return await alerts.evaluate_and_store(db)
    results = await asyncio.gather(run(), run())
    assert sum(r["opened"] for r in results) == 1
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_commit_failure_never_sends(store, monkeypatch):
    await use_signal(monkeypatch)
    mock = AsyncMock(return_value=True); monkeypatch.setattr(notify, "send", mock)
    async with store() as db:
        monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
        with pytest.raises(RuntimeError):
            await alerts.evaluate_and_store(db)
        await db.rollback()
    mock.assert_not_awaited()
