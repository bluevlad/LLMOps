# LLMOps

**MacBook 에 설치된 로컬 LLM 모델(Ollama / MLX) 을 관제하는 에이전트.**
인벤토리 · 상주 상태 · 호출/지연/토큰 · 수명주기 · 이상 징후를 **모델 단위**로 보고, 이상 신호를 알리고 조치를 기록한다.

> 🟡 **상태**: v0.3.0 (모델 관제 에이전트 한정) 전환 중 — M0·M1 완료, M2(파이프라인 뷰 DocPipeline 이관)·M2'(축소) 진행
> **범위 밖**: consumer 관점 파이프라인 뷰(Flow Map · 사용량 · 골든셋 큐레이션 · 비교 실험 화면) → [DocPipeline `/admin`](https://docpipeline.unmong.com/admin) (LLMOps 읽기 API 를 S2S 키로 pull). 프로세스·컨테이너 헬스 → InfraWatcher
> **정본 플랜**: [`services/llmops/MODEL_MONITOR_AGENT_PLAN.md`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/services/llmops/MODEL_MONITOR_AGENT_PLAN.md) (private)
> **운영 도메인**: https://llmops.unmong.com (Phase 1d 부터 활성)
> **전략·플랜·표준 정본**: [`Ai-Legacy-bluevlad/services/llmops/`](https://github.com/bluevlad/Ai-Legacy-bluevlad/tree/main/services/llmops) (private) — **로드맵·결정 이력·Phase 정의는 모두 정본 참조**
> 본 코드 저장소(public)에는 **구현 코드만** 둡니다.

---

## ⚠️ Sunset Criteria (2026-11-18 평가) — v0.3.0 관제 조치 기반

> 본 서비스는 **6개월 시점에 자기 자신이 수집한 데이터로 평가** 한다. 운영자 1명 환경에서 좀비 서비스 방지를 위한 명시적 kill switch.
> v0.3.0 (2026-09-12) 부터 KPI 는 **"관제 신호가 실제 모델 조치로 이어진 횟수"** 로 측정.

| 결과 | 조건 |
|------|------|
| 🔴 **자동 종료** | 6개월간 관제 신호(퇴출 후보 · 이상 징후 · 상주 이탈) 기반 조치 **0건** |
| 🟡 **조건부 유지** | 조치 ≥ 1건이나 전부 수동 확인으로 발견 (알림 없이) — M3 알림 투자 중단, 화면만 유지 |
| 🟢 **정식 유지** | 조치 ≥ 1건 + 그중 1건 이상이 LLMOps 이상 징후 화면·알림에서 **먼저** 발견됨 |

조치 근거는 정본 `reports/YYYY-MM-DD_<model>-<action>.md` 로 남긴다. 상세: [정본 §8](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/services/llmops/MODEL_MONITOR_AGENT_PLAN.md)

### 흡수 절차 (자동 종료 시)

1. InfraWatcher 에 "AI/ML 인벤토리" 탭 신설 (인벤토리 + 상주만)
2. `llmops.unmong.com` → 301 redirect → `infrawatcher.unmong.com/ai`
3. PG `llmops` DB 는 read-only 마운트 후 6개월 보존 → 삭제 (`batch_runs` 수신은 DocPipeline 또는 InfraWatcher 로 이관 결정 후)
4. `services/llmops/` 디렉토리 → `services/_archived/llmops-2026/` 이전

평가 commit 메시지 강제 포맷: `chore(llmops): 6-month review — <sunset|conditional-hold|keep-active>`

---

## 한 줄 요약 (v0.3.0)

> "MacBook 에 설치된 로컬 LLM 모델을 관제한다 — **어떤 모델이 설치·상주해 있고, 누가 얼마나 쓰며, 무엇을 퇴출·교체해야 하는가**."

consumer ×8 은 지금처럼 `POST /api/batch-runs` 로 보고한다 (모델별 지표의 유일한 원천). DocPipeline 은 `X-API-Key`(`LLMOPS_READ_KEYS`) 로 `/api/batch-runs/summary` · `/api/usage*` · `/api/golden-set*` · `/api/comparisons*` 를 pull 해 파이프라인 뷰를 그린다.

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
│   │   ├── api/                  # 라우터 (auth, models, model_monitor, batch_runs, usage, golden_set, comparisons, public)
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
│   │   ├── pages/                # HomePage, LoginPage, ModelsPage, ModelDetailPage (v0.3.0 — 모델 화면만)
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

- **모델 인벤토리 스키마**: [`standards/ai/LLM_INVENTORY_SCHEMA.md`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/standards/ai/LLM_INVENTORY_SCHEMA.md)
- **배치 보고 API 계약**: [`standards/observability/BATCH_RUN_REPORTING.md`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/standards/observability/BATCH_RUN_REPORTING.md)
- **Consumer SSoT**: [`infrastructure/service-registry.yaml`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/infrastructure/service-registry.yaml) `llm_consumers` 섹션

## 로드맵 (v0.3.0 — 모델 관제 에이전트)

| 단계 | 산출물 | 상태 |
|------|--------|------|
| M0 | 정본 문서 (MODEL_MONITOR_AGENT_PLAN) + 범위 한정 결정 | ✅ 2026-09-12 |
| M1 | `LLMOPS_READ_KEYS` S2S 읽기 인증 (batch-runs/usage/golden-set/comparisons) | ✅ 2026-09-12 |
| M2 | DocPipeline `/admin` LLM 파이프라인 패널 (Flow Map · 사용량 · 골든셋 · 비교 이력) | 🟡 진행 |
| M2' | LLMOps 축소 — pipeline/usage/golden-set/comparisons 화면 삭제, 홈 = 모델 관제 개요 | 🟡 진행 |
| M3 | 관제 강화 — 알림(상주 이탈·퇴출 후보·실패율·계약 위반) + 조치 기록, Slack 발송, 디스크 사용량, 인벤토리 변경 이력 | ✅ 2026-09-12 |

v0.2.0 Phase 3~6 (Consumer DB 통합 · 자동 인사이트 리포트 · SDK · 시각화) 는 폐기. 평가·리포트는 DocPipeline 평가 플랫폼 담당.
결정 이력은 [정본 README](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/services/llmops/README.md#결정-이력-요약) 참조.

## 관제 알림 (M3)

평가 잡이 10분마다 신호를 모아 `llm_alerts` 에 reconcile 한다 (fingerprint 로 중복 제거, 신호가 사라지면 자동 해결).

| kind | severity | 조건 |
|------|----------|------|
| `ollama_unreachable` | critical | Ollama `/api/ps` 도달 불가 |
| `expected_resident_missing` | warning | `EXPECTED_RESIDENT_MODELS` 모델이 메모리에 없음 |
| `failure_spike` | warning | 24h 실패 ≥ `ALERT_FAIL_MIN_COUNT` 이고 실패율 ≥ `ALERT_FAIL_RATE_THRESHOLD` |
| `contract_anomaly` | warning | 24h 보고 계약 위반 (미등록 모델명 · deprecated 호출 · model 누락) |
| `retire_candidate` | info | 60일 호출 0 + 90일 비교 0 |

- `SLACK_WEBHOOK_URL` 이 있으면 신규 알림 1회 + 해결 시 1회 발송. 비어 있으면 DB 기록만 (화면에는 그대로 표시)
- **조치 기록** (`POST /api/monitor/alerts/{id}/ack`) 이 Sunset KPI "관제 조치 수" 의 원천
- 인벤토리 변경(`llm_model_events`)은 폴러가 diff 로 생성 — 신규 설치 · 제거(auto deprecated) · 복귀 · digest/크기 변경
- 모델 삭제·pull 같은 **조작은 제공하지 않는다** (관측 plane 원칙). 삭제는 호스트에서 `ollama rm`

## 인증

Google OAuth 2.0 (ID Token flow) — 다른 unmong 서비스(InfraWatcher / OpsConsole / AllergyInsight) 와 동일 패턴.
JWT 발급은 LLMOps 자체. role: `llmops_admin` / `llmops_viewer`.

## 관련 서비스

- **DocPipeline** (`docpipeline.unmong.com`) — 평가 플랫폼 + LLM 파이프라인 뷰(Flow Map·사용량·골든셋·비교 이력). LLMOps 읽기 API 를 S2S 로 pull
- **InfraWatcher** (`infrawatcher.unmong.com`) — 포트·컨테이너 헬스체크. LLMOps 종료 시 흡수 대상
- **OpsConsole** (`opsconsole.unmong.com`) — IDP. LLMOps 의 OAuth/구조 패턴 참조 원본
- **Ai-Legacy-bluevlad** (private) — 표준·전략·SSoT
