"""공개 API(/api/public/*) — 인증 없이 접근 가능 + 60초 캐시."""
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
        kpi=public.KpiOut(model_count=3, comparison_count=2),
        generated_at=datetime.now(timezone.utc),
    )


def test_overview_public_no_auth(client, monkeypatch) -> None:
    async def fake_load(db):
        return _overview()

    monkeypatch.setattr(public, "load_overview", fake_load)
    res = client.get("/api/public/overview")
    assert res.status_code == 200
    assert res.json()["kpi"] == {"model_count": 3, "comparison_count": 2}


def test_overview_cached_within_ttl(client, monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_load(db):
        calls["n"] += 1
        return _overview()

    monkeypatch.setattr(public, "load_overview", fake_load)
    assert client.get("/api/public/overview").status_code == 200
    assert client.get("/api/public/overview").status_code == 200
    assert calls["n"] == 1


def test_flow_public_no_auth_fixed_30_days(client, monkeypatch) -> None:
    captured = {}

    async def fake_build(db, days):
        captured["days"] = days
        from app.api.pipeline import FlowOut

        return FlowOut(
            layers=[], nodes=[], edges=[], days=days,
            generated_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(public, "build_flow", fake_build)
    res = client.get("/api/public/flow")
    assert res.status_code == 200
    assert captured["days"] == 30
    # 공개 endpoint 는 days 파라미터를 열지 않음 — 전달해도 30일 고정
    assert client.get("/api/public/flow?days=365").json()["days"] == 30


def test_admin_flow_still_requires_auth() -> None:
    assert TestClient(app).get("/api/pipeline/flow").status_code == 401
