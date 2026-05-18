# LLMOps

MacBook 호스트에 설치된 로컬 LLM(Ollama / MLX)의 **사용 현황·소요시간·ROI** 를 통합 관제하는 분석 대시보드.

> 🟡 **상태**: Phase 1 (Foundation) 진행 중 — 골격·도메인 등록 완료, backend/frontend 구현 대기
> **운영 도메인**: https://llmops.unmong.com (Phase 1 진입 후 활성)
> **전략·플랜·표준 정본**: [`Claude-Opus-bluevlad/services/llmops/`](https://github.com/bluevlad/Claude-Opus-bluevlad/tree/main/services/llmops) (private)
> 본 코드 저장소(public)에는 **구현 코드만** 둡니다.

---

## ⚠️ Sunset Criteria (2026-11-18 평가)

> 본 서비스는 Phase 1 시작 후 **6개월 시점에 자기 자신이 수집한 데이터로 평가** 한다.
> 운영자 1명 · 14개 서브도메인 환경에서 좀비 서비스 방지를 위한 명시적 kill switch.

### 🔴 자동 종료 (즉시 InfraWatcher 흡수)

다음 중 하나라도 만족 시:

- `batch_runs` 누적 < **500 행** (사실상 미사용)
- 등록된 5개 consumer 중 **3개 이상이 deprecated**
- 운영자 대시보드 접속 **월 1회 미만**

### 🟡 조건부 유지 (1년 재평가)

- `batch_runs` 500~5,000 행 + 월간 접속 1~4회
- → 화면은 유지, **Phase 3 시각화 신규 투자 중단**

### 🟢 정식 유지

- `batch_runs` > 5,000 행 + 월간 접속 5회 이상
- 또는 ROI 환산 (절약된 Claude API 비용) > 운영 비용

### 흡수 절차 (자동 종료 시)

1. InfraWatcher 에 "AI/ML 인벤토리" 탭 신설 (Layer 1 만, Layer 2/3 폐기)
2. `llmops.unmong.com` → 301 redirect → `infrawatcher.unmong.com/ai`
3. PG `llmops` DB 는 read-only 마운트 후 6개월 보존 → 삭제
4. `services/llmops/` 디렉토리 → `services/_archived/llmops-2026/` 이전

평가 commit 메시지 강제 포맷: `chore(llmops): 6-month review — <decision>`

---

## 한 줄 요약

> "5개 로컬 LLM 워크로드(StandUp 주간 합성·AllergyInsight RAG/번역·Auto-Tobe Agent-B·Medium-Digest)의 모델별 호출량·소요시간·ROI 를 단일 대시보드에서 본다."

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

## 로드맵

| Phase | 산출물 | 상태 |
|---|---|---|
| 0. 정의 | service-registry `llm_consumers` + 2개 표준 문서 | ✅ 2026-05-18 |
| 1. 골격 | repo + 도메인 + FastAPI/React + OAuth + `/api/models` + `/api/batch-runs` | 🟡 진행 중 |
| 2. 계측 | shared `llmops_client.py` + 4개 서비스 적용 | 대기 |
| 3. 시각화 | 서비스↔모델 매트릭스 + 파이프라인 히트맵 + 코퍼스 성장 탭 | 대기 (데이터 30일 후) |
| 4. 분석 | ROI 환산 + 품질 드리프트 회귀 | 대기 (데이터 60일 후) |

## 인증

Google OAuth 2.0 (ID Token flow) — 다른 unmong 서비스(InfraWatcher / OpsConsole / AllergyInsight) 와 동일 패턴.
JWT 발급은 LLMOps 자체. role: `llmops_admin` / `llmops_viewer`.

## 관련 서비스

- **InfraWatcher** (`infrawatcher.unmong.com`) — 포트 헬스체크. LLMOps 종료 시 흡수 대상
- **OpsConsole** (`opsconsole.unmong.com`) — IDP. LLMOps 의 OAuth/구조 패턴 참조 원본
- **Claude-Opus-bluevlad** (private) — 표준·전략·SSoT
