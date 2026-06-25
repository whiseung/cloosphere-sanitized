# Gmail / Google Calendar 통합 사용 가이드

> 채팅 중 자연어로 Gmail 메일을 작성·검색하거나 Google 캘린더 일정을 만들고 조회할 수 있는 기능입니다.

---

## 개요

| 기능 | 도구 | Scope (Google) |
|---|---|---|
| **메일 작성/발송** | `gmail_send` | `gmail.send` (sensitive) — HITL 미리보기 필수 |
| **메일 검색** | `gmail_search` | `gmail.readonly` (restricted) |
| **메일 본문 조회** | `gmail_get` | `gmail.readonly` (restricted) |
| **일정 등록** | `calendar_create_event` | `calendar.events` (restricted) — HITL 미리보기 필수 |
| **일정 조회** | `calendar_list_events` | `calendar.events` (restricted) |
| **참석자 가능 시간 찾기** | `calendar_find_free_slots` | `calendar.events.freebusy` (sensitive) |

발송/등록은 **모두 사용자가 직접 확인한 뒤에만 실행**됩니다 (HITL — Human In The Loop).

---

## 사용 전 조건

다음 5가지가 모두 충족돼야 채팅 입력창 "+" 메뉴에 Gmail/Calendar 토글이 보입니다:

1. **관리자가 통합 기능을 활성화** — `Admin Settings > Connections > Google Workspace Integration`
2. **사용자 그룹에 권한 부여** — `Admin Settings > Users > Groups` 의 `features.gmail` / `features.calendar`
3. **에이전트 capability 가 `off` 가 아님** — 에이전트 사용 시 `Workspace > Agents > [에이전트] > Capabilities` 에서 설정
4. **Google 계정 연결** — `Settings > Connections > Google` (개인 설정)
5. **(채팅 시점) 채팅 입력창 "+" 메뉴에서 토글 ON**

토글이 보이지 않거나 회색으로 비활성이면 hover 시 어느 조건이 빠졌는지 안내됩니다.

---

## 사용 흐름

### 메일 발송 예

1. 채팅 입력창 "+" 클릭 → Gmail 토글 ON
2. "alice@example.com 에게 다음 주 미팅 시간 조율하는 메일 보내줘" 같은 자연어 입력
3. AI 가 초안을 만들어 **풍부한 미리보기**로 반환:
   - 수신자 / 참조 / 숨은 참조 chip (외부 도메인은 황색 강조)
   - 제목 / 본문 (편집 가능)
4. 검토 후:
   - 외부 도메인 또는 3명 이상 수신자 → "Review required" 표시되며 **확인 체크박스** 켜야 발송 활성화
   - 그 외 → 한 번에 "Send" 버튼 클릭
5. 발송 후 5초 동안 버튼 비활성 (rapid retry 차단)
6. 결과 알림 — 성공 / 이미 발송됨 / 실패

### 일정 등록 예

1. 입력창 "+" → Calendar 토글 ON
2. "내일 오후 2시 30분 동안 alice@cloocus.com 과 회의 잡아줘. Meet 링크 포함" 같은 자연어
3. AI 가 일정 초안을 미리보기로 반환:
   - 제목 / 시작·종료 시각 / 시간대 (편집 가능)
   - 참석자 chip / send_updates 옵션 / Meet 링크 토글
4. 검토 → Create Event 클릭
5. 성공 시 "Open in Google Calendar" 링크가 나타남

### 메일 검색 예

> "지난 7일 동안 invoice 가 들어 있는 메일 5건만 보여줘"

AI 가 Gmail 검색 문법 (`subject:invoice newer_than:7d`) 을 자동 구성해 호출 → 결과 목록 제목/발신자/스니펫 반환.

특정 메일 본문이 필요하면 AI 가 자동으로 `gmail_get` 으로 이어 조회합니다.

### 공통 빈 시간 찾기 예

> "다음 주 화요일 9-18시 사이에 alice, bob, carol 셋이 30분 이상 비는 시간 찾아줘"

`freeBusy` API → 셋의 busy 시간 합집합을 뺀 공통 free slot 목록을 반환합니다.

---

## HITL 미리보기 동작 설명

### 위험도 분류 (`risk_level`)

| 조건 | 표시 | UI 동작 |
|---|---|---|
| 내부 단일 수신자 + 짧은 본문 | `low` | 1-click "Send" |
| 외부 도메인 / 3명 이상 / cc·bcc 사용 / 스레드 회신 / 본문 1000자 이상 | `high` | "Review required" 배지 + 확인 체크박스 켜야 발송 가능 |

"내부 도메인" 은 관리자가 `INTERNAL_EMAIL_DOMAINS` 환경변수로 설정합니다 (예: `cloocus.com,acme.com`).  설정 없으면 모든 도메인을 외부로 표시 (안전 default).

### Anti-spoof 도메인 표시

각 수신자 chip 옆에 `@<domain> (외부/내부)` 라벨이 붙습니다.  AI 가 생성한 raw 문자열을 그대로 보여주지 않고, 도메인 별로 별도 표시해 spoofing 메일 방지.

### Idempotency

같은 미리보기에서 "Send" 를 여러 번 눌러도 **한 번만** 발송됩니다.  발송 후 다시 클릭하면 "Email already sent earlier" 안내가 나오고 다시 보내지지 않습니다.

### Cooldown

"Send" / "Create Event" 클릭 후 5초 동안 버튼 비활성.  실패해도 적용 (의도하지 않은 rapid retry 차단).

---

## 자주 묻는 질문

### Q. 토글이 안 보여요

채팅 입력창 "+" 메뉴에서 hover 하면 어느 조건이 안 됐는지 tooltip 으로 안내됩니다:

- *"Connect your Google account in Settings → Connections to use this"* → 4번 (OAuth 연결) 안 됨
- *"Your group does not have permission for this feature. Ask your admin."* → 2번 (그룹 권한) 없음
- 메뉴 자체에 안 나타남 → 1번 (관리자 기능 비활성) 또는 3번 (에이전트 capability='off')

### Q. 메일 본문에 **마크다운** 형식이 보존되나요?

MVP 는 text/plain 으로만 발송됩니다.  실제 메일에서는 마크다운 기호가 그대로 보입니다 (예: `**bold**`).  v1.1 에서 HTML 변환 예정.

### Q. 첨부파일도 보낼 수 있나요?

MVP 미지원.  v1.1 에서 추가 예정.

### Q. 정기 일정 (반복 이벤트) 등록은?

MVP 미지원.  현재는 단일 인스턴스 일정만.

### Q. 회의 시간 추천 받기

`calendar_find_free_slots` 가 참석자들의 빈 시간 교집합을 계산합니다.  `min_duration_minutes` 로 최소 길이 조정 가능 (기본 30 분).

### Q. 발송 실패 후 같은 미리보기에서 재시도

같은 미리보기 (`message_id`) 는 재시도 불가합니다.  AI 에게 다시 요청 → 새 미리보기 생성 후 발송하세요.

### Q. 발송 후 취소 가능한가요?

**불가능합니다.**  실제 Google API 로 발송되면 Gmail/Calendar 의 표준 흐름을 따릅니다 (Gmail 의 "Undo send" 는 Gmail 클라이언트 기능이지 API 가 아닙니다).  발송 전에 신중히 검토하세요.

### Q. 어떻게 발송 이력을 확인하나요?

`Admin > Monitoring > Audit Logs` 에서 `GMAIL_SEND` / `CALENDAR_CREATE_EVENT` 액션을 필터로 조회 가능.

---

## 개인정보 / 보안 안내

- 발송된 메일 / 등록된 일정의 **원문은 audit log 에 저장되지 않습니다** (SHA-256 hash 와 메타데이터만).
- HITL 미리보기 단계에서는 본문이 LLM 으로 전송됩니다.  민감한 내용을 입력할 때는 회사 데이터 사용 정책을 확인하세요.
- OAuth 토큰은 **Fernet 으로 암호화**되어 DB 에 저장됩니다.  KEK 없이는 복호화 불가.
- 발송이 영구 실패 (`invalid_grant`) 하면 자동으로 OAuth 토큰이 무효화되며 다음 사용 시 재인증을 요청합니다.

---

## 운영자 문의

문제가 지속되면 관리자에게:
- `Admin > Monitoring > Audit Logs` 의 `GMAIL_SEND_FAILED` / `CALENDAR_CREATE_EVENT_FAILED` 항목 확인
- Backend 로그의 `[google.event]` 라인 (구조화 측정 hook)
- runbook: `dev/runbooks/google-integration-rollback.md`
