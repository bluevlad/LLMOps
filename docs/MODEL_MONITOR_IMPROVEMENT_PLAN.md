# LLMOps 모델 관제 고도화 구현 가이드

- 작성일: 2026-09-12
- 분석 기준: `main`, `af19fa6`
- 상태: 1차 A/F-1/E-1 구현·로컬 검증 완료, 미배포. 상세 결과는 §9. 체크리스트는 항목별로 완료 여부를 표시한다.
- 목적: 수집 지속성 → 지표 정확성 → 알림 신뢰성 → 조치 효과 측정 순으로 모델 관제의 신뢰도를 높인다.
- 검토: §8에 코드 대조 검토 의견과 권고안이 있다. §3 단계 순서는 §8-3의 수정안을 함께 읽는다.

사용자 요청에 따라 이 저장소의 `docs/`에 작성한 구현 가이드다. 전략·표준 정본을 대체하지 않는다. 실제 DDL·API 계약 변경 전에는 정본의 `LLM_INVENTORY_SCHEMA.md`, `BATCH_RUN_REPORTING.md`, `service-registry.yaml`을 확인하고 변경안을 먼저 반영한다.

## 1. 범위와 설계 원칙

LLMOps는 모델의 설치·상주·호출·실패·지연·수명주기를 관측하고, 이상 신호와 운영자의 조치를 연결한다.

- consumer 파이프라인 화면·골든셋 큐레이션·평가 플랫폼은 DocPipeline 담당이다.
- 프로세스·컨테이너 상태는 InfraWatcher 담당이다. LLMOps는 자신의 수집·평가 상태를 노출하고 InfraWatcher가 중단을 감시한다.
- 모델 삭제·pull·자동 재시작은 구현하지 않는다. 조치에 필요한 근거와 외부 작업 결과를 기록한다.
- 관측 실패·미계측·표본 부족을 정상이나 미사용으로 해석하지 않는다.
- 기존 consumer 보고와 S2S 읽기 API는 호환성을 유지한다. 새 필드는 우선 선택적으로 추가한다.
- 별도 메시지 브로커나 시계열 저장소 도입보다 기존 PostgreSQL·APScheduler로 해결하는 것을 우선한다.

## 2. 분석 결과와 검증 범위

| 구분 | 확인 내용 | 한계 |
|---|---|---|
| 실행 상태 | 백엔드·프런트엔드 컨테이너가 healthy | 이미지와 분석 커밋의 일치 여부는 미확인 |
| 기존 테스트 | 로컬 백엔드 테스트 89개 통과 | 운영 DB 데이터 정확성과 장애 복구를 보장하지 않음 |
| 실행 재현 | 두 인벤토리 작업의 `next_run_time=None` | 로컬 스케줄러 등록 상태로 재현 |
| 실행 재현 | 호출·비교 이력이 없는 새 모델이 퇴출 후보로 분류 | 운영상 오분류 모델 수는 미집계 |
| 실행 재현 | Ollama 연결 실패 시 기존 상주 이탈 알림이 해결 대상으로 분류 | 운영 알림 이력에서 발생 빈도는 미집계 |
| 코드 검토 | 실패율 분모에 결과 미보고 포함, 발송 실패 재시도 없음, 모든 IntegrityError를 중복 처리 | 영향 건수는 운영 데이터로 추가 검증 필요 |

APScheduler 3.x의 `next_run_time=None`은 작업을 일시정지 상태로 등록한다. [공식 API 문서](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html#apscheduler.schedulers.base.BaseScheduler.add_job)

## 3. 구현 순서

각 단계는 독립적으로 검토·배포할 수 있는 변경 묶음이다. P0는 즉시 수정할 관제 신뢰성 문제, P1은 판단·전달 정확성, P2는 원인 분석·운영 효율 개선이다.

| 단계 | 우선순위 | 결과물 | 선행 조건 | 예상 공수 | 목표 배포 | 평가일 전 |
|---|---|---|---|---|---|---|
| A | P0 | 정기 수집 복구 | 없음 | 0.5일 | 1차, T+1일 | 필수 |
| F-1 | P0 | 실제 조치·확인 분리와 이력 | 없음 | 1~2일 | 1차, T+3일 이내 | 필수 |
| E-1 | P0 | 중요 알림 최소 재시도 | 없음 | 0.5~1일 | 1차, T+3일 이내 | 필수 |
| B | P0 | 수집 상태·관측 불가·안전한 해결 | A | 2~3일 | 2차, T+8일 이내 | 필수 |
| C | P1 | 수신 오류·계측률·실패율 | C-1 독립 가능 | 2~3일 | 2차, T+8일 이내 | 필수 |
| D | P1 | 관측 기간·계측 공백 기반 수명주기 | B, C | 1~2일 | 3차, T+14일 이내 | 조건부 |
| E-2 | P1 | outbox·backoff·전달 순서 | B, E-1 | 2~3일 | 3차, T+14일 이내 | 조건부 |
| F-2 | P1 | 화면 최신성·정렬·홈 | B, E-2 | 1~2일 | 3차, T+14일 이내 | 조건부 |
| G | P2 | 탐지·원인 분석·집계 비용 | B, C 및 운영 기준선 | 3~5일 | 기준선 확보 후 | 조건부 |

공수는 1인 작업일 추정이며 측정된 실적이 아니다. T는 실제 착수일이고 목표일은 제안값으로 배포 승인을 뜻하지 않는다. 구현 담당은 본 저장소 구현 담당자, 운영 검증·배포 담당은 운영 관리자이며 구체적 담당자 지정은 남아 있다. 2026-11-18 평가 전 필수 범위를 먼저 완료한다.

A는 독립 롤백 가능한 변경으로 유지한다. F-1/E-1을 같은 1차 묶음으로 준비하되 배포 지연 요인이 되면 A만 먼저 반영한다. §8의 검토 원문은 보존하며 실제 구현 차이는 §9에 기록한다.

## 4. 단계별 구현 가이드

### A. 정기 수집 복구

**대상:** [scheduler.py](../backend/app/jobs/scheduler.py), [main.py](../backend/app/main.py), [test_monitor_alerts.py](../backend/tests/test_monitor_alerts.py)

현재 Ollama·MLX 작업 모두 `next_run_time=None`으로 등록된다. 시작 시 1회 수집과 수동 refresh 외의 정기 수집이 실행되지 않는다.

- [x] 두 폴러의 `next_run_time`을 생략해 interval 기준으로 실행되게 한다. 시작 시 수집과의 중복을 고려해 첫 주기 정책을 명시한다.
- [x] 알림 평가의 timezone-aware 첫 실행 시각은 유지한다.
- [x] 소스 문자열 검사 대신 작업 등록 결과와 실제 실행 횟수를 검사한다.
- [x] 테스트는 네트워크·DB·Slack 호출을 가짜 작업으로 대체하고 짧은 interval을 사용한다.

**완료 기준:** 두 폴러의 다음 실행 시각이 존재하고, 테스트에서 각각 2회 이상 실행된다. 운영 검증에서는 최소 두 수집 주기 동안 성공 시각이 전진해야 한다. API 기동·수동 refresh도 유지된다.

### B. 수집 상태와 알림 판단 분리

**대상:** [pollers/](../backend/app/pollers/), [alerts.py](../backend/app/monitor/alerts.py), [disk.py](../backend/app/monitor/disk.py), [monitor API](../backend/app/api/monitor.py), [main.py](../backend/app/main.py)

#### B-1. 수집·평가 상태 영속화

새 상태 테이블 또는 동등한 구조에 다음 정보를 기록한다. 이름은 설계 예시이며 정본에서 확정한다.

| 필드 | 의미 |
|---|---|
| `source`, `host` | Ollama inventory/live, MLX inventory, alert evaluator 식별 |
| `last_attempt_at`, `last_success_at` | 실행 시도와 성공 시각 분리 |
| `last_error_code`, `consecutive_failures` | 정제된 실패 원인과 연속 실패 수 |
| `duration_ms`, `observed_count` | 수집 소요 시간과 관측 건수 |
| `expected_interval_seconds` | 최신성 판정의 기준 주기 |

- [ ] 수집 결과를 `success / failure / skipped`로 구분한다. 성공한 빈 결과와 네트워크 실패를 같은 `0`으로 반환하지 않는다.
- [ ] 오류에는 토큰·웹훅 URL·DB 접속 문자열을 저장하지 않는다.
- [ ] 마지막 평가 시각을 프로세스 전역 변수만으로 관리하지 않는다.
- [ ] 내부 관제 상태 API를 추가하고 stale 임계값은 수집 주기에 따라 설정한다.
- [ ] `/api/health`는 liveness로 유지하고 DB readiness와 관측 최신성을 별도 항목으로 제공한다.
외부 의존: InfraWatcher의 감시 등록은 타 저장소 작업으로 별도 추적한다. B-1의 완료 범위는 상태 저장과 내부 API 노출까지다.

#### B-2. 관측 불가 처리

- [ ] 신호 수집 결과에 평가 범위와 성공 여부를 포함한다. 모든 신호에 하나의 공통 성공 여부만 적용하지 않는다.
- [ ] 정상적으로 평가된 범위에서 사라진 신호만 해결한다.
- [ ] Ollama 연결 실패 시 `ollama_unreachable`은 열고, 기존 상주 이탈은 판단 보류한다. 복구 후 실제 상주 확인 시 해결한다.
- [ ] 설치 판정 창을 `expected_interval_seconds` 기반으로 산출하고 초과 관측은 unknown으로 표시한다.
- [ ] 디스크 설치 상태는 `present / absent / unknown`으로 구분한다. 오래된 관측은 unknown이며 마지막 확인 용량과 시각을 함께 표시한다.
- [ ] 빈 스캔에 대한 안전장치는 유지하되, 소스 접근 성공·연속 빈 관측으로 실제 전체 제거를 확정하는 절차를 추가한다.
- [ ] Ollama upsert와 inventory diff 기록은 하나의 트랜잭션으로 처리한다. 현재 upsert 내부 commit을 호출자 수준으로 이동한다.

**완료 기준:** 연결 실패를 복구로 처리하지 않는다. 수집 중단으로 용량이 0처럼 표시되지 않는다. 재시작 후 마지막 성공 시각이 유지된다. 부분 실패가 다른 정상 수집원의 판단을 막지 않는다.

### C. 수신 계약과 지표 정확성

**대상:** [batch_runs.py](../backend/app/api/batch_runs.py), [batch_run 모델](../backend/app/models/batch_run.py), [model_monitor.py](../backend/app/api/model_monitor.py), [alerts.py](../backend/app/monitor/alerts.py)

#### C-1. 조용한 저장 실패 방지

저장·유일성 검증은 요청 처리 중 수행하고 이상 탐지·집계·알림 평가는 background에서 수행한다. CLAUDE.md의 동기 분석 금지와 구분한다.

- [ ] `IntegrityError` 중 `uq_batch_runs_consumer_run` 유일성 위반만 중복으로 처리한다. 다른 위반은 구별된 오류로 반환하고 기록한다.
- [ ] quality judge 허용값, 점수 범위, 토큰·지연·재시도 음수, timezone 및 시작·종료 시간 순서를 검증한다.
- [ ] 기존 consumer의 실제 payload를 점검한 뒤 validation을 강화한다. 누락을 허용하는 기존 필드에 일괄 필수 제약을 추가하지 않는다.
- [ ] 정상 중복 재전송은 기존 응답 계약을 유지한다. 저장 성공 이전에는 accepted를 반환하지 않는다(현행 유지·회귀 방지).
- [ ] 수신 거절·저장 실패·중복·보고 지연을 별도 집계한다.

**완료 기준:** 잘못된 judge는 입력 오류로 응답하고 duplicate로 숨기지 않는다. 동시 중복 보고는 하나만 저장되며, DB CHECK·FK 위반은 중복으로 처리되지 않는다. PostgreSQL 통합 테스트로 확인한다.

#### C-2. 실패율과 계측률

| 항목 | 정의 |
|---|---|
| `calls` | 보고된 전체 stage 수. 실제 추론 시도 수와 같다고 가정하지 않음 |
| `known_outcomes` | `ok=true` 또는 `ok=false` 건수 |
| `unknown_outcomes` | `ok=null` 건수 |
| `failure_rate` | 실패 / known_outcomes. 분모 0이면 null |
| `outcome_coverage` | known_outcomes / calls. 분모 0이면 null |

- [ ] API·알림·목록·상세의 지표 정의를 공통화하되, 알림 전환 전에는 새 정의를 화면 표시용으로만 제공한다.
- [ ] 최소 known_outcomes 표본 수 미만이면 새 정의의 failure_spike를 생성하지 않는다.
- [ ] 기존/새 정의의 모델별 실패율을 함께 산출해 임계값을 조정한 뒤, 알림 분모와 임계값을 같은 배포에서 전환한다.
- [ ] 실패율 옆에 표본 수·계측률을 표시한다. 미계측을 성공률 100%로 표시하지 않는다.
- [ ] 토큰 입력·출력과 지연에도 각각 보고 표본 수를 제공한다. 한쪽 토큰만 누락된 경우도 식별한다.
- [ ] 계측률 부족은 별도 신호로 표현하고 실패 판단의 신뢰도를 표시한다.
- [ ] `content_truncated`는 저장용 본문 절단임을 명확히 표시한다. 추론 출력 중단은 별도 `finish_reason` 등으로 구분한다.

**완료 기준:** 실패 5건·결과 불명 95건이면 관측 실패율 100%, 계측률 5%로 표시한다. 결과가 모두 불명이면 실패율은 null이다. 토큰 0과 미보고 null을 구분한다.

### D. 수명주기 판단 보정

**대상:** [model_roles.py](../backend/app/api/model_roles.py), [model_monitor.py](../backend/app/api/model_monitor.py)

- [ ] `first_seen_at`, 도입일, 유효 관측 시작일을 이용해 신규 모델 유예기간을 적용한다.
- [ ] 기존 60일 호출·90일 비교 규칙을 적용하려면 필요한 관측 기간과 데이터 보존 범위가 충족돼야 한다.
- [ ] 일부 역할만 미계측인 경우에도 사용 여부 불명으로 처리한다. 실제 호출이 관측되면 active 판정을 우선할 수 있다.
- [ ] `new / insufficient-observation` 등 보류 상태와 사유를 정본에서 확정한다.
- [ ] 상주 필수·운영자 유지 지정·평가 전용 역할과 퇴출 후보 정책의 관계를 명시한다.
- [ ] 후보 근거에 마지막 호출·비교·관측 범위·미계측 역할을 포함한다.
- [ ] 수동 deprecated와 자동 제거 상태를 notes 문자열이 아닌 구조화된 원인으로 구분하는 방안을 검토한다.

**완료 기준:** 신규 모델은 즉시 후보가 되지 않는다. 수집 공백과 미계측 경로가 있는 모델은 무조건 퇴출 후보로 판정하지 않는다. 충분한 관측 조건을 충족한 장기 미사용 모델은 기존 정책대로 후보가 된다.

### E. 알림 전달 신뢰성과 동시성

**E-1(P0, 완료):** 열린 critical/warning 미발송 알림 재시도, DB 영속 횟수·최소 간격·상한·로그. §9 참조. 아래는 **E-2(P1)**의 완전한 전달 보강 체크리스트다.

**대상:** [alerts.py](../backend/app/monitor/alerts.py), [notify.py](../backend/app/monitor/notify.py), [monitor 모델](../backend/app/models/monitor.py)

- [ ] 알림 상태 변경과 notification outbox 생성을 한 DB 트랜잭션에 저장한다.
- [ ] 발송 작업은 commit된 outbox를 읽어 처리한다. 웹훅 호출 동안 알림 평가 트랜잭션을 열어 두지 않는다.
- [ ] outbox에 `alert_id`, 이벤트 종류, 상태, 시도 수, 다음 시도 시각, 마지막 오류, 성공 시각을 저장한다.
- [ ] 지수 backoff와 제한된 재시도를 적용하고, 최종 실패를 화면에 노출한다. HTTP 429 응답의 재시도 지시를 반영한다.
- [ ] DB 잠금 또는 동등한 방식으로 수동 평가와 정기 평가를 직렬화한다. `max_instances=1`만으로 API와 여러 프로세스 간 경쟁이 해결된다고 가정하지 않는다.
- [ ] 동일 알림의 opened/resolved 이벤트 순서를 보장하고 unique 제약으로 이벤트 중복 생성을 방지한다.
- [ ] 웹훅 성공 직후 프로세스가 종료되면 재전송될 수 있음을 고려한다. exactly-once를 보장한다고 표현하지 않는다.
- [ ] 인벤토리 알림도 같은 발송 경로로 통합한다.

**완료 기준:** 첫 발송 실패 후 성공할 때까지 재시도된다. DB 저장 실패 시 발송하지 않는다. 발송 중 재시작해도 대기 이벤트가 사라지지 않는다. 동시 평가로 열린 fingerprint가 중복되지 않는다. 테스트는 Slack을 모킹한다.

### F. 관제 화면과 조치 효과 기록

**F-1(P0, 완료):** 조치 스키마·읽기/쓰기/취소 API·최소 입력 화면·KPI 조회. 선행 조건 없음. **F-2(P1):** 자동 갱신·stale·정렬·홈 재구성.

**대상:** [AlertsPanel.jsx](../frontend/src/components/AlertsPanel.jsx), [ModelsPage.jsx](../frontend/src/pages/ModelsPage.jsx), [HomePage.jsx](../frontend/src/pages/HomePage.jsx), [monitor API](../backend/app/api/monitor.py)

- [ ] 알림·사용 통계에 자동 갱신을 추가하고 화면별 마지막 성공 갱신 시각을 표시한다.
- [ ] 갱신 실패 시 마지막 데이터는 유지하되 stale 상태를 표시한다. 요청 취소와 늦게 도착한 응답의 덮어쓰기를 처리한다.
- [ ] 운영자 홈은 수집 상태, 미확인 critical, 영향 모델·consumer, 최근 변경과 조치를 우선 표시한다.
- [ ] 알림 목록은 severity 우선 정렬을 DB limit 이전에 적용하고, 열린 알림이 단순 기간 필터 때문에 숨겨지지 않게 한다.
- [x] acknowledge와 action을 분리한다. 확인만으로 실제 조치 KPI를 증가시키지 않는다.
- [x] 조치에 종류·내용·실행자·시각·발견 경로·근거 링크·검증 결과를 기록한다. 취소·정정은 이력으로 추가한다.
- [x] 기존 ack와 메모는 기존 컬럼에 그대로 보존하고 실제 조치로 자동 승격하지 않는다. 이후 확인·취소 전후는 audit log에 기록한다.
- [x] viewer/S2S는 허용된 읽기 범위를 유지하고 조치 쓰기는 admin으로 제한한다.

**완료 기준:** 장시간 열린 화면에 새 알림이 나타난다. 빈 조치로 KPI가 증가하지 않는다. 취소 전 이력이 남는다. 모델 변경 후 회복 확인과 알림에서 먼저 발견했는지 여부를 조회할 수 있다.

### G. 탐지 고도화와 집계 비용 개선

#### G-1. 탐지 및 원인 분석

- [ ] 짧은 실패율 창과 24시간 창을 병행한다. 초기 후보는 5~15분이지만 최소 표본 수와 consumer 실행 주기를 확인한 뒤 확정한다.
- [ ] consumer별 기대 보고 주기·유예시간을 registry 기반으로 관리한다. 주간 배치에 실시간 무호출 임계값을 적용하지 않는다.
- [ ] `received_at - started_at`과 마지막 수신 시각으로 보고 지연을 구분한다. 배치 시작 시각만으로 개별 stage 발생 시각을 정확히 알 수 없는 한계를 표시한다.
- [ ] 모델×consumer×stage별 지연 기준선, timeout·재시도·오류 유형을 제공한다.
- [ ] TTFT·생성 속도 등은 해당 경로에서 수집 가능한 경우 선택 필드로 도입한다. 전체 duration만으로 임의 추정하지 않는다.
- [ ] digest 변경·상주 관측·실패 급증·조치를 모델 타임라인에 연결한다. 시간적 상관관계를 원인 확정으로 표현하지 않는다.
- [ ] provider·host가 다른 동일 이름 모델을 합산하지 않도록 모델 인스턴스 식별 계약을 설계한다. 기존 문자열 보고는 alias 매핑과 모호성 표시로 이행한다. 현재 Ollama name:tag와 MLX org/repo의 무충돌은 명명 관행에 의존하며 계약으로 강제되지 않는다.

#### G-2. 집계 및 파일 스캔

- [ ] 모델 상세 조회 시 usage·daily·last-call·comparison 쿼리에 대상 필터를 전달한다.
- [ ] 비교 이력은 페이지네이션하고 목록 구성에 필요 없는 전체 결과 로딩을 줄인다.
- [ ] 개발 DB의 대표 데이터로 실행계획·응답시간을 측정한 후 `started_at`, join 키, 모델 필터 인덱스를 검토한다.
- [ ] 사전 집계는 필요성이 확인될 때 도입한다. 일별 p95의 평균을 전체 기간 p95로 사용하지 않는다.
- [ ] MLX 파일 순회는 이벤트 루프 밖에서 수행하고 동시 실행을 제한한다.
- [ ] HF cache의 symlink·공유 파일 중복 계상을 확인한다. 논리 모델 크기와 실제 회수 가능 디스크 공간을 구분한다.
- [ ] 원문·상세 이벤트의 보존 정책이 수명주기 판단에 필요한 장기 사용 근거를 지우지 않도록 설계한다.

**완료 기준:** 저빈도 consumer에서 오탐이 억제되고, 지연 저하를 작업 유형별로 설명할 수 있다. 집계 개선 전후 결과가 같으며 대표 데이터에서 응답시간과 쿼리 비용의 변화를 기록한다.

## 5. 스키마·API 변경 및 배포

### 변경 원칙

1. 구현 직전 운영 이미지·커밋·마이그레이션 상태를 확인한다.
2. 정본 계약에 상태·집계 정의·추가 필드를 반영한다.
3. additive migration으로 수집 상태, outbox, 조치 이력을 추가한다. 기존 컬럼 삭제와 의미 변경은 별도 단계로 분리한다.
4. 백엔드가 기존 consumer payload를 수용하는 상태에서 API를 먼저 배포한다.
5. 프런트엔드와 S2S consumer를 새 필드에 맞춘 뒤 엄격한 validation을 적용한다.
6. backfill은 근거가 있는 정보만 채운다. 과거 정상 관측 기간·실제 조치·발송 성공을 추정해 생성하지 않는다.

### 배포 후 확인

- [ ] 외부 의존(InfraWatcher 별도 작업): heartbeat 만료 감시 등록, DB 장애로 상태 저장이 불가능할 때의 탐지 확인

- [ ] Ollama·MLX의 최소 두 주기 동안 마지막 성공 시각 증가 확인
- [ ] 실제 보고 유입, 중복 재전송, 새로운 validation 거절 건수 확인
- [ ] 실패율·계측률을 표본 SQL 집계와 대조
- [ ] 새 알림은 과거 데이터 재평가로 대량 생성되지 않는지 확인하고 초기 평가는 발송 없이 검토
- [ ] 승인된 검증 채널에서 발송·재시도·해결 순서 확인
- [ ] 재시작 후 수집 상태·대기 발송·조치 이력 유지 확인
- [ ] 읽기 권한·쓰기 권한 및 DocPipeline S2S 호환성 확인

### 롤백

- A의 스케줄러 복구는 후속 단계 롤백과 분리한다.
- 신규 규칙·발송 worker를 독립적으로 비활성화할 수 있게 한다.
- outbox를 비활성화한 뒤 이전 코드의 직접 발송과 동시에 동작하지 않도록 확인한다.
- additive migration은 이전 앱과 호환되도록 유지하고, 데이터가 쌓인 테이블을 자동 downgrade로 삭제하지 않는다.
- 문제 발생 시 이전 이미지 복구와 pending 이벤트 처리 방침을 함께 기록한다.

## 6. 검증 전략

| 계층 | 필수 시나리오 |
|---|---|
| 단위 | 미계측 실패율, 신규 모델 유예, 부분 관측 실패, 빈 inventory, 정상 복구 |
| 스케줄러 | 실제 interval 반복 실행, 중복 시작 방지, 정상 종료 |
| PostgreSQL 통합 | 제약 위반 구별, upsert+diff 원자성, 동시 평가, outbox 저장·재시도, 조치 이력 |
| API 계약 | 기존 ingest payload, 중복 응답, null 지표, S2S 읽기, admin 쓰기 |
| 화면 | 자동 갱신, stale 표시, 실패 시 이전 데이터 유지, 조치 오류 표시 |
| 운영 확인 | 수집 두 주기, 실제 보고 표본 대조, 외부 heartbeat 감시 |

기존 테스트는 다음 명령으로 실행한다.

```bash
cd backend
.venv/bin/python -m pytest -q
```

추가 통합 테스트는 별도의 테스트 DB에서 수행한다. 테스트 실행이 운영 lifespan 폴러나 실제 Slack 발송을 유발하지 않도록 의존성을 격리한다. DB 없는 인증·순수 함수 테스트 통과만으로 수집·발송 정상 동작을 판정하지 않는다.

## 7. 운영 성과 지표와 남은 결정

개선 성과는 화면 수 대신 다음 지표로 평가한다. 목표값은 운영 기준선을 측정한 후 확정한다.

- 수집·평가 최신성 충족률 및 최장 공백
- consumer별 결과·토큰·지연 계측률
- 알림 발송 성공률·최종 실패 수·전달 지연
- 운영자가 오탐으로 분류한 알림 비율
- 최초 이상 관측 → 알림 → 확인 → 실제 조치 → 복구 확인 소요 시간
- LLMOps 화면·알림에서 먼저 발견돼 검증된 모델 조치 수

구현 시작 전 확정할 항목은 stale 임계값, consumer별 기대 보고 주기, 모델별 상주 정책, 수명주기 유예기간, 관측 신뢰도 기준, 상세 데이터 보존기간이다. 이는 운영 데이터와 registry를 바탕으로 결정하며 본 문서의 예시값을 운영 기본값으로 바로 적용하지 않는다.

## 8. 검토 의견과 권고안

- 검토일: 2026-09-12
- 검토 기준: `main`, `af19fa6` 코드 대조 + 백엔드 테스트 89개 실행(0.45초, 전부 통과)
- 결론: §2 진단은 코드와 일치한다. 수정이 필요한 것은 진단이 아니라 **단계 순서와 의존 관계**다.

### 8-1. 사실 확인 결과

§2에 적힌 여섯 항목을 코드로 재확인했다. 반증된 항목은 없다.

| 주장 | 확인 위치 | 결과 |
|---|---|---|
| 두 폴러가 일시정지 상태로 등록 | `backend/app/jobs/scheduler.py` — `ollama_poller`·`mlx_poller` 의 `next_run_time=None`, `alert_evaluator` 만 tz-aware 시각 보유 | 일치 |
| Ollama 연결 실패가 상주 이탈을 해결 처리 | `alerts.py` `resident_signals` 가 unreachable 시 단일 신호만 반환 → `reconcile` 이 기존 `expected_resident_missing` 을 `to_resolve` 로 분류, Slack 해결 메시지까지 발송 | 일치 |
| 모든 `IntegrityError` 를 중복 처리 | `batch_runs.py` `receive_batch_run` 의 `except IntegrityError` 가 위반 종류를 구별하지 않음 | 일치 |
| 실패율 분모에 결과 미보고 포함 | `model_monitor.py` `_usage_by_model` 이 `count(id)` 를 분모, `count(...).filter(ok is false)` 를 분자로 사용 | 일치 |
| 발송 실패 재시도 없음 | `evaluate_and_store` 가 `to_open` 에만 발송, `notify.send` 실패 시 `notified_at` 미기록 | 일치 (§8-2 권고 2 참조) |
| DB 없는 테스트만 존재 | 테스트 89개가 0.45초에 종료 — PostgreSQL 통합 경로 없음 | 일치 |

### 8-2. 권고안

아래 검토 체크리스트의 내용은 §3~5 및 §9에 반영했다. 원문 체크박스는 검토 당시 상태로 보존하며, 현재 구현 완료 여부는 §9를 기준으로 한다.

우선순위 표기는 §3 기준이며, 변경을 제안하는 항목만 적는다.

**권고 1 — F의 acknowledge/action 분리를 P1에서 P0로 올리고 A와 함께 배포한다. (최우선)**

Sunset KPI 는 관제 신호 기반 조치 수인데, 현재 `POST /api/monitor/alerts/{id}/ack` 는 확인과 조치를 같은 필드에 기록한다. §5 변경 원칙 6이 backfill 을 금지하므로, 분리 시점 이전에 쌓인 기록은 평가 시점에 KPI 로 환산할 수 없다. 2026-11-18 평가까지 남은 기간이 두 달이므로 지연 비용이 그대로 KPI 손실이 된다.

§3 의존 표는 F의 선행 조건을 B·E로 적었으나, `backend/app/api/monitor.py` 의 ack 핸들러와 `LlmAlert` 의 ack 컬럼은 수집 상태 테이블·outbox와 코드 의존이 없다. 화면 자동 갱신·홈 재구성은 B·E 이후로 남기되, **조치 기록 스키마와 쓰기 API 만 A와 같은 배포에 포함한다.**

- [ ] F를 F-1(조치 기록 분리, P0)과 F-2(화면·갱신·정렬, P1)로 분할한다.
- [ ] F-1의 선행 조건을 "없음"으로 정정한다.

**권고 2 — E를 최소 재시도(P0)와 outbox(P1)로 분할한다.**

현재 발송 실패한 알림은 다음 평가 주기에 `to_update` 로 분류되고, 그 경로에는 발송 로직이 없다. 즉 첫 Slack 발송이 실패한 critical 알림은 이후 영구히 침묵한다. 완전한 outbox·backoff 는 P1이 타당하나, 다음 주기에 재시도할 최소 방어는 A·B와 같은 배포에 넣을 수 있다.

- [ ] E-1(P0): 열린 알림 중 `notified_at` 이 비어 있고 severity 가 critical/warning 인 건을 다음 주기에 재발송 대상으로 포함한다. 재시도 횟수 상한과 로그를 함께 남긴다.
- [ ] E-2(P1): 기존 E 체크리스트 전체(outbox·트랜잭션 분리·backoff·직렬화)를 유지한다.

**권고 3 — C-1과 프로젝트 안티패턴의 관계를 문서에 명시한다.**

CLAUDE.md 안티패턴은 "/api/batch-runs 수신 시 동기 처리 금지 — 받자마자 ACK, 분석은 background" 다. 현재 구현은 commit 이후 202를 반환하므로 C-1의 "저장 성공 이전에는 accepted 를 반환하지 않는다" 는 **이미 충족된 회귀 방지 항목**이다. 해석 충돌을 막기 위해 다음을 명기한다.

- [ ] C-1 서두에 "저장·유일성 검증은 동기, 이상 탐지·집계·알림 평가는 background" 라는 경계 문장을 추가한다.
- [ ] 해당 체크리스트 항목에 "현행 유지·회귀 방지" 표기를 단다.

**권고 4 — C-2의 분모 교체를 알림 임계값 재조정과 같은 배포에 묶는다.**

현재 기본값은 `ALERT_FAIL_RATE_THRESHOLD=0.2`, `ALERT_FAIL_MIN_COUNT=3` 이며, 실패율은 전체 stage 수를 분모로 계산된다. 분모를 `known_outcomes` 로 바꾸면 계측률이 낮은 consumer 에서 실패율이 급등해 `failure_spike` 가 과다 발생한다.

- [ ] C-2 체크리스트에 "최소 `known_outcomes` 표본 수 미만이면 failure_spike 를 생성하지 않는다" 를 추가한다.
- [ ] 분모 변경 배포 전에 기존 정의와 새 정의의 모델별 실패율을 함께 산출해 임계값을 재설정한다.
- [ ] 임계값 재설정 전까지는 새 정의를 화면 표시용으로만 쓰고 알림 판단에는 적용하지 않는다.

**권고 5 — B-1의 InfraWatcher 연동을 외부 의존으로 분리한다.**

"InfraWatcher 에서 heartbeat 만료를 감지하도록 연결한다" 는 타 저장소 변경이라 본 문서의 체크박스로는 완료 판정이 불가능하다.

- [ ] 본 문서의 B-1 범위는 "수집·평가 상태 저장 + 내부 관제 상태 API 노출" 까지로 한정한다.
- [ ] 감시 등록은 §5 배포 후 확인의 외부 의존 항목으로 옮기고 InfraWatcher 측 작업으로 별도 추적한다.

**권고 6 — G-1의 동일 이름 모델 합산 위험에 현재 상태 근거를 남긴다.**

`_usage_by_model` 은 `BatchRunStage.model` 문자열로만 group by 하고 `_build_stats_row` 는 `r.model_id` 로 조회한다. 따라서 같은 이름이 두 provider 에 존재하면 두 행에 동일한 사용량이 붙는다. 현재는 Ollama 가 `name:tag`, MLX 가 `org/repo` 형식이라 충돌하지 않으나 이는 설계적 보장이 아니라 명명 관행에 의한 우연한 회피다.

- [ ] P2 유지에 동의한다. 다만 G-1 해당 항목에 "현재 무충돌은 명명 관행에 의존하며 계약으로 강제되지 않음" 을 근거로 명기한다.

**권고 7 — 단계별 공수·담당·목표일과 평가일 전 필수 범위를 명시한다.**

현 문서는 우선순위는 있으나 일정 정보가 없어 2026-11-18 평가 전에 무엇을 반드시 끝낼지 결정할 수 없다.

- [ ] §3 표에 예상 공수와 목표 배포일 열을 추가한다.
- [ ] 평가일 전 **필수**: A, F-1, E-1, B, C. **조건부**: D, E-2, F-2, G. 이 구분을 §3에 표기한다.

**권고 8 — 설치 판정 창을 수집 주기에서 유도하도록 B-2에 연결한다.**

`backend/app/monitor/disk.py` 의 `INSTALLED_WINDOW` 는 3시간 고정이고 MLX 스캔 주기는 1시간이다. 폴러가 멈춘 상태로 3시간이 지나면 설치 용량이 0으로 표시된다. B-1이 이미 `expected_interval_seconds` 를 정의하므로 상수를 거기서 유도하면 B-2의 완료 기준("수집 중단으로 용량이 0처럼 표시되지 않는다")이 코드 수준에서 닫힌다.

- [ ] B-2에 "설치 판정 창을 `expected_interval_seconds` 기반으로 산출하고, 창을 넘긴 관측은 `unknown` 으로 표시한다" 를 추가한다.

### 8-3. 권고 반영 시 구현 순서

| 배포 | 포함 | 근거 |
|---|---|---|
| 1차 | A, F-1, E-1 | 수집 복구 + KPI 원천 확보 + 알림 영구 침묵 차단. 스키마 변경은 additive 한 건 |
| 2차 | B, C | 상태 영속화·관측 불가 처리·수신 계약. 1차 복구를 지연시키지 않음 |
| 3차 | D, E-2, F-2 | 판단 보정·전달 신뢰성·화면. 2차의 상태·지표 정의에 의존 |
| 4차 | G | 운영 기준선 측정 이후 착수 |

§3의 "첫 배포는 A에 집중한다" 는 원칙은 유지한다. F-1과 E-1은 각각 단일 컬럼 추가와 발송 조건 확장 수준이며 A의 롤백 단위를 침범하지 않는 범위에서만 포함한다. 그 이상으로 커지면 1차에서 제외하고 A만 먼저 배포한다.

## 9. 1차 구현 결과 (2026-09-12)

### 완료 범위

- **A:** Ollama/MLX 작업의 paused 등록을 제거했다. lifespan 시작 수집 후 interval마다 실행한다. 실제 scheduler에서 두 폴러가 각각 2회 이상 실행되고, 중복 start가 작업을 중복 등록하지 않는 테스트를 추가했다.
- **F-1:** `llm_alert_actions`에 실제 조치와 취소를 append-only로 저장한다. 동일 request_id 재전송은 중복 생성하지 않고 다른 내용 재사용은 409다. 실제 조치와 확인을 UI/API에서 구분하며 해결된 알림에도 조치를 남길 수 있다. 검증 결과 정정은 기존 기록 취소 후 새 기록으로 남긴다.
- **E-1:** 최초 발송이 실패한 열린 critical/warning을 다음 평가에서 재시도한다. 횟수·마지막 시각을 DB에 저장하고 기본 최대 3회(최초 포함), 최소 600초 간격을 적용한다. 수동 평가도 간격을 우회하지 못한다. 웹훅 미설정·dry-run은 횟수를 소비하지 않는다.
- 알림 저장 commit 후 발송하며, 평가에 transaction advisory lock, 발송에 행 잠금을 적용한다. 재시도 소진 상태는 화면과 로그에서 확인한다.
- 정본 `standards/ai/LLM_INVENTORY_SCHEMA.md` §9에 계약을 먼저 반영했다. ingest payload와 consumer registry는 변경하지 않았다.

### 파일·API

| 결과물 | 위치 |
|---|---|
| 반복 수집 | [scheduler.py](../backend/app/jobs/scheduler.py) |
| 조치 API | [alert_actions.py](../backend/app/api/alert_actions.py) |
| 확인 audit·재시도 정보 | [monitor.py](../backend/app/api/monitor.py) |
| 재시도 | [alerts.py](../backend/app/monitor/alerts.py) |
| 모델·마이그레이션 | [monitor 모델](../backend/app/models/monitor.py), [e6b8c2d4f013](../backend/app/database/migrations/versions/20260912_e6b8c2d4f013_alert_actions_retry.py) |
| 조치 입력·이력 화면 | [AlertActions.jsx](../frontend/src/components/AlertActions.jsx) |
| 반복 실행 회귀 | [test_scheduler_execution.py](../backend/tests/test_scheduler_execution.py) |
| validation·권한·재시도 정책 | [test_monitor_release1.py](../backend/tests/test_monitor_release1.py) |
| PostgreSQL 통합 | [test_monitor_postgres.py](../backend/tests/test_monitor_postgres.py) |

- `GET/POST /api/monitor/alerts/{id}/actions`: 이력 조회/조치 저장. 조회는 before_id·limit 페이지네이션 지원.
- `POST /api/monitor/alerts/{id}/actions/{action_id}/cancel`: 취소 사유 추가. 원문 보존.
- `GET /api/monitor/actions/summary`: 취소되지 않은 action_count, 개선 확인된 verified_action_count, 그중 알림/관제 화면 최초 발견인 llmops_first_verified_count. 전체 기간 기준이며 이 API를 통한 구조화된 기록만 집계한다.
- 기존 `/ack`는 확인 전용이다. 레거시 action_note 입력을 수용하되 실제 조치로 계산하지 않는다.
- 읽기 member/S2S, 쓰기 admin. 결과 improved/no_change는 result_note 필수. 근거 링크는 HTTP(S)만 허용한다.

### 검증 결과

- 백엔드 **105개 테스트 통과**. 전용 PostgreSQL 15 DB에서 8개 통합 테스트를 포함해 실행했다.
- 비어 있는 임시 DB에 기존 migration부터 새 head `e6b8c2d4f013`까지 적용 성공.
- 동시 조치 저장의 멱등성, 취소 이후 원문 보존, ack의 KPI 제외, S2S 읽기/쓰기 제한, 별도 세션에서의 재시도 지속, dry-run·미설정·상한·간격, 동시 평가, commit 실패 시 발송 차단을 검증했다.
- `npm run build` 통과. 브라우저에서 실제 관리자 조작과 운영 두 수집 주기 검증은 배포 후 항목으로 남아 있다.
- 테스트의 Slack은 모킹했다. 운영 DB 마이그레이션·서비스 재시작·실제 Slack 발송·배포는 수행하지 않았다.

### 실행·배포 유의사항

통합 테스트는 `LLMOPS_TEST_DATABASE_URL`이 설정되어야 실행되며, 없으면 skip한다. URL은 loopback 주소와 `_test`로 끝나는 DB만 허용한다. fixture는 테스트 DB의 알림·조치·audit 테이블을 초기화하므로 별도 DB를 사용한다. 테스트 DB에 먼저 `DATABASE_URL=<테스트 DB URL> .venv/bin/alembic upgrade head`를 적용한다.

```bash
cd backend
# 전용 테스트 DB URL을 환경변수로 설정한 상태에서 실행
.venv/bin/python -m pytest -q
```

1차 스키마는 단일 컬럼보다 커졌다. 취소·정정 원문 보존을 위해 조치 테이블을 추가하고, 재시도 상한의 재시작 내구성을 위해 알림 컬럼 2개를 추가했다. 모두 additive migration 한 건에 포함되며 A의 코드 수정과 분리 가능하다. 기존 ack를 실제 조치로 승격하는 backfill은 없다.

완전한 outbox는 아직 없다. 발송 직후 DB commit 전에 프로세스가 종료되면 성공 기록/시도 횟수가 rollback되어 중복 발송 가능성이 있다. 해결 알림의 재시도, opened/resolved의 완전한 전달 순서는 E-2에 남아 있다. B의 관측 실패 시 잘못된 해결 처리, C의 지표 분모·수신 오류 수정, D/F-2/G도 이번 변경에는 포함하지 않았다.

기본 실패율 임계값과 분모는 권고 4에 따라 그대로 유지했다. 운영 표본 비교와 임계값 확정 전에 알림의 분모만 바꾸지 않는다.

### 재검증 결과 (2026-09-12, 사용자 요청)

- DB 미설정 기본 실행: 97 passed, 8 skipped. 이후 전용 PostgreSQL 15를 연결한 전체 실행: **105 passed, 0 skipped (1.40초)**.
- 새 임시 DB를 이전 head `d5f7a1b3c902`까지 구성하고 레거시 알림·발송 시각·확인자·확인 시각·메모를 입력한 뒤 `e6b8c2d4f013`로 upgrade했다.
- 이전 알림의 모든 필드 값 보존, notification_attempts=0, last_notification_attempt_at=null, 실제 조치 테이블 0건을 확인했다. 과거 확인 기록을 실제 조치로 소급 생성하지 않는다.
- `alembic upgrade head` 재실행도 성공했다.
- 프런트엔드 `npm run build` 및 `git diff --check` 통과.
- 서비스 코드는 수정하지 않았다. 브라우저 수동 검증·운영 배포·운영 DB 변경·실제 Slack 발송은 포함하지 않는다.
