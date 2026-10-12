"""M3 관제 — 알림 신호 판정·reconcile·인벤토리 diff·디스크 집계 (순수 함수) + 인증 가드."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.monitor import alerts, notify
from app.pollers.inventory_diff import ExistingModel, diff_inventory

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


# --- 인증 가드 -------------------------------------------------------------

def test_monitor_endpoints_require_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/monitor/alerts").status_code == 401
    assert client.get("/api/monitor/events").status_code == 401
    assert client.get("/api/monitor/disk").status_code == 401
    assert client.post("/api/monitor/alerts/1/ack", json={}).status_code == 401
    assert client.post("/api/monitor/alerts/evaluate").status_code == 401


# --- 상주/도달 신호 --------------------------------------------------------

@dataclass
class FakeLiveModel:
    model_id: str


@dataclass
class FakeLive:
    reachable: bool
    models: list
    error: str | None = None


def test_ollama_unreachable_is_critical() -> None:
    sigs = alerts.resident_signals(FakeLive(False, [], "connect timeout"), ["gemma4:12b-mlx"])
    assert len(sigs) == 1
    assert sigs[0].kind == "ollama_unreachable" and sigs[0].severity == "critical"
    # 도달 불가일 때는 상주 이탈을 중복으로 내지 않는다
    assert all(s.kind != "expected_resident_missing" for s in sigs)


def test_expected_resident_missing() -> None:
    live = FakeLive(True, [FakeLiveModel("qwen2.5:7b")])
    sigs = alerts.resident_signals(live, ["gemma4:12b-mlx", "qwen2.5:7b"])
    assert [s.model_id for s in sigs] == ["gemma4:12b-mlx"]
    assert sigs[0].fingerprint == "expected_resident_missing:gemma4:12b-mlx"


def test_no_signal_when_all_resident() -> None:
    live = FakeLive(True, [FakeLiveModel("gemma4:12b-mlx")])
    assert alerts.resident_signals(live, ["gemma4:12b-mlx"]) == []


# --- 실패율 급증 -----------------------------------------------------------

def test_failure_spike_threshold() -> None:
    rows = [
        ("gemma4:12b-mlx", 100, 30),   # 30% — 초과
        ("exaone3.5:7.8b", 100, 5),    # 5% — 미만
        ("qwen2.5:7b", 4, 2),          # 50% 지만 건수 min_count 미만
    ]
    sigs = alerts.failure_signals(rows, threshold=0.2, min_count=3)
    assert [s.model_id for s in sigs] == ["gemma4:12b-mlx"]
    assert sigs[0].detail["fails_24h"] == 30 and sigs[0].severity == "warning"


def test_failure_signals_ignore_zero_calls() -> None:
    assert alerts.failure_signals([("m", 0, 0)], 0.2, 3) == []


# --- 수명주기 / 계약 -------------------------------------------------------

@dataclass
class FakeStats:
    model_id: str
    lifecycle: str
    last_call_ever: datetime | None = None
    last_comparison_at: datetime | None = None
    size_bytes: int | None = None


def test_retire_candidate_is_info() -> None:
    rows = [FakeStats("old:7b", "retire-candidate"), FakeStats("gemma4:12b-mlx", "active")]
    sigs = alerts.lifecycle_signals(rows)
    assert [s.model_id for s in sigs] == ["old:7b"]
    assert sigs[0].severity == "info"


@dataclass
class FakeAnomaly:
    kind: str
    model: str | None
    consumer_id: str
    count: int
    hint: str = "hint"


def test_contract_signals_filter_kinds() -> None:
    rows = [
        FakeAnomaly("unregistered_model", "ghost:1b", "skillradar-synthesis", 4),
        FakeAnomaly("stage_failed", "gemma4:12b-mlx", "standup-weekly-newsletter", 9),  # 제외 (failure_spike 가 담당)
        FakeAnomaly("tokens_unreported", "gemma4:12b-mlx", "x", 2),                      # 제외
    ]
    sigs = alerts.contract_signals(rows)
    assert len(sigs) == 1
    assert sigs[0].fingerprint == "contract_anomaly:unregistered_model:ghost:1b:skillradar-synthesis"


# --- reconcile -------------------------------------------------------------

@dataclass
class FakeAlert:
    fingerprint: str
    severity: str = "warning"
    notified_at: datetime | None = None
    resolved_at: datetime | None = None


def _sig(fp: str) -> alerts.Signal:
    return alerts.Signal(kind="retire_candidate", severity="info", fingerprint=fp, title="t", message="m")


def test_reconcile_opens_updates_resolves() -> None:
    open_alerts = [FakeAlert("a"), FakeAlert("b")]
    signals = [_sig("a"), _sig("c")]
    r = alerts.reconcile(open_alerts, signals)
    assert [s.fingerprint for s in r.to_open] == ["c"]
    assert [a.fingerprint for a, _ in r.to_update] == ["a"]
    assert [a.fingerprint for a in r.to_resolve] == ["b"]


def test_reconcile_dedups_same_fingerprint() -> None:
    r = alerts.reconcile([], [_sig("x"), _sig("x")])
    assert len(r.to_open) == 1


# --- 인벤토리 diff ---------------------------------------------------------

def _existing(mid, digest=None, size=None, dep=None, notes=None):
    return ExistingModel(model_id=mid, digest=digest, size_bytes=size, deprecated_at=dep, notes=notes)


def test_diff_discovered_and_removed() -> None:
    existing = [_existing("old:7b", digest="d1", size=100)]
    incoming = [{"model_id": "new:3b", "digest": "d2", "size_bytes": 200}]
    d = diff_inventory("ollama", "macbook-mac1", existing, incoming, now=NOW)
    kinds = {e["kind"]: e["model_id"] for e in d.events}
    assert kinds == {"discovered": "new:3b", "removed": "old:7b"}
    assert d.deprecate == ["old:7b"] and d.revive == []


def test_diff_does_not_redeprecate_already_deprecated() -> None:
    existing = [_existing("gone:7b", dep=date(2026, 9, 1), notes="auto: removed from ollama (2026-09-01)")]
    d = diff_inventory("ollama", "macbook-mac1", existing, [], now=NOW)
    assert d.events == [] and d.deprecate == []


def test_diff_reappeared_revives_auto_deprecated_only() -> None:
    existing = [
        _existing("back:7b", digest="d1", size=100, dep=date(2026, 9, 1),
                  notes="auto: removed from ollama (2026-09-01)"),
        _existing("manual:7b", digest="d2", size=100, dep=date(2026, 8, 1), notes="수동 퇴출 결정"),
    ]
    incoming = [{"model_id": "back:7b", "digest": "d1", "size_bytes": 100},
                {"model_id": "manual:7b", "digest": "d2", "size_bytes": 100}]
    d = diff_inventory("ollama", "macbook-mac1", existing, incoming, now=NOW)
    assert d.revive == ["back:7b"]
    assert [e["kind"] for e in d.events] == ["reappeared"]


def test_diff_digest_change_and_size_noise() -> None:
    existing = [_existing("a:7b", digest="d1", size=1_000_000_000),
                _existing("b:7b", digest="d2", size=1_000_000_000)]
    incoming = [
        {"model_id": "a:7b", "digest": "dNEW", "size_bytes": 1_100_000_000},   # digest 변경
        {"model_id": "b:7b", "digest": "d2", "size_bytes": 1_000_000_500},     # 0.5MB — 노이즈, 무시
    ]
    d = diff_inventory("ollama", "macbook-mac1", existing, incoming, now=NOW)
    assert [(e["kind"], e["model_id"]) for e in d.events] == [("digest_changed", "a:7b")]


def test_diff_size_change_reported_when_large() -> None:
    existing = [_existing("m:7b", size=1_000_000_000)]
    incoming = [{"model_id": "m:7b", "size_bytes": 2_000_000_000}]
    d = diff_inventory("mlx", "macbook-mac1", existing, incoming, now=NOW)
    assert [e["kind"] for e in d.events] == ["size_changed"]


def test_notable_events_exclude_metadata_churn() -> None:
    existing = [_existing("a:7b", digest="d1"), _existing("b:7b", size=1_000_000_000)]
    incoming = [{"model_id": "a:7b", "digest": "dNEW"}, {"model_id": "b:7b", "size_bytes": 5_000_000_000},
                {"model_id": "c:7b"}]
    d = diff_inventory("ollama", "macbook-mac1", existing, incoming, now=NOW)
    assert [e["kind"] for e in d.notable] == ["discovered"]


# --- Slack 포맷 ------------------------------------------------------------

def test_format_events_lists_models() -> None:
    text = notify.format_events([{"kind": "removed", "provider": "ollama", "model_id": "old:7b"}])
    assert "인벤토리 변경" in text and "ollama/old:7b" in text


def test_format_alert_opened_and_resolved() -> None:
    a = alerts.Signal(kind="failure_spike", severity="warning", fingerprint="f",
                      title="실패율 급증 — m", message="24h 10건 중 5건")
    assert notify.format_alert(a, "opened").startswith("🟡 [LLMOps]")
    assert "해결" in notify.format_alert(a, "resolved")


def test_notify_send_noop_without_webhook(monkeypatch) -> None:
    import asyncio

    from app.core.config import settings

    monkeypatch.setattr(settings, "slack_webhook_url", "")
    assert notify.configured() is False
    assert asyncio.run(notify.send("x")) is False


# --- 디스크 사용량 ---------------------------------------------------------

@dataclass
class FakeModel:
    model_id: str
    provider: str
    size_bytes: int
    deprecated_at: date | None
    last_seen_at: datetime


def test_disk_usage_splits_active_and_reclaimable() -> None:
    from app.monitor.disk import build_disk_out

    rows = [
        FakeModel("gemma4:12b-mlx", "ollama", 8_000_000_000, None, NOW),
        FakeModel("old:26b", "ollama", 16_000_000_000, date(2026, 9, 5), NOW),      # deprecated 인데 아직 설치됨
        FakeModel("gone:7b", "ollama", 4_000_000_000, date(2026, 8, 1), NOW - timedelta(days=7)),  # 파일도 없음
    ]
    out = build_disk_out(rows, NOW)
    assert out.total_installed_bytes == 24_000_000_000
    assert out.reclaimable_bytes == 16_000_000_000      # 삭제하면 회수되는 용량
    p = out.providers[0]
    assert p.active_count == 1 and p.deprecated_installed_count == 1
    assert out.top_models[0].model_id == "old:26b"       # 설치된 것 중 큰 순
    assert out.top_models[-1].installed is False


def test_diff_empty_incoming_does_not_mass_deprecate() -> None:
    """소스가 일시적으로 빈 응답을 줘도 인벤토리 전체를 auto-deprecate 하지 않는다."""
    existing = [_existing("a:7b", size=1), _existing("b:7b", size=1)]
    d = diff_inventory("ollama", "macbook-mac1", existing, [], now=NOW)
    assert d.events == [] and d.deprecate == []
