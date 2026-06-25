---
paths:
  - "backend/open_webui/routers/schedules.py"
  - "backend/open_webui/models/schedules.py"
  - "backend/open_webui/services/scheduler.py"
  - "backend/open_webui/services/schedule_worker.py"
  - "src/lib/components/schedules/**/*.svelte"
  - "src/lib/apis/schedules/**/*.ts"
  - "src/routes/(app)/workspace/schedules/**/*"
---

# 예약 작업(Schedules) 규칙

## 권한 모델 (2026-04-23 갱신)

권한 체크는 **두 축 AND 평가**. 자세한 원칙은 `backend-permission.md` 참조.

- **Feature Permission** (그룹별): `features.scheduled_tasks` (boolean) + `workspace.schedules` (none/access/read/write) 두 개를 `_check_feature_permission()`이 함께 검증.
- **Resource Permission** (리소스별): `access_control` JSON 필드 — `read` / `write` 2단계. 소유자 + admin은 항상 통과.

### 백엔드 라우터 (`/api/v1/schedules`)

| 메서드 | 경로 | Feature Perm | Resource Perm | 설명 |
|--------|------|-------------|---------------|------|
| GET | `/` | read | get_schedules_by_user_id("read") | 사용자 스케줄 목록 (소유 + access_control.read 공유받은 것) |
| POST | `/create` | read | — | 생성 (croniter 검증) |
| GET | `/{id}` | read | `has_access(user, "read", ac)` | 단일 조회 |
| POST | `/{id}/update` | read | `has_access(user, "write", ac)` | 수정 (소유자/admin/write 공유자) |
| DELETE | `/{id}/delete` | read | `has_access(user, "write", ac)` | 삭제 (소유자/admin/write 공유자) |
| POST | `/{id}/toggle` | read | `has_access(user, "write", ac)` | 활성/비활성 전환 |
| POST | `/{id}/run` | read | `has_access(user, "write", ac)` | 즉시 실행 — ScheduleTask.triggered_by_user_id 기록 |
| GET | `/{id}/tasks` | read | `has_access(user, "read", ac)` | 실행 이력 |
| POST | `/{id}/share` | read | **소유자/admin 전용** | 다른 사용자에게 복사 (write 공유자도 차단 — 권한 확산 방지) |
| GET | `/tasks/recent` | read | — | 최근 작업 |

### 실행 권한 전파 정책 (중요)

- `POST /{id}/run`에서 write 권한 공유자가 수동 트리거해도 **실제 실행 컨텍스트는 `schedule.user_id` (원 소유자)로 유지**.
- 실행되는 에이전트 / Dashboard / tool 권한은 원 소유자 기준. 트리거만 공유, 권한 상승 없음.
- 감사를 위해 `ScheduleTask.triggered_by_user_id`에 트리거 사용자 id 기록 (소유자 본인 트리거는 NULL, 스케줄러 정기 실행도 NULL).

### 결과 chat 이어쓰기 정책

- schedule 결과 chat (`chat.meta.schedule_id` 존재)은 **소유자만 후속 메시지 입력 가능**.
- read/write 공유자, admin(비소유자)은 **read-only** — `Chat.svelte` `isScheduleReadOnly` (소유자 외 전부 true)에서 MessageInput 숨기고 안내 배너 노출.
- 이유: worker가 `schedule.user_id` 컨텍스트로 chat history를 누적하므로, 비소유자가 끼어들면 owner 데이터/이력 오염.
- 백엔드 `GET /chats/{id}` 폴백은 read 공유자에게 조회만 허용. mutating 엔드포인트(`POST /{id}`, completion)는 기존 owner 체크가 막음.

## DB 모델

### Schedule
- `id`, `user_id`, `name`, `description`
- `target_type`: "agent" | "flow" | "model" | "dashboard"
- `target_model_id`: models.id 참조
- `prompt`: 실행할 프롬프트
- `cron_expression`: croniter 형식 ("0 9 * * *")
- `timezone`: pytz 지원 ("Asia/Seoul")
- `delivery`: JSON — 알림 채널/템플릿 설정
- `is_active`, `next_run_at` (사전 계산, Unix)
- `start_at`, `end_at`: nullable 기간 제한
- `chat_id`: 결과 기록 채팅 (재사용)
- `meta`: JSON — copied_from 등
- `access_control`: JSON — `read`/`write` 2단계 그룹/조직/사용자 권한
- 인덱스: `(is_active, next_run_at)` — 스케줄러 쿼리 최적화

### ScheduleTask
- `id`, `schedule_id`, `user_id`
- `status`: "pending" | "running" | "completed" | "failed"
- `worker_id`, `prompt`, `result` (JSON), `error_message`
- `chat_id`, `scheduled_at`, `started_at`, `completed_at`
- `retry_count`, `max_retries` (기본 2)
- `triggered_by_user_id`: **nullable**. NULL = 정기 실행, 값 있음 = 수동 트리거 사용자 (audit trail, migration `c1d2e3f4a5b6`에서 추가)
- UNIQUE (`schedule_id`, `scheduled_at`) — 중복 작업 방지

## 스케줄러 엔진 (scheduler.py)
- 매 60초 루프, PostgreSQL Advisory Lock (20260226)으로 리더 선택
- `get_due_schedules(now)` → `enqueue_task(schedule, now, triggered_by_user_id=None)` → `_update_next_run()`
- croniter + pytz로 다음 실행 시각 계산, Unix timestamp 저장
- `reset_stale_tasks(600s)`, `cleanup_old_tasks(30일)`

## 작업 워커 (schedule_worker.py)
- 매 5초 루프, `SELECT ... FOR UPDATE SKIP LOCKED`로 작업 분배
- 에이전트(`base_model_id` 있음) → UnifiedAgent, 그 외 → generate_chat_completion
- **실행 user 컨텍스트는 `schedule.user_id`** (원 소유자) — `Users.get_user_by_id(schedule.user_id)`
- 채팅 기록: 기존 `chat_id` 있으면 append, 없으면 새로 생성
- 알림: trigger 조건(always/on_success/on_failure), 템플릿 변수({{schedule_name}} 등)
- 차트: `[[dbsphere:chart]]` 블록 추출 → 서버 사이드 렌더링 → 이미지 첨부
- 재시도: retriable 에러만, max_retries 초과 시 failed

## 프론트엔드 컴포넌트
- `ScheduleList.svelte`: 목록 + Fuse.js 검색
- `ScheduleForm.svelte`: 생성/편집 폼 + **AccessControlModal** (공유 설정)
- `ScheduleInput.svelte`: Cron UI (interval/hourly/daily/weekly/monthly/custom)
- `ScheduleDelivery.svelte`: 알림 설정
- `ScheduleTaskHistory.svelte`: 실행 이력

## 공유 정책

- **access_control 기반 공유** (이번 구현): read 권한자는 조회/복사, write 권한자는 수정/삭제/toggle/run까지. 실행 컨텍스트는 소유자 유지.
- **share 엔드포인트 (기존)**: 독립 복사 — `meta.copied_from`에 출처 기록. 소유자/admin 전용.
- 두 경로는 공존.

## Group Permissions UI (admin)

`src/lib/components/admin/Users/Groups/Permissions.svelte` — workspace 섹션에 "Schedules Access" 드롭다운 (none/access/read/write). 기본값 `read`.

## 주의사항
- `_check_feature_permission()`은 boolean `features.scheduled_tasks` + 4단계 `workspace.schedules` 두 개 모두 검증
- `target_model_id`의 read 권한도 별도 체크 (`_check_model_access`)
- SQLite: 분산 락 없음 (단일 인스턴스 가정)
- Cron 표현식: croniter 표준만 지원
