"""Phase A: batch-runs / comparisons 읽기 API — 인증 가드 검증."""
from fastapi.testclient import TestClient

from app.main import app


def test_batch_runs_list_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/batch-runs").status_code == 401


def test_batch_runs_summary_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/batch-runs/summary").status_code == 401


def test_comparisons_list_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/comparisons").status_code == 401


def test_comparison_detail_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/comparisons/1").status_code == 401


def test_usage_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/usage").status_code == 401

