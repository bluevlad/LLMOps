"""label_scoring 단위 테스트 — DB·LLM 불필요."""
from scripts.label_scoring import (
    compute_label_metrics,
    macro_f1,
    parse_json_output,
    score_output,
    set_f1,
)


# ── parse_json_output ──────────────────────────────────────────────


def test_parse_plain_json() -> None:
    assert parse_json_output('{"cost": "free"}') == {"cost": "free"}


def test_parse_fenced_json_with_prose() -> None:
    text = '다음은 결과입니다.\n```json\n{"cost": "paid", "audience": ["junior"]}\n```\n감사합니다.'
    assert parse_json_output(text) == {"cost": "paid", "audience": ["junior"]}


def test_parse_invalid_returns_none() -> None:
    assert parse_json_output("JSON 없음") is None
    assert parse_json_output('["리스트는", "dict가 아님"]') is None


# ── set_f1 ─────────────────────────────────────────────────────────


def test_set_f1_exact_and_partial() -> None:
    assert set_f1(["jobseeker"], ["jobseeker"]) == 1.0
    # pred {a,b} vs gold {a}: precision 0.5, recall 1.0 → F1 2/3
    assert abs(set_f1(["jobseeker", "junior"], ["jobseeker"]) - 2 / 3) < 1e-9
    assert set_f1(["senior"], ["jobseeker"]) == 0.0
    assert set_f1("리스트아님", ["jobseeker"]) == 0.0


# ── score_output ───────────────────────────────────────────────────


def test_score_output_dict_expected() -> None:
    out = '{"summary": "요약", "tags": ["ai"], "audience": ["jobseeker"], "cost": "Free"}'
    score, dims, predicted = score_output(out, {"cost": "free", "audience": ["jobseeker"]})
    assert dims == {"cost": 1.0, "audience": 1.0}      # 대소문자 무시
    assert score == 1.0
    assert predicted == {"cost": "Free", "audience": ["jobseeker"]}


def test_score_output_missing_field_and_unparseable() -> None:
    score, dims, _ = score_output('{"cost": "paid"}', {"cost": "paid", "audience": ["junior"]})
    assert dims == {"cost": 1.0, "audience": 0.0}
    assert score == 0.5

    score, dims, _ = score_output("JSON 아님", {"cost": "paid", "audience": ["junior"]})
    assert score == 0.0 and dims == {"cost": 0.0, "audience": 0.0}


def test_score_output_string_expected_first_line() -> None:
    score, dims, predicted = score_output("\n  Paid  \n부연 설명", "paid")
    assert score == 1.0 and dims == {"label": 1.0}
    assert predicted == {"label": "Paid"}
    assert score_output("free", "paid")[0] == 0.0


# ── macro_f1 / compute_label_metrics ───────────────────────────────


def test_macro_f1_penalizes_missing_class() -> None:
    # gold: a,a,b / pred: a,a,a → a: F1 0.8, b: F1 0 → macro 0.4
    assert macro_f1([("a", "a"), ("a", "a"), ("b", "a")]) == 0.4
    assert macro_f1([("a", "a"), ("b", "b")]) == 1.0


def test_compute_label_metrics_scalar_only() -> None:
    rows = [
        ("m1", {"cost": "free", "audience": ["jobseeker"]}, {"cost": "free"}),
        ("m1", {"cost": "paid", "audience": ["junior"]}, {"cost": "free"}),
        ("m2", {"cost": "free", "audience": ["jobseeker"]}, None),  # 호출 실패 → 오답 처리
    ]
    metrics = compute_label_metrics(rows)
    assert metrics["m1"]["cost"]["n"] == 2
    assert metrics["m1"]["cost"]["accuracy"] == 0.5
    assert metrics["m2"]["cost"]["accuracy"] == 0.0
    assert "audience" not in metrics["m1"]           # 리스트 필드는 제외
