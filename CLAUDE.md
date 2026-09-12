# LLMOps 프로젝트 설정

> 3-머신 작업 환경(MacBook 편집·운영 / Desktop 터미널·AutoQA / Notebook TIPAIP2 격리) 규칙: [WORKSTATION_GUIDE.md](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/infrastructure/environments/WORKSTATION_GUIDE.md) — 개인 서비스 편집은 MacBook 에서만, Desktop 은 pull-only

> Git-First Workflow는 `~/GIT/CLAUDE.md`에서 자동 상속됩니다.
> 본 파일에는 LLMOps 고유 설정만 작성합니다.
>
> **전략·플랜·표준 정본**: [`Ai-Legacy-bluevlad/services/llmops/`](https://github.com/bluevlad/Ai-Legacy-bluevlad/tree/main/services/llmops) (private)
> 본 코드 저장소(public)에는 **구현 코드만** 둡니다.

## 프로젝트 개요

- **프로젝트명**: LLMOps
- **설명**: MacBook 에 설치된 로컬 LLM 모델(Ollama / MLX) 관제 에이전트 — 인벤토리·상주·호출·수명주기·이상 징후를 **모델 단위**로 (v0.3.0, 2026-09-12)
- **범위 밖**: consumer 관점 파이프라인 뷰(Flow Map·사용량·골든셋 큐레이션·비교 실험 화면) → DocPipeline `/admin`. 프로세스·컨테이너 헬스 → InfraWatcher
- **정본 플랜**: [`services/llmops/MODEL_MONITOR_AGENT_PLAN.md`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/services/llmops/MODEL_MONITOR_AGENT_PLAN.md)
- **GitHub**: https://github.com/bluevlad/LLMOps (public)
- **상태**: v0.3.0 전환 중 — M0·M1 완료, M2(DocPipeline 이관)·M2'(축소) 진행, M3(관제 강화) 대기
- **Sunset 평가일**: 2026-11-18 — [README §Sunset Criteria](./README.md#️-sunset-criteria-2026-11-18-평가)

## 기술 스택

- **Backend**: Python 3.11+ + FastAPI + SQLAlchemy 2.0 (asyncpg)
- **Frontend**: React 18 + Vite
- **Database**: PostgreSQL 15 (공유 컨테이너) — DB `llmops`/`llmops_dev` (단일 DB)
- **Auth**: Google OAuth 2.0 ID Token + JWT (LLMOps 자체 발급) — `LLMOPS_ADMIN_EMAILS` allowlist 만 admin, 그 외 로그인은 `llmops_guest` (데이터 접근 불가, 로그인 이력만 기록)
- **S2S 읽기**: `X-API-Key` ↔ `LLMOPS_READ_KEYS` (JSON `{client_id: key}`) — DocPipeline 이 batch-runs/usage/golden-set/comparisons 읽기 API 를 pull. ingest 키(`LLMOPS_INGEST_KEYS`)와 별도
- **수집 대상**: Ollama REST (`/api/tags`), MLX 디렉토리 (`~/.cache/huggingface/`)

## 포트 / 도메인

- Frontend: **4110**
- Backend: **9110**
- 도메인: `https://llmops.unmong.com/` (게이트웨이)
- `https://도메인:포트` 형식 금지 — [DOMAIN_MANAGEMENT.md](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/standards/infrastructure/DOMAIN_MANAGEMENT.md) 준수

## Git Workflow — `main` 기본 작업 / `prod` 배포 트리거

표준: [`MAIN_PROD_WORKFLOW.md`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/standards/git/MAIN_PROD_WORKFLOW.md), [`PROD_TO_MAIN_AUTO_SYNC.md`](https://github.com/bluevlad/Ai-Legacy-bluevlad/blob/main/standards/git/PROD_TO_MAIN_AUTO_SYNC.md)

| 브랜치 | 역할 |
|---|---|
| `main` | **코드 원본 (SSoT)** — 모든 구현은 여기서 시작 |
| `prod` | **OrbStack 배포 트리거** — `main → prod` merge only, 직접 commit 금지 |

### 표준 순서 (사용자가 "prod push" / "배포" 요청 시)

```bash
# 1) main 에서 작업 & push
git checkout main && git pull --rebase origin main
# ... 구현 & commit ...
git push origin main

# 2) prod 에 merge (자동 배포 트리거)
git checkout prod && git pull --rebase origin prod
git merge main && git push origin prod
git checkout main    # 다시 main 으로 복귀
```

- `.github/workflows/deploy-macos.yml` — prod push → OrbStack 배포
- `.github/workflows/sync-prod-to-main.yml` — prod-only commit 발생 시 main 자동 역동기화 (drift 안전망)
- 예외 케이스 (실수로 prod 에 작업한 경우) 는 표준 문서 §3 참조

## 데이터 모델 표준 (수정 시 반드시 참조)

| 표준 | 위치 |
|---|---|
| 모델 인벤토리 스키마 | `standards/ai/LLM_INVENTORY_SCHEMA.md` (Ai-Legacy-bluevlad) |
| 배치 보고 API 계약 | `standards/observability/BATCH_RUN_REPORTING.md` (Ai-Legacy-bluevlad) |
| Consumer SSoT | `infrastructure/service-registry.yaml` 의 `llm_consumers` 섹션 |

→ DDL / API payload / 필드 변경 시 위 3개를 **먼저** 수정 후 코드 반영.

## 개발 환경

### Docker 통합 (권장)

```bash
cp .env.example .env
# .env 의 CHANGE_ME 값 채움
docker compose up --build

curl http://localhost:9110/api/health
open  http://localhost:4110
```

### 백엔드 단독

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 9110 --reload
```

### 프론트엔드 단독

```bash
cd frontend
npm install
npm run dev    # → http://localhost:4110
```

## Sunset 조항 (재확인)

본 서비스는 2026-11-18 자기 데이터로 평가 → 자동 종료 / 조건부 유지 / 정식 유지 3분류.
v0.3.0 KPI = **관제 신호 기반 모델 조치 수** (README §Sunset Criteria 참조). 평가 commit 메시지 강제 포맷:

```
chore(llmops): 6-month review — <decision>
```

decision 값: `sunset` / `conditional-hold` / `keep-active`

## 안티패턴

- **/api/batch-runs 수신 시 동기 처리 금지** — 받자마자 ACK, 분석은 background
- **모델 비활성화 시 DELETE 금지** — `deprecated_at` 마크만 (과거 join 보존)
- **service-registry 우회하여 consumer 정의 금지** — SSoT 위반 → 분석 깨짐
- **InfraWatcher 와 기능 중복 금지** — 프로세스·컨테이너 헬스는 InfraWatcher, 모델 단위 관제는 LLMOps
- **파이프라인 뷰를 LLMOps 에 다시 만들지 않기** — Flow Map·사용량·골든셋 큐레이션·비교 화면은 DocPipeline `/admin` (LLMOps 는 읽기 API 만 제공). 토폴로지 정본은 DocPipeline `config/llm_flow_map.yaml`
- **`model_roles.KNOWN_CONSUMER_IDS` 우회 금지** — consumer 추가 시 registry → 스냅샷 순서
- **timestamptz 컬럼에 naive `datetime.utcnow()` 금지** — 세션 TZ(KST)로 해석돼 9시간 과거로 기록됨. `datetime.now(timezone.utc)` 사용 (2026-09-12 폴러 회귀)
- **LLMOps 에서 모델 조작(삭제·pull) 제공 금지** — 관측 plane 원칙. 알림은 근거만 주고 실행은 호스트에서
