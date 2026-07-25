"""Phase C: golden-set 큐레이션 + usage accumulation API — 인증 가드/스키마 검증."""
from fastapi.testclient import TestClient

from app.main import app


def test_golden_set_list_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/golden-set").status_code == 401


def test_golden_set_summary_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/golden-set/summary").status_code == 401


def test_golden_set_promotable_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/golden-set/promotable").status_code == 401


def test_golden_set_promote_requires_auth() -> None:
    client = TestClient(app)
    assert client.post("/api/golden-set/promote", json={"stage_id": 1}).status_code == 401


def test_golden_set_curate_requires_auth() -> None:
    client = TestClient(app)
    assert client.patch("/api/golden-set/1", json={"status": "approved"}).status_code == 401


def test_golden_set_export_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/golden-set/export").status_code == 401


def test_usage_accumulation_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/usage/accumulation").status_code == 401


def test_accum_keys_are_standard_increments() -> None:
    """§2-γ 증분 키만 합산 대상 — *_total 스냅샷 키가 끼어들면 왜곡."""
    from app.api.usage import _ACCUM_KEYS

    assert all(not k.endswith("_total") for k in _ACCUM_KEYS)
    assert "items_ingested" in _ACCUM_KEYS
    assert "golden_added" in _ACCUM_KEYS


def test_golden_set_model_status_enum() -> None:
    from app.api.golden_set import _STATUSES

    assert _STATUSES == ("candidate", "approved", "rejected")
