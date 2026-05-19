# LLMOps

**로컬 LLM 의 능력 한계를 자체 데이터로 측정하고, paid API 대비 품질·비용 ROI 를 분기 단위로 리포트하는 R&D 분석 플랫폼.**
유사 AI agent 구축을 시작할 때 참고할 **기술 가이드** 를 산출한다.

> 🟡 **상태**: Phase 1.5 (목적 재정의 + 표준 v0.2.0) 진행 중 — Phase 1a~1d 골격 완료
> **운영 도메인**: https://llmops.unmong.com (Phase 1d 부터 활성)
> **전략·플랜·표준 정본**: [`Claude-Opus-bluevlad/services/llmops/`](https://github.com/bluevlad/Claude-Opus-bluevlad/tree/main/services/llmops) (private) — **로드맵·결정 이력·Phase 정의는 모두 정본 참조**
> 본 코드 저장소(public)에는 **구현 코드만** 둡니다.

---

## ⚠️ Sunset Criteria (2026-11-18 평가) — v0.2.0 인사이트 기반

> 본 서비스는 Phase 1 시작 후 **6개월 시점에 자기 자신이 수집한 데이터로 평가** 한다.
> 운영자 1명 · 14개 서브도메인 환경에서 좀비 서비스 방지를 위한 명시적 kill switch.
> R&D 도구로 재정의(2026-05-19)됨에 따라 **KPI 는 사용량이 아니라 "인사이트 리포트 산출량 + 영향력"** 으로 측정.

| 결과 | 조건 |
|------|------|
| 🔴 **자동 종료** | 분기당 인사이트 리포트(`models/{model_id}-report-YYYYQQ.md`) **0건 × 2 분기 연속** |
| 🟡 **조건부 유지** | 분기당 리포트 ≥ 1 + 영향력(리포트로 인한 consumer 모델 교체 결정 수) = 0 — Phase 5/6 신규 투자 중단 |
| 🟢 **정식 유지** | 분기당 리포트 ≥ 1 + 영향력 ≥ 1 + (paid-API 도입 결정 또는 절감 결정 근거 제공) |

상세 기준 (v0.1.0 deprecated 사유 포함): [정본 문서 §Sunset 조항](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/services/llmops/README.md#sunset-조항-v020--인사이트-기반으로-재정의)

### 흡수 절차 (자동 종료 시)

1. InfraWatcher 에 "AI/ML 인벤토리" 탭 신설 (Layer 1 만, Layer 2/3 폐기)
2. `llmops.unmong.com` → 301 redirect → `infrawatcher.unmong.com/ai`
3. PG `llmops` DB 는 read-only 마운트 후 6개월 보존 → 삭제
4. `services/llmops/` 디렉토리 → `services/_archived/llmops-2026/` 이전

평가 commit 메시지 강제 포맷: `chore(llmops): 6-month review — <sunset|conditional-hold|keep-active>`

---

## 한 줄 요약 (v0.2.0)

> "로컬 LLM 5개 워크로드(StandUp / AllergyInsight×2 / Auto-Tobe / Medium-Digest)의 **능력 한계를 측정**하고, **paid API 대비 품질·비용 ROI** 를 분기 단위로 리포트한다."

## 컨테이너 구성

| 컨테이너 | 포트 | 역할 |
|----------|------|------|
| llmops-frontend | 4110 | React 18 + Vite 운영자 UI |
| llmops-backend  | 9110 | FastAPI 인벤토리/계측 수신 API |

PostgreSQL 은 **공유 컨테이너**(`172.30.1.72:5432`)를 사용합니다. DB 명: `llmops`(prod) / `llmops_dev`(dev).

## 빠른 시작 (로컬 개발)

```bash
# 0) 환경변수 준비
cp .env.example .env
# .env 안의 CHANGE_ME 값을 채운다 (DATABASE_URL, JWT_SECRET_KEY, GOOGLE_OAUTH_CLIENT_ID)

# 1) Docker 통합 기동
docker compose up --build

# 2) 헬스 확인
curl http://localhost:9110/api/health    # → {"status": "ok"}
open  http://localhost:4110              # → React 앱
```

## 디렉토리 구조

```
LLMOps/
├── backend/                      # FastAPI 서버
│   ├── app/
│   │   ├── api/                  # 라우터 (health, auth, models, batch_runs)
│   │   ├── core/                 # 설정, 보안
│   │   ├── database/             # async engine + alembic
│   │   ├── models/               # SQLAlchemy ORM
│   │   ├── pollers/              # Ollama tags / MLX 디렉토리 스캔 잡
│   │   └── main.py
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                     # React 18 + Vite
│   ├── src/
│   │   ├── pages/                # LoginPage, ModelsPage
│   │   ├── components/
│   │   ├── api/
│   │   └── App.jsx
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md                     # 본 문서
└── CLAUDE.md                     # Claude Code 진입점
```

## 데이터 모델 (표준 문서)

- **모델 인벤토리 스키마**: [`standards/ai/LLM_INVENTORY_SCHEMA.md`](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/ai/LLM_INVENTORY_SCHEMA.md)
- **배치 보고 API 계약**: [`standards/observability/BATCH_RUN_REPORTING.md`](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/observability/BATCH_RUN_REPORTING.md)
- **Consumer SSoT**: [`infrastructure/service-registry.yaml`](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/infrastructure/service-registry.yaml) `llm_consumers` 섹션

## 로드맵 (요약)

| Phase | 코드 | 산출물 | 상태 |
|-------|:---:|--------|------|
| 0~1d | — | 정의 + 골격 + Backend/Frontend + Auto-deploy | ✅ |
| **1.5** | **(α)** | 표준 v0.2.0 (quality + paid-api) + 목적 재정의 + Sunset 갱신 | 🟡 진행 중 |
| **2** | **(γ)** | 무료 vs 유료 비교 실험 모듈 (로컬 ↔ Claude API 평행 실행) | 대기 |
| **3** | **(β)** | Consumer DB 통합 (AllergyInsight case study) | 대기 |
| 4 | — | 자동 인사이트 리포트 (월 1회 모델 교체 권고) | 대기 |
| 5 | — | shared SDK + 4개 consumer 계측 | 대기 |
| 6 | — | 시각화 확장 (모델↔서비스 매트릭스) | 대기 |

상세·순서 결정 근거·결정 이력은 [정본 로드맵](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/services/llmops/README.md#로드맵-v020) 참조.

## 인증

Google OAuth 2.0 (ID Token flow) — 다른 unmong 서비스(InfraWatcher / OpsConsole / AllergyInsight) 와 동일 패턴.
JWT 발급은 LLMOps 자체. role: `llmops_admin` / `llmops_viewer`.

## 관련 서비스

- **InfraWatcher** (`infrawatcher.unmong.com`) — 포트 헬스체크. LLMOps 종료 시 흡수 대상
- **OpsConsole** (`opsconsole.unmong.com`) — IDP. LLMOps 의 OAuth/구조 패턴 참조 원본
- **Claude-Opus-bluevlad** (private) — 표준·전략·SSoT
