"""Phase 1b: /api/models 인증 + 폴러 단위 테스트."""
from fastapi.testclient import TestClient

from app.main import app
from app.pollers import ollama as ollama_poller


def test_models_requires_auth() -> None:
    client = TestClient(app)
    res = client.get("/api/models")
    assert res.status_code == 401


def test_ollama_to_row_mapping() -> None:
    item = {
        "name": "qwen2.5:7b",
        "model": "qwen2.5:7b",
        "modified_at": "2026-03-14T10:34:44.133468357+09:00",
        "size": 4683087332,
        "digest": "abc123",
        "details": {
            "format": "gguf",
            "family": "qwen2",
            "parameter_size": "7.6B",
            "quantization_level": "Q4_K_M",
        },
    }
    row = ollama_poller._to_row(item)
    assert row["model_id"] == "qwen2.5:7b"
    assert row["provider"] == "ollama"
    assert row["host"] == "macbook-mac1"
    assert row["size_bytes"] == 4683087332
    assert row["family"] == "qwen2"
    assert row["quantization"] == "Q4_K_M"
    assert row["format"] == "gguf"
    assert row["source_modified_at"] is not None
