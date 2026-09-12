"""공개 API(/api/public/*) — 인증 없이 접근 가능 + 60초 캐시 (v0.3.0: 모델 관제 KPI 만)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import public
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    public._cache.clear()
    app.dependency_overrides[public.get_db] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    public._cache.clear()


def _overview() -> public.OverviewOut:
    return public.OverviewOut(
        days=30,
        kpi=public.KpiOut(model_count=6, resident_count=2, calls_30d=1234, anomaly_count_30d=1,
                          open_alerts=2, unacknowledged_alerts=1),
        ollama_reachable=True,
        generated_at=datetime.now(timezone.utc),
    )


def test_overview_public_no_auth(client, monkeypatch) -> None:
    async def fake_load(db):
        return _overview()

    monkeypatch.setattr(public, "load_overview", fake_load)
    res = client.get("/api/public/overview")
    assert res.status_code == 200
    body = res.json()
    assert body["kpi"] == {"model_count": 6, "resident_count": 2, "calls_30d": 1234,
                           "anomaly_count_30d": 1, "open_alerts": 2, "unacknowledged_alerts": 1}
    assert body["days"] == 30 and body["ollama_reachable"] is True


def test_overview_cached_within_ttl(client, monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_load(db):
        calls["n"] += 1
        return _overview()

    monkeypatch.setattr(public, "load_overview", fake_load)
    assert client.get("/api/public/overview").status_code == 200
    assert client.get("/api/public/overview").status_code == 200
    assert calls["n"] == 1


def test_flow_endpoints_removed() -> None:
    """Flow Map 은 DocPipeline 으로 이관 — LLMOps 에서는 더 이상 제공하지 않는다."""
    client = TestClient(app)
    assert client.get("/api/public/flow").status_code == 404
    assert client.get("/api/pipeline/flow").status_code == 404
