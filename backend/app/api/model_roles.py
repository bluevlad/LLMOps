"""모델 ↔ consumer 역할 스냅샷 + 수명주기 판정 (모델 모니터링 화면용).

정본은 service-registry.yaml 의 llm_consumers (Ai-Legacy-bluevlad, private).
LLMOps 런타임은 private repo 를 읽을 수 없으므로 pipeline.py 의 토폴로지와 같은 방식으로
여기 스냅샷을 유지한다 — 모델/슬롯 변경 시 registry 를 먼저 고치고 본 스냅샷을 따라 갱신할 것.
(여기서 consumer 를 새로 "정의"하지 않는다. consumer_id 는 pipeline._NODES 와 일치해야 한다.)

role_tags 는 llm_models.role_tags(Layer 2, 수동) 가 비어 있을 때 이 스냅샷으로 채운다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, TypedDict


class ModelRole(TypedDict, total=False):
    model: str            # batch_run_stages.model 에 보고되는 문자열 (= llm_models.model_id)
    consumer_id: str | None
    role: str             # 슬롯 이름 (enrich / compose / analyze / translate / embedding / eval-base …)
    instrumented: bool    # False = 해당 경로는 batch_runs 보고가 없음 (호출 0 이 "미사용" 이 아님)
    note: str


# 2026-09-05 인벤토리 정리 이후 활성 5개 모델 기준 (memory: model-inventory-cleanup-2026-09)
MODEL_ROLES: list[ModelRole] = [
    # gemma4:12b-mlx — 프로덕션 주력 (단일화 결정 2026-09-05)
    {"model": "gemma4:12b-mlx", "consumer_id": "skillradar-synthesis", "role": "enrich"},
    {"model": "gemma4:12b-mlx", "consumer_id": "allergyinsight-paper-translate", "role": "translate"},
    {"model": "gemma4:12b-mlx", "consumer_id": "allergyinsight-rag-chat", "role": "rag-answer"},
    {"model": "gemma4:12b-mlx", "consumer_id": "allergyinsight-evolution-proposal", "role": "proposal"},
    {"model": "gemma4:12b-mlx", "consumer_id": "standup-weekly-newsletter", "role": "analyze"},
    # exaone3.5:7.8b — 한국어 콘텐츠 생성·정제 경로 (연구 전용 라이선스 → 골든셋 축적 라인 제외)
    {"model": "exaone3.5:7.8b", "consumer_id": "tech-briefing-newsletter", "role": "analyze"},
    {"model": "exaone3.5:7.8b", "consumer_id": "skillradar-synthesis", "role": "compose"},
    {"model": "exaone3.5:7.8b", "consumer_id": "standup-weekly-newsletter", "role": "compose"},
    # DocPipeline 파싱 정제 슬롯 (REFINE_LLM_MODEL, 2026-09-10) — TIPAIP2 서빙 v4 '오프라인 정제' 역할의 로컬 대응.
    # DocPipeline 은 insights/rounds 만 push 하고 batch_runs 보고는 아직 없음 → 호출 0 이 "미사용" 이 아님
    {"model": "exaone3.5:7.8b", "consumer_id": "docpipeline-refine", "role": "refine", "instrumented": False,
     "note": "파싱 전문 정제(머리말/꼬리말·깨짐·중복 제거) — batch_runs 미연동, 라이선스상 정제물 골든셋 승격 시 검토"},
    # qwen2.5-coder:14b — StandUp stage-2 (주 1회) 유일 실사용
    {"model": "qwen2.5-coder:14b", "consumer_id": "standup-weekly-newsletter", "role": "stage-2"},
    # qwen2.5:7b — 서비스 호출 없음, 평가·파인튜닝 베이스 전용 티어 (Apache 2.0)
    {"model": "qwen2.5:7b", "consumer_id": None, "role": "eval-base",
     "note": "비교 실험 / 파인튜닝 베이스 전용 — 프로덕션 호출 없음이 정상"},
    # nomic-embed-text — 임베딩 경로는 batch_runs 계측 밖
    {"model": "nomic-embed-text:latest", "consumer_id": "allergyinsight-rag-chat",
     "role": "embedding", "instrumented": False},
    {"model": "nomic-embed-text:latest", "consumer_id": "skillradar-synthesis",
     "role": "embedding", "instrumented": False},
]

# 수명주기 규칙 (인벤토리 정리 제안 5): 60일 호출 0 + 90일 비교 0 → 퇴출 후보
CALL_IDLE_DAYS = 60
COMPARISON_IDLE_DAYS = 90

LIFECYCLE_LABELS = {
    "active": "운영 중",
    "eval-only": "평가 전용",
    "idle": "유휴 (비교 실험만)",
    "retire-candidate": "퇴출 후보",
    "uninstrumented": "계측 밖",
    "deprecated": "deprecated",
}


def roles_for(model_id: str) -> list[ModelRole]:
    return [r for r in MODEL_ROLES if r["model"] == model_id]


def role_tags_for(model_id: str) -> list[str]:
    return sorted({r["role"] for r in roles_for(model_id)})


def consumers_for(model_id: str) -> list[str]:
    return sorted({r["consumer_id"] for r in roles_for(model_id) if r.get("consumer_id")})


def _to_dt(v: datetime | date | None) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)


def lifecycle_status(
    *,
    model_id: str,
    deprecated_at: date | None,
    last_call_at: datetime | None,
    last_comparison_at: datetime | None,
    now: datetime | None = None,
) -> str:
    """모델 1개의 수명주기 상태. 순수 함수 — 단위 테스트 대상."""
    now = now or datetime.now(timezone.utc)
    if deprecated_at is not None:
        return "deprecated"

    roles = roles_for(model_id)
    if roles and all(r.get("instrumented") is False for r in roles):
        return "uninstrumented"

    called = _to_dt(last_call_at)
    compared = _to_dt(last_comparison_at)
    recently_called = called is not None and now - called <= timedelta(days=CALL_IDLE_DAYS)
    recently_compared = compared is not None and now - compared <= timedelta(days=COMPARISON_IDLE_DAYS)

    if roles and all(r["role"] == "eval-base" for r in roles):
        return "eval-only" if recently_compared else "retire-candidate"
    if recently_called:
        return "active"
    if recently_compared:
        return "idle"
    return "retire-candidate"


def snapshot_consistency_errors(known_consumer_ids: set[str]) -> list[str]:
    """pipeline._NODES 의 consumer_id 와 어긋난 항목 — 테스트에서 검증."""
    errors: list[str] = []
    for r in MODEL_ROLES:
        cid = r.get("consumer_id")
        if cid is not None and cid not in known_consumer_ids:
            errors.append(f"{r['model']} → unknown consumer {cid}")
    return errors


def roles_as_dicts(model_id: str) -> list[dict[str, Any]]:
    return [
        {
            "consumer_id": r.get("consumer_id"),
            "role": r["role"],
            "instrumented": r.get("instrumented", True),
            "note": r.get("note"),
        }
        for r in roles_for(model_id)
    ]
