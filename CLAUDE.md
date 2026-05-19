# LLMOps 프로젝트 설정

> Git-First Workflow는 `~/GIT/CLAUDE.md`에서 자동 상속됩니다.
> 본 파일에는 LLMOps 고유 설정만 작성합니다.
>
> **전략·플랜·표준 정본**: [`Claude-Opus-bluevlad/services/llmops/`](https://github.com/bluevlad/Claude-Opus-bluevlad/tree/main/services/llmops) (private)
> 본 코드 저장소(public)에는 **구현 코드만** 둡니다.

## 프로젝트 개요

- **프로젝트명**: LLMOps
- **설명**: 로컬 LLM (Ollama / MLX) 사용 현황·ROI 통합 관제 대시보드
- **GitHub**: https://github.com/bluevlad/LLMOps (public)
- **상태**: Phase 1 (Foundation) 진행 중
- **Sunset 평가일**: 2026-11-18 — [README §Sunset Criteria](./README.md#️-sunset-criteria-2026-11-18-평가)

## 기술 스택

- **Backend**: Python 3.11+ + FastAPI + SQLAlchemy 2.0 (asyncpg)
- **Frontend**: React 18 + Vite
- **Database**: PostgreSQL 15 (공유 컨테이너) — DB `llmops`/`llmops_dev` (단일 DB)
- **Auth**: Google OAuth 2.0 ID Token + JWT (LLMOps 자체 발급)
- **수집 대상**: Ollama REST (`/api/tags`), MLX 디렉토리 (`~/.cache/huggingface/`)

## 포트 / 도메인

- Frontend: **4110**
- Backend: **9110**
- 도메인: `https://llmops.unmong.com/` (게이트웨이)
- `https://도메인:포트` 형식 금지 — [DOMAIN_MANAGEMENT.md](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/infrastructure/DOMAIN_MANAGEMENT.md) 준수

## Git Workflow — `main` 기본 작업 / `prod` 배포 트리거

표준: [`MAIN_PROD_WORKFLOW.md`](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/git/MAIN_PROD_WORKFLOW.md), [`PROD_TO_MAIN_AUTO_SYNC.md`](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/git/PROD_TO_MAIN_AUTO_SYNC.md)

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
| 모델 인벤토리 스키마 | `standards/ai/LLM_INVENTORY_SCHEMA.md` (Claude-Opus-bluevlad) |
| 배치 보고 API 계약 | `standards/observability/BATCH_RUN_REPORTING.md` (Claude-Opus-bluevlad) |
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
README §Sunset Criteria 참조. 평가 commit 메시지 강제 포맷:

```
chore(llmops): 6-month review — <decision>
```

decision 값: `sunset` / `conditional-hold` / `keep-active`

## 안티패턴

- **/api/batch-runs 수신 시 동기 처리 금지** — 받자마자 ACK, 분석은 background
- **모델 비활성화 시 DELETE 금지** — `deprecated_at` 마크만 (과거 join 보존)
- **service-registry 우회하여 consumer 정의 금지** — SSoT 위반 → 분석 깨짐
- **InfraWatcher 와 기능 중복 금지** — 헬스체크는 InfraWatcher, 분석은 LLMOps
