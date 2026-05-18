"""Phase 1a smoke test — /api/health 만 검증."""
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "llmops", "version": "0.1.0"}
