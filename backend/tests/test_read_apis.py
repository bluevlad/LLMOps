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


def test_pipeline_flow_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/pipeline/flow").status_code == 401


def test_pipeline_topology_consistency() -> None:
    """엣지가 참조하는 노드가 모두 존재하고, layer 값이 유효한지."""
    from app.api.pipeline import _EDGES, _NODES, LAYERS

    node_ids = {n["id"] for n in _NODES}
    layer_ids = {l["id"] for l in LAYERS}
    for src, dst, kind in _EDGES:
        assert src in node_ids, f"edge source {src} not in nodes"
        assert dst in node_ids, f"edge target {dst} not in nodes"
        assert kind in ("flow", "feedback")
    for n in _NODES:
        assert n["layer"] in layer_ids
        assert n["status"] in ("active", "pending", "planned")
