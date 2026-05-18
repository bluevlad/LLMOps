"""Phase 1b: /api/batch-runs 헤더/스키마 검증."""
from fastapi.testclient import TestClient

from app.main import app


def test_batch_runs_requires_headers() -> None:
    client = TestClient(app)
    res = client.post("/api/batch-runs", json={
        "consumer_id": "test",
        "run_id": "r1",
        "started_at": "2026-05-18T00:00:00Z",
        "status": "success",
    })
    # 헤더 누락 → 422 (FastAPI 자동 검증)
    assert res.status_code == 422


def test_batch_runs_header_mismatch() -> None:
    client = TestClient(app)
    res = client.post(
        "/api/batch-runs",
        json={
            "consumer_id": "a",
            "run_id": "r1",
            "started_at": "2026-05-18T00:00:00Z",
            "status": "success",
        },
        headers={"X-LLMOps-Key": "k", "X-Consumer-Id": "b"},
    )
    assert res.status_code == 400


def test_batch_runs_invalid_key() -> None:
    client = TestClient(app)
    res = client.post(
        "/api/batch-runs",
        json={
            "consumer_id": "a",
            "run_id": "r1",
            "started_at": "2026-05-18T00:00:00Z",
            "status": "success",
        },
        headers={"X-LLMOps-Key": "wrong", "X-Consumer-Id": "a"},
    )
    assert res.status_code == 401


def test_batch_runs_invalid_status() -> None:
    client = TestClient(app)
    res = client.post(
        "/api/batch-runs",
        json={
            "consumer_id": "a",
            "run_id": "r1",
            "started_at": "2026-05-18T00:00:00Z",
            "status": "INVALID",
        },
        headers={"X-LLMOps-Key": "k", "X-Consumer-Id": "a"},
    )
    assert res.status_code == 422
