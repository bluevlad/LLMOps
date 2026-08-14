"""label_scoring — 정답 라벨 자동 채점 (결정적 평가, LLM-as-judge 불필요).

분류형 태스크는 정답 라벨이 있으므로 judge 호출 없이 채점한다 —
비용 0, 재현성 100%. run_comparison.py 의 scoring.mode=label_match 에서 사용.

prompt spec 의 expected 형식:
  expected: "정답문자열"                     → 출력 첫 줄 정규화 비교 (1.0/0.0)
  expected: {field: "값", field2: [값, ...]}  → JSON 출력 필드별 채점
    - 스칼라 필드: 정규화 동등 비교 (1.0/0.0)
    - 리스트 필드: set-F1 (multi-label 부분 점수)

quality_score = 필드 점수 평균, quality_dimensions = 필드별 점수.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?|```\s*$", re.MULTILINE)


def _norm(v: Any) -> str:
    return str(v).strip().casefold()


def parse_json_output(text: str) -> dict[str, Any] | None:
    """모델 출력에서 JSON 오브젝트 추출. 코드펜스/전후 잡담 방어."""
    t = _FENCE_RE.sub("", text).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def set_f1(pred: Any, gold: list[Any]) -> float:
    """multi-label set-F1. pred 가 리스트가 아니면 0."""
    if not isinstance(pred, list):
        return 0.0
    p, g = {_norm(x) for x in pred}, {_norm(x) for x in gold}
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    tp = len(p & g)
    precision, recall = tp / len(p), tp / len(g)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_output(
    output_text: str, expected: dict[str, Any] | str
) -> tuple[float, dict[str, float], dict[str, Any]]:
    """(quality_score, 필드별 dimensions, 예측값) 반환."""
    if isinstance(expected, str):
        lines = [ln for ln in output_text.splitlines() if ln.strip()]
        pred = lines[0] if lines else ""
        score = 1.0 if _norm(pred) == _norm(expected) else 0.0
        return score, {"label": score}, {"label": pred.strip()}

    parsed = parse_json_output(output_text)
    dims: dict[str, float] = {}
    predicted: dict[str, Any] = {}
    for field, gold in expected.items():
        pred = parsed.get(field) if parsed else None
        predicted[field] = pred
        if isinstance(gold, list):
            dims[field] = round(set_f1(pred, gold), 3)
        else:
            dims[field] = 1.0 if pred is not None and _norm(pred) == _norm(gold) else 0.0
    score = round(sum(dims.values()) / len(dims), 3) if dims else 0.0
    return score, dims, predicted


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    """(gold, pred) 쌍의 macro-F1. 클래스 = gold ∪ pred 출현 라벨."""
    classes = {g for g, _ in pairs} | {p for _, p in pairs if p}
    if not classes:
        return 0.0
    f1s = []
    for c in classes:
        tp = sum(1 for g, p in pairs if g == c and p == c)
        fp = sum(1 for g, p in pairs if g != c and p == c)
        fn = sum(1 for g, p in pairs if g == c and p != c)
        f1s.append(2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0)
    return round(sum(f1s) / len(f1s), 3)


def compute_label_metrics(
    rows: list[tuple[str, dict[str, Any], dict[str, Any] | None]],
) -> dict[str, dict[str, dict[str, float | int]]]:
    """모델별 × 스칼라 필드별 accuracy / macro-F1.

    rows: (model_id, expected dict, predicted dict|None).
    리스트 필드(set-F1)는 dimensions 평균으로 이미 노출되므로 여기선 스칼라만.
    """
    by_model_field: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for model_id, expected, predicted in rows:
        for field, gold in expected.items():
            if isinstance(gold, list):
                continue
            pred = (predicted or {}).get(field)
            by_model_field[model_id][field].append(
                (_norm(gold), _norm(pred) if pred is not None else "")
            )

    out: dict[str, dict[str, dict[str, float | int]]] = {}
    for model_id, fields in by_model_field.items():
        out[model_id] = {}
        for field, pairs in fields.items():
            acc = sum(1 for g, p in pairs if g == p) / len(pairs)
            out[model_id][field] = {
                "n": len(pairs),
                "accuracy": round(acc, 3),
                "macro_f1": macro_f1(pairs),
            }
    return out
