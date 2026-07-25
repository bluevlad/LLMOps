"""GET /api/pipeline/flow — 파이프라인 Flow Map (토폴로지 + 실행 상태 오버레이).

토폴로지 정본은 service-registry.yaml 의 llm_consumers (Claude-Opus-bluevlad, private).
LLMOps 런타임은 private repo 를 읽을 수 없으므로 여기 스냅샷을 유지한다 —
consumer 추가/변경 시 registry 를 먼저 고치고 본 토폴로지를 따라 갱신할 것.

노드 status:
- active  : 운영 중 + batch_runs 보고 연동됨 (라이브 통계 오버레이)
- pending : 서비스는 운영 중이나 LLMOps 계측/연동 대기
- planned : 미구현 (로드맵)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.batch_runs import consumer_summaries
from app.core.security import get_current_user
from app.database.session import get_db
from app.models.user import LlmopsUser

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

LAYERS = [
    {"id": "collect", "label": "수집"},
    {"id": "process", "label": "LLM 처리"},
    {"id": "store", "label": "저장 · 산출"},
    {"id": "evolve", "label": "평가 · 자가진화"},
]

# (id, label, layer, service, status, consumer_id, description)
_NODES: list[dict[str, Any]] = [
    # 수집
    {"id": "src-papers", "label": "논문 수집", "layer": "collect", "service": "allergy",
     "status": "active", "description": "PubMed 등 6개 소스 크롤링"},
    {"id": "src-kin", "label": "지식iN 문의 수집", "layer": "collect", "service": "allergy",
     "status": "active", "description": "KiN 질문 수집 → 분류 (kin-pipeline 잡, 08:00)"},
    {"id": "src-news", "label": "뉴스 수집", "layer": "collect", "service": "newsletter",
     "status": "active", "description": "네이버/구글 RSS + 테크 크롤링"},
    {"id": "src-corpus", "label": "사내 코퍼스", "layer": "collect", "service": "standup",
     "status": "active", "description": "QA·로그·픽스 코퍼스"},
    {"id": "src-skillradar", "label": "SkillRadar 크롤링", "layer": "collect", "service": "skillradar",
     "status": "active", "description": "교육과정·세미나·정책 커넥터 (03:00 ingest)"},
    # LLM 처리 (consumer_id = batch_runs 연동 키)
    {"id": "proc-translate", "label": "논문 번역", "layer": "process", "service": "allergy",
     "status": "active", "consumer_id": "allergyinsight-paper-translate",
     "description": "일일 05:00 KO 번역 (MLX EXAONE)"},
    {"id": "proc-rag-chat", "label": "RAG 챗 (알러지 상담)", "layer": "process", "service": "allergy",
     "status": "active", "consumer_id": "allergyinsight-rag-chat",
     "description": "가드레일 + 근거 인용 답변"},
    {"id": "proc-kin-answer", "label": "지식iN 답변 생성", "layer": "process", "service": "allergy",
     "status": "active", "consumer_id": "allergyinsight-kin-pipeline",
     "description": "수집→분류→RAG 답변 draft + 검수 보고"},
    {"id": "proc-tech-brief", "label": "뉴스 분석·추천", "layer": "process", "service": "newsletter",
     "status": "active", "consumer_id": "tech-briefing-newsletter",
     "description": "기사별 추천/근거 JSON (qwen2.5-coder)"},
    {"id": "proc-standup", "label": "주간 뉴스레터 생성", "layer": "process", "service": "standup",
     "status": "active", "consumer_id": "standup-weekly-newsletter",
     "description": "3-stage cascade (llama→qwen→exaone)"},
    {"id": "proc-skillradar", "label": "AI 요약·분류·편성", "layer": "process", "service": "skillradar",
     "status": "active", "consumer_id": "skillradar-synthesis",
     "description": "enrich(llama3.2) + digest 편성(exaone) + 임베딩"},
    # 저장·산출
    {"id": "store-chroma", "label": "ChromaDB (논문 지식)", "layer": "store", "service": "allergy",
     "status": "active", "description": "chunk 800/overlap 100, cosine"},
    {"id": "store-newsletter", "label": "뉴스레터 · 다이제스트", "layer": "store", "service": "newsletter",
     "status": "active", "description": "tech-briefing / 주간 / digest 발송"},
    {"id": "store-pgvector", "label": "pgvector (코퍼스·리소스)", "layer": "store", "service": "standup",
     "status": "active", "description": "standup ×4 + skillradar 768d"},
    # 평가·자가진화
    {"id": "evolve-golden", "label": "골든셋 (SFT/DPO)", "layer": "evolve", "service": "allergy",
     "status": "active", "description": "전문가 승인 → JSONL export"},
    {"id": "evolve-curation", "label": "골든셋 큐레이션 (LLMOps)", "layer": "evolve", "service": "llmops",
     "status": "active", "href": "/golden-set",
     "description": "content 샘플 → golden_set_items 승격·검수·export"},
    {"id": "evolve-finetune", "label": "Fine-tuning", "layer": "evolve", "service": "model-tuner",
     "status": "planned", "description": "골든셋 기반 추가학습 (별도 consumer)"},
    {"id": "evolve-compare", "label": "교사후보 평가", "layer": "evolve", "service": "llmops",
     "status": "active", "href": "/comparisons",
     "description": "LLM-as-judge 품질·속도·비용 비교"},
    {"id": "evolve-proposal", "label": "자가진화 제안", "layer": "evolve", "service": "allergy",
     "status": "active", "consumer_id": "allergyinsight-evolution-proposal",
     "description": "운영 데이터 기반 개선 제안 생성"},
]

# (source, target, kind)  kind: flow | feedback
_EDGES: list[tuple[str, str, str]] = [
    ("src-papers", "proc-translate", "flow"),
    ("proc-translate", "store-chroma", "flow"),
    ("store-chroma", "proc-rag-chat", "flow"),
    ("store-chroma", "proc-kin-answer", "flow"),
    ("src-kin", "proc-kin-answer", "flow"),
    ("proc-kin-answer", "evolve-golden", "flow"),
    ("src-news", "proc-tech-brief", "flow"),
    ("proc-tech-brief", "store-newsletter", "flow"),
    ("src-corpus", "proc-standup", "flow"),
    ("proc-standup", "store-newsletter", "flow"),
    ("proc-standup", "store-pgvector", "flow"),
    ("src-skillradar", "proc-skillradar", "flow"),
    ("proc-skillradar", "store-pgvector", "flow"),
    ("evolve-golden", "evolve-finetune", "flow"),
    ("proc-kin-answer", "evolve-curation", "flow"),
    ("proc-skillradar", "evolve-curation", "flow"),
    ("evolve-curation", "evolve-finetune", "flow"),
    ("evolve-finetune", "evolve-compare", "flow"),
    ("evolve-compare", "evolve-proposal", "flow"),
    ("evolve-proposal", "proc-rag-chat", "feedback"),
]


class FlowNodeStats(BaseModel):
    runs_total: int
    runs_success: int
    last_run_at: datetime | None
    avg_quality: float | None
    models: list[str]


class FlowNodeOut(BaseModel):
    id: str
    label: str
    layer: str
    service: str
    status: str
    description: str
    consumer_id: str | None = None
    href: str | None = None
    stats: FlowNodeStats | None = None


class FlowEdgeOut(BaseModel):
    source: str
    target: str
    kind: str


class FlowOut(BaseModel):
    layers: list[dict[str, str]]
    nodes: list[FlowNodeOut]
    edges: list[FlowEdgeOut]
    days: int
    generated_at: datetime


@router.get("/flow", response_model=FlowOut)
async def pipeline_flow(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(get_current_user),
) -> FlowOut:
    summaries = {s.consumer_id: s for s in await consumer_summaries(db, days)}

    nodes: list[FlowNodeOut] = []
    for n in _NODES:
        stats = None
        s = summaries.get(n.get("consumer_id"))
        if s is not None:
            stats = FlowNodeStats(
                runs_total=s.runs_total,
                runs_success=s.runs_success,
                last_run_at=s.last_run_at,
                avg_quality=s.avg_quality,
                models=s.models,
            )
        nodes.append(FlowNodeOut(**n, stats=stats))

    return FlowOut(
        layers=LAYERS,
        nodes=nodes,
        edges=[FlowEdgeOut(source=s, target=t, kind=k) for s, t, k in _EDGES],
        days=days,
        generated_at=datetime.now(timezone.utc),
    )
