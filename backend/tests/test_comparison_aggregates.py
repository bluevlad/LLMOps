"""Phase A: comparisons 모델별 집계 (build_detail) 단위 테스트 — DB 불필요."""
from datetime import datetime, timezone
from decimal import Decimal

from app.api.comparisons import build_detail
from app.models.comparison import ComparisonResult, ComparisonRun


def _result(prompt_id: str, model_id: str, provider: str, quality: str | None,
            duration_ms: int | None = 1000, tokens_out: int | None = 100,
            cost: str | None = None, dims: dict | None = None) -> ComparisonResult:
    return ComparisonResult(
        prompt_id=prompt_id,
        model_id=model_id,
        provider=provider,
        quality_score=Decimal(quality) if quality is not None else None,
        duration_ms=duration_ms,
        tokens_out=tokens_out,
        cost_usd=Decimal(cost) if cost is not None else None,
        quality_dimensions=dims,
    )


def _run(results: list[ComparisonResult]) -> ComparisonRun:
    run = ComparisonRun(
        id=1,
        case_name="test",
        prompt_set_id="ps1",
        started_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        judge_model="claude-opus-4-7",
    )
    run.results = results
    return run


def test_aggregates_win_rate_and_quality() -> None:
    run = _run([
        _result("p1", "qwen2.5:14b", "ollama", "0.8", dims={"factuality": 0.9}),
        _result("p1", "gpt-4o-mini", "openai-api", "0.6", cost="0.001"),
        _result("p2", "qwen2.5:14b", "ollama", "0.5", dims={"factuality": 0.7}),
        _result("p2", "gpt-4o-mini", "openai-api", "0.9", cost="0.002"),
    ])
    detail = build_detail(run)

    assert detail.run.prompt_count == 2
    assert detail.run.model_count == 2
    assert len(detail.results) == 4

    by_model = {a.model_id: a for a in detail.aggregates}
    qwen, gpt = by_model["qwen2.5:14b"], by_model["gpt-4o-mini"]

    assert qwen.avg_quality == 0.65
    assert qwen.win_count == 1 and qwen.win_rate == 0.5
    assert gpt.win_count == 1 and gpt.win_rate == 0.5
    assert qwen.dimensions == {"factuality": 0.8}
    assert qwen.total_cost_usd is None          # 로컬 = 비용 없음
    assert gpt.total_cost_usd == 0.003
    # tokens/s: 100 tok / 1s × 2건
    assert qwen.tokens_out_per_sec == 100.0
    # 정렬: avg_quality 내림차순
    assert detail.aggregates[0].model_id == "gpt-4o-mini"


def test_aggregates_tie_gives_shared_win() -> None:
    run = _run([
        _result("p1", "a", "ollama", "0.7"),
        _result("p1", "b", "ollama", "0.7"),
    ])
    by_model = {a.model_id: a for a in build_detail(run).aggregates}
    assert by_model["a"].win_count == 1
    assert by_model["b"].win_count == 1


def test_aggregates_handles_missing_metrics() -> None:
    run = _run([
        _result("p1", "a", "ollama", None, duration_ms=None, tokens_out=None),
    ])
    detail = build_detail(run)
    agg = detail.aggregates[0]
    assert agg.avg_quality is None
    assert agg.win_count == 0
    assert agg.avg_duration_ms is None
    assert agg.tokens_out_per_sec is None
