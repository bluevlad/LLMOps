"""모델 모니터링 API — 인증 가드 + 순수 함수(수명주기·ps 파싱·스냅샷 정합) 단위 테스트."""
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api import model_roles
from app.api.model_monitor import parse_ps_payload
from app.api.pipeline import _NODES
from app.main import app

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def test_monitor_endpoints_require_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/models/stats").status_code == 401
    assert client.get("/api/models/live").status_code == 401
    assert client.get("/api/models/anomalies").status_code == 401
    assert client.get("/api/models/detail", params={"provider": "ollama", "model_id": "x"}).status_code == 401


def test_snapshot_consumers_match_pipeline_topology() -> None:
    known = {n["consumer_id"] for n in _NODES if n.get("consumer_id")}
    assert model_roles.snapshot_consistency_errors(known) == []


def test_snapshot_covers_active_five_models() -> None:
    covered = {r["model"] for r in model_roles.MODEL_ROLES}
    assert covered == {
        "gemma4:12b-mlx", "exaone3.5:7.8b", "qwen2.5-coder:14b", "qwen2.5:7b", "nomic-embed-text:latest",
    }


def test_lifecycle_deprecated_wins() -> None:
    assert model_roles.lifecycle_status(
        model_id="gemma4:12b-mlx", deprecated_at=date(2026, 9, 5),
        last_call_at=NOW, last_comparison_at=NOW, now=NOW,
    ) == "deprecated"


def test_lifecycle_active_when_called_within_60d() -> None:
    assert model_roles.lifecycle_status(
        model_id="gemma4:12b-mlx", deprecated_at=None,
        last_call_at=NOW - timedelta(days=59), last_comparison_at=None, now=NOW,
    ) == "active"


def test_lifecycle_retire_candidate_after_60d_and_90d() -> None:
    assert model_roles.lifecycle_status(
        model_id="qwen2.5-coder:14b", deprecated_at=None,
        last_call_at=NOW - timedelta(days=61), last_comparison_at=NOW - timedelta(days=91), now=NOW,
    ) == "retire-candidate"


def test_lifecycle_idle_when_only_compared() -> None:
    assert model_roles.lifecycle_status(
        model_id="qwen2.5-coder:14b", deprecated_at=None,
        last_call_at=None, last_comparison_at=NOW - timedelta(days=10), now=NOW,
    ) == "idle"


def test_lifecycle_eval_only_tier() -> None:
    assert model_roles.lifecycle_status(
        model_id="qwen2.5:7b", deprecated_at=None,
        last_call_at=None, last_comparison_at=NOW - timedelta(days=30), now=NOW,
    ) == "eval-only"
    assert model_roles.lifecycle_status(
        model_id="qwen2.5:7b", deprecated_at=None,
        last_call_at=None, last_comparison_at=NOW - timedelta(days=120), now=NOW,
    ) == "retire-candidate"


def test_lifecycle_uninstrumented_embedding() -> None:
    assert model_roles.lifecycle_status(
        model_id="nomic-embed-text:latest", deprecated_at=None,
        last_call_at=None, last_comparison_at=None, now=NOW,
    ) == "uninstrumented"


def test_lifecycle_unknown_model_falls_back_to_generic_rule() -> None:
    assert model_roles.lifecycle_status(
        model_id="something:new", deprecated_at=None,
        last_call_at=None, last_comparison_at=None, now=NOW,
    ) == "retire-candidate"


def test_role_tags_from_snapshot() -> None:
    assert model_roles.role_tags_for("exaone3.5:7.8b") == ["analyze", "compose", "refine"]
    assert "docpipeline-refine" in model_roles.consumers_for("exaone3.5:7.8b")
    assert "skillradar-synthesis" in model_roles.consumers_for("gemma4:12b-mlx")
    assert model_roles.consumers_for("qwen2.5:7b") == []


def test_parse_ps_payload() -> None:
    payload = {"models": [{
        "name": "qwen2.5:7b", "model": "qwen2.5:7b", "size": 4913826364,
        "digest": "845d", "expires_at": "2026-09-10T13:26:27.877323+09:00",
        "size_vram": 4913826364, "context_length": 8192,
    }, {"model": "no-name-key"}, {"size": 1}]}
    rows = parse_ps_payload(payload)
    assert [r.model_id for r in rows] == ["qwen2.5:7b", "no-name-key"]
    assert rows[0].size_vram == 4913826364
    assert rows[0].context_length == 8192
    assert rows[0].expires_at is not None and rows[0].expires_at.tzinfo is not None
    assert parse_ps_payload({}) == []
