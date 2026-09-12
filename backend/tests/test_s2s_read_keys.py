"""S2S 읽기 키(LLMOPS_READ_KEYS, X-API-Key) — v0.3.0 DocPipeline pull 계약."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import (
    load_read_keys,
    require_member_or_s2s,
    resolve_s2s_client,
    s2s_user,
)
from app.main import app


def test_load_read_keys_parses_json(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_read_keys", '{"docpipeline": "k1", "other": "k2"}')
    assert load_read_keys() == {"docpipeline": "k1", "other": "k2"}


def test_load_read_keys_invalid_json_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_read_keys", "not-json")
    assert load_read_keys() == {}


def test_resolve_s2s_client(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_read_keys", '{"docpipeline": "secret"}')
    assert resolve_s2s_client("secret") == "docpipeline"
    assert resolve_s2s_client("wrong") is None
    monkeypatch.setattr(settings, "llmops_read_keys", "{}")
    assert resolve_s2s_client("secret") is None


def test_s2s_user_is_synthetic_viewer() -> None:
    u = s2s_user("docpipeline")
    assert u.role == "llmops_viewer" and u.email == "s2s:docpipeline"


@pytest.mark.parametrize("path", [
    "/api/batch-runs/summary",
    "/api/usage",
    "/api/usage/accumulation",
    "/api/golden-set/summary",
    "/api/comparisons",
])
def test_read_endpoints_reject_wrong_api_key(monkeypatch, path) -> None:
    monkeypatch.setattr(settings, "llmops_read_keys", '{"docpipeline": "secret"}')
    res = TestClient(app).get(path, headers={"X-API-Key": "wrong"})
    assert res.status_code == 401


def test_read_endpoint_rejects_key_when_none_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_read_keys", "{}")
    res = TestClient(app).get("/api/usage", headers={"X-API-Key": "anything"})
    assert res.status_code == 401


def test_valid_api_key_passes_auth_gate(monkeypatch) -> None:
    """의존성 단독 검증 — DB 없이 합성 viewer 를 돌려준다."""
    import asyncio

    monkeypatch.setattr(settings, "llmops_read_keys", '{"docpipeline": "secret"}')
    user = asyncio.run(require_member_or_s2s(x_api_key="secret", creds=None, db=None))
    assert user.email == "s2s:docpipeline" and user.role == "llmops_viewer"


def test_ingest_endpoint_unaffected_by_read_keys(monkeypatch) -> None:
    """POST /api/batch-runs 는 ingest 키 체계 그대로 — 읽기 키로는 보고 불가."""
    monkeypatch.setattr(settings, "llmops_read_keys", '{"docpipeline": "secret"}')
    monkeypatch.delenv("LLMOPS_INGEST_KEYS", raising=False)
    res = TestClient(app).post("/api/batch-runs", json={}, headers={"X-API-Key": "secret"})
    assert res.status_code in (401, 403, 422)
