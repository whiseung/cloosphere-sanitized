# Gmail / Calendar 통합 Rollback Runbook

> 사고 발생 시 on-call 이 **5분 안에 실행** 가능한 4단계 시나리오.

| 사고 유형 | 1순위 대응 | 소요 | 영향 |
|---|---|---|---|
| 1. 신규 tool call 즉시 차단 (최소 영향) | Admin flag OFF | < 1분 | 모든 in-flight HITL confirm 까지 막힘 |
| 2. 특정 사용자만 차단 | OAuth row 삭제 | < 5분 | 해당 사용자만 |
| 3. 전체 token 회수 (긴급) | DB DELETE | < 5분 | 모든 사용자 재인증 필요 |
| 4. Scope 회수 (최후) | Google Cloud Console 변경 | < 30분 | SSO 흐름 자체 영향 |

`feat/google-workspace-integration` 브랜치의 5축 게이트로 인해 **각 단계는 독립적으로 동작** — admin flag 만 끄면 시스템은 그대로 두고 빠르게 차단할 수 있습니다.

---

## 1. 신규 tool call 즉시 차단

가장 가벼운 차단.  사용자 OAuth 연결은 그대로, admin 토글만 OFF.

### Curl 실행

```bash
# Gmail 만 OFF
curl -X POST https://<host>/api/v1/configs/google_integration \
  -H 'Authorization: Bearer <admin-token>' \
  -H 'Content-Type: application/json' \
  -d '{"ENABLE_GMAIL_INTEGRATION": false}'

# Calendar 만 OFF
curl -X POST https://<host>/api/v1/configs/google_integration \
  -H 'Authorization: Bearer <admin-token>' \
  -H 'Content-Type: application/json' \
  -d '{"ENABLE_CALENDAR_INTEGRATION": false}'

# 둘 다 OFF
curl -X POST https://<host>/api/v1/configs/google_integration \
  -H 'Authorization: Bearer <admin-token>' \
  -H 'Content-Type: application/json' \
  -d '{"ENABLE_GMAIL_INTEGRATION": false, "ENABLE_CALENDAR_INTEGRATION": false}'
```

또는 UI 로: `Admin Settings > Connections > Google Workspace Integration > 토글 OFF`.

### 동작 확인

```bash
# 응답에 false 로 반영됐는지
curl https://<host>/api/v1/configs/google_integration \
  -H 'Authorization: Bearer <admin-token>'
# {"ENABLE_GMAIL_INTEGRATION":false,"ENABLE_CALENDAR_INTEGRATION":false}

# 새 채팅 turn 에서 tool 비노출 + 기존 HITL confirm endpoint 가 403 반환
curl -X POST https://<host>/api/v1/google/gmail/confirm/<message_id> \
  -H 'Authorization: Bearer <user-token>' \
  -d '...'
# 403 Forbidden — ENABLE_GMAIL_INTEGRATION off
```

**효과 범위**: 즉시 — `request.app.state.config.ENABLE_*` 가 모든 worker 에 반영됨 (PersistentConfig).

**복귀**: 같은 endpoint 에 `true` POST 만 하면 됨.

---

## 2. 특정 사용자만 차단

해당 사용자의 OAuth 연결 해제 — 토큰 row 삭제.

### Curl 실행 (사용자 자가 disconnect)

```bash
# 본인 토큰 (어느 user 든)
curl -X DELETE https://<host>/api/v1/email/connections/google \
  -H 'Authorization: Bearer <user-token>'
```

### 운영자 명의로 강제 disconnect

```python
# Backend container 안에서 (또는 Python shell)
from open_webui.models.user_oauth_tokens import UserOAuthTokens
UserOAuthTokens.delete(user_id="<USER_ID>", provider="google")
# True / False (이미 없으면 False)
```

또는 DB 직접:
```sql
DELETE FROM user_oauth_tokens
WHERE user_id = '<USER_ID>' AND provider = 'google';
```

### 동작 확인

```bash
# 해당 사용자가 다시 tool call 시도하면 GoogleReauthRequired (no_token) →
# audit log 에 GMAIL_SEND_FAILED 기록되고 frontend 에 reauth 안내 표시
curl https://<host>/api/v1/email/connections -H 'Authorization: Bearer <user-token>'
# google.connected: false
```

**복귀**: 사용자가 Settings > Connections 에서 Google 재연결.

---

## 3. 전체 token 회수 (긴급)

대규모 사고 (예: scope 오남용, 데이터 유출 가능성) 시 **모든 사용자의 Google 토큰을 일괄 무효화**.

### DB 실행

```sql
-- 변경 전 백업 (안전)
CREATE TABLE user_oauth_tokens_backup_$(date +%Y%m%d) AS
  SELECT * FROM user_oauth_tokens WHERE provider = 'google';

-- 일괄 삭제
DELETE FROM user_oauth_tokens WHERE provider = 'google';
```

또는 Python:
```python
from open_webui.internal.db import get_db
from open_webui.models.user_oauth_tokens import UserOAuthToken

with get_db() as db:
    count = (
        db.query(UserOAuthToken)
        .filter(UserOAuthToken.provider == "google")
        .delete()
    )
    db.commit()
    print(f"Deleted {count} rows")
```

### 동작 확인

```sql
SELECT COUNT(*) FROM user_oauth_tokens WHERE provider = 'google';
-- 0
```

모든 사용자가 다음 채팅 turn 에서 `GoogleReauthRequired` 응답을 받음 → frontend 가 "Connect your Google account" 안내.

**복귀**: 각 사용자가 SSO 다시 진행 (관리자 대량 복귀 불가).

---

## 4. Scope 회수 (최후)

Google Cloud Console 에서 OAuth client 의 scope 자체 제거.  **모든 사용자가 동의 화면을 다시 통과해야 함**.

### Google Cloud Console 단계

1. https://console.cloud.google.com/apis/credentials/consent 접속
2. 사고 발생 OAuth Client 선택 → "EDIT APP"
3. **Scopes** 페이지에서 회수할 scope 체크 해제:
   - `gmail.readonly`
   - `gmail.send`
   - `calendar.events`
   - `calendar.events.freebusy`
4. "SAVE AND CONTINUE" 클릭

### Token 일괄 revoke (선택)

```bash
# 모든 user 의 refresh token 을 Google 측에서 무효화
# (각 사용자가 직접 https://myaccount.google.com/permissions 에서 제거 가능)
```

또는 **3 번 (DB DELETE) 과 함께** 진행해 양쪽 완전 정리.

### 영향

- 즉시: 새 SSO 시 동의 화면이 다시 표시됨 (scope 회수된 상태)
- 기존 token: Google 측에서 다음 refresh 시 거부 → `invalid_grant` → `_purge_invalid_google_token` 호출됨

**복귀**: Google Cloud Console 에서 scope 다시 추가 후 사용자 재동의.

---

## 검증 (모든 시나리오 공통)

각 단계 실행 후:

1. **audit log 확인**:
```bash
curl https://<host>/api/v1/audit-logs?action=GMAIL_SEND_FAILED \
  -H 'Authorization: Bearer <admin-token>' | jq '.[0:5]'
```

2. **구조화 event log** (Loki/Promtail 등):
```
[google.event] event=google.tool.call success=false error_type=reauth_required
```

3. **사용자 영향**:
- 1번 시나리오: 채팅 toggle 비활성 (5축 admin off)
- 2번: 해당 user 의 토글에 "Connect your Google account" tooltip
- 3-4번: 모든 user 동일

---

## On-call 통보 (사고 인지)

다음 metric 이 임계값 초과 시 자동 알림 (T-X07 alerting 설정):

| Metric | Threshold | 액션 |
|---|---|---|
| `send_with_regret` rolling 1h | > 2% | 1번 (admin flag OFF) 검토 |
| `gmail_send_failed (401/invalid_grant)` | > 5/min | 3번 (전체 token 회수) 후보 |
| `429 rate` | > 1% sustained 10min | Google quota 증대 신청 후 admin flag OFF |
| `invalid_grant` daily | > 5% (vs ~1%/월 baseline) | 3번 검토 |
| `batch_quota_hit` | > 10/min per user | 해당 user 만 2번 차단 |

---

## 참조

- 5축 게이트 구조: `dev/00_dev_docs/active/gmail-calendar-integration/plan.md` §5.2
- audit action enum: `backend/open_webui/models/audit_log.py:65-72`
- token row schema: `backend/open_webui/models/user_oauth_tokens.py`
- admin endpoint: `backend/open_webui/routers/configs.py:144-178`
- HITL confirm endpoint: `backend/open_webui/routers/google_actions.py`
