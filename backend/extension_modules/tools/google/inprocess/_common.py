"""Google in-process tool 공통 인프라.

설계 의도:
- httpx ``async with httpx.AsyncClient`` 패턴 (코드베이스 미러 ``mcp_client.py``)
- tenacity exponential backoff + jitter (429 / 5xx)
- 401 발생 시 토큰 1회 재발급 후 재시도.  invalid_grant 면 row 삭제 + 사용자
  알림용 ``GoogleReauthRequired`` raise → tool 응답이 LLM 에게 reauth 안내
  메시지 생성을 유도한다.
- IANA timezone 강제 (UTC offset 거부) — F3 회피.
- AuditLogger 패턴 미러 — ``AuditLogCreateForm`` + ``AuditLogs.insert_audit_log``.
- per-turn write quota (T-B21 — in-memory window counter).
- 측정 hook (T-X03) — `emit_event` 가 구조화된 log line 으로 6 events emit.
  Loki/Promtail 등 log aggregator 가 alerting destination 으로 라우트.

이 모듈은 가장자리에 위치해 LLM tool wrapper 가 사용. tool 구현 (gmail.py /
calendar.py) 은 ``call_google_api`` 만 호출하면 인증/재시도/감사가 자동 처리.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from open_webui.models.audit_log import AuditAction, AuditLogCreateForm, AuditLogs
from open_webui.utils.oauth_tokens import get_valid_access_token
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GoogleReauthRequired(Exception):
    """OAuth 토큰이 만료/취소돼 사용자 재인증이 필요한 상태.

    tool wrapper 는 이 예외를 잡아 LLM 에게 reauth 안내 메시지 생성을 유도하는
    JSON 응답으로 변환해야 한다 (HITL 컴포넌트가 disconnect 알림 표시).
    """

    def __init__(self, user_id: str, reason: str = "invalid_grant"):
        self.user_id = user_id
        self.reason = reason
        super().__init__(
            f"Google OAuth reauth required for user={user_id}, reason={reason}"
        )


class GoogleApiError(Exception):
    """4xx / 5xx 응답을 비-인증 사유로 받았을 때 raise.

    401 은 별도 처리 (재발급 시도 후 GoogleReauthRequired).  retry 가능한
    429 / 5xx 는 tenacity 가 자동 재시도하므로 외부로 새지 않음.
    """

    def __init__(self, status_code: int, message: str, payload: Any = None):
        self.status_code = status_code
        self.message = message
        self.payload = payload
        super().__init__(f"Google API error {status_code}: {message}")


class _Retryable(Exception):
    """tenacity 가 backoff 할 수 있는 transient 오류 wrapper (internal)."""


class BatchQuotaExceeded(Exception):
    """1 user turn 안의 write tool call 누적이 한도 초과.

    T-B21 에서 storage 와 함께 raise 위치 구현.  여기는 raise 대상 정의만.
    """

    def __init__(self, user_id: str, tool_name: str, limit: int):
        self.user_id = user_id
        self.tool_name = tool_name
        self.limit = limit
        super().__init__(
            f"Batch write quota exceeded for user={user_id}, "
            f"tool={tool_name}, limit={limit}"
        )


# ---------------------------------------------------------------------------
# OAuth token
# ---------------------------------------------------------------------------


async def get_token(user_id: str) -> str:
    """``get_valid_access_token`` wrapper — None 이면 GoogleReauthRequired."""
    token = await get_valid_access_token(user_id, "google")
    if not token:
        raise GoogleReauthRequired(user_id=user_id, reason="no_token")
    return token


# ---------------------------------------------------------------------------
# Timezone validation (F3 회피)
# ---------------------------------------------------------------------------


def iana_timezone(tz: str) -> str:
    """입력 timezone string 이 IANA ID 인지 검증 후 정규화.

    Google Calendar API 는 IANA ID (예: ``Asia/Seoul``) 만 안정적으로
    처리한다.  UTC offset (``+09:00``) 은 DST 정보가 없어 반복 이벤트에서
    한 시간 어긋나는 사고 (F3) 가 잦다.

    Raises:
        ValueError: IANA ID 가 아니거나 zoneinfo 가 인식 못 하는 값.
    """
    if not isinstance(tz, str) or not tz.strip():
        raise ValueError("timezone must be a non-empty IANA ID string")
    tz_clean = tz.strip()
    # Offset / alias 거부 — '+09:00' / 'GMT+9' / 'Z'.  ``UTC`` 와 ``Etc/UTC`` 는
    # 정식 IANA ID 이고 DST 가 없어 F3 사고 대상이 아니므로 허용.  ``GMT`` 단독은
    # zoneinfo 가 인식하지만 알 수 없는 사용자 의도이므로 명시 거부 유지.
    if tz_clean[0] in "+-" or tz_clean.upper() in {"Z", "GMT"}:
        raise ValueError(
            f"timezone must be an IANA ID (e.g. 'Asia/Seoul', 'UTC'), got: {tz_clean}"
        )
    try:
        ZoneInfo(tz_clean)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"unknown IANA timezone: {tz_clean}. examples: 'Asia/Seoul', 'UTC'"
        ) from exc
    return tz_clean


# ---------------------------------------------------------------------------
# Per-turn write quota (T-B21 — in-memory storage)
# ---------------------------------------------------------------------------

import time
from collections import defaultdict

DEFAULT_WRITE_QUOTA_PER_TURN = 3

# Quota window — 1 LLM turn 이 보통 30-60초 안에 끝난다는 전제.  이 window
# 안에 같은 (user, conversation) 의 write tool call 누적이 ``limit`` 초과면
# BatchQuotaExceeded raise.
#
# Multi-worker 한계: 각 worker process 가 자기 dict 를 가짐.  worker 간
# load-balance 로 호출이 분산되면 합산이 안 된다.  실제로는 한 chat session
# 의 LLM 호출이 같은 worker 로 sticky 되는 경우가 많고, batch send 시도는
# 보통 짧은 시간에 발생하므로 MVP 정확도로 충분.  엄밀한 글로벌 quota 는
# Redis 등으로 미루어 둠.
_WRITE_QUOTA_WINDOW_SECONDS = 60.0

# (user_id, conversation_id) → list of (timestamp, tool_name)
_WRITE_CALLS_LOG: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)


def enforce_write_quota(
    user_id: str,
    conversation_id: Optional[str],
    tool_name: str,
    limit: int = DEFAULT_WRITE_QUOTA_PER_TURN,
) -> None:
    """1 user turn 안의 write tool call 누적을 검사.

    한도 초과 시 ``BatchQuotaExceeded`` raise.  tool wrapper 는 이를 잡아
    LLM 에 ``{"error": "batch_quota_exceeded", ...}`` 응답으로 변환한다.

    저장소: in-memory dict (`_WRITE_CALLS_LOG`).  ``_WRITE_QUOTA_WINDOW_SECONDS``
    (기본 60초) 안의 호출만 카운트.  ``conversation_id`` 가 ``None`` 이면 빈
    string 으로 폴백 — 즉 user 단위 quota 가 된다 (정확도 ↓, 보수성 ↑).
    """
    now = time.monotonic()
    key = (user_id, conversation_id or "")

    # Lazy prune — window 밖 entry 제거.
    log_entries = _WRITE_CALLS_LOG[key]
    cutoff = now - _WRITE_QUOTA_WINDOW_SECONDS
    if log_entries and log_entries[0][0] < cutoff:
        log_entries[:] = [(ts, name) for ts, name in log_entries if ts >= cutoff]

    if len(log_entries) >= limit:
        log.warning(
            "write quota exceeded: user=%s conversation=%s tool=%s count=%d limit=%d",
            user_id,
            conversation_id,
            tool_name,
            len(log_entries),
            limit,
        )
        emit_event(
            "google.batch_quota_hit",
            user_id=user_id,
            conversation_id=conversation_id,
            tool=tool_name,
            limit=limit,
        )
        raise BatchQuotaExceeded(user_id=user_id, tool_name=tool_name, limit=limit)

    log_entries.append((now, tool_name))


def _reset_write_quota_for_test(
    user_id: Optional[str] = None, conversation_id: Optional[str] = None
) -> None:
    """테스트 전용 — 카운터 초기화.  fixture 격리에 사용.

    Args:
        user_id / conversation_id 모두 None → 전체 reset.
        둘 다 지정 → 해당 키만 reset.
    """
    if user_id is None and conversation_id is None:
        _WRITE_CALLS_LOG.clear()
        return
    key = (user_id or "", conversation_id or "")
    _WRITE_CALLS_LOG.pop(key, None)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def write_audit_log(
    user_id: str,
    action: AuditAction,
    resource_type: str,
    after_state: dict,
    resource_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> None:
    """Gmail / Calendar tool 실행 결과를 감사 로그에 기록.

    AuditLogger 의 ``log_create`` 패턴 미러 — ``AuditLogCreateForm`` 빌드
    후 ``AuditLogs.insert_audit_log`` 호출.  본문 hash + 메타 dict 만
    저장 (Privacy — plan §5.4: payload 의 본문은 hash 만).  실패해도
    비즈니스 로직을 막지 않기 위해 try/except.

    Args:
        user_id: 행위 주체 사용자.
        action: ``AuditAction`` enum (GMAIL_SEND / GMAIL_SEND_FAILED /
            CALENDAR_CREATE_EVENT).
        resource_type: 자유 문자열 — Gmail 발송 시 "gmail_message",
            Calendar 생성 시 "calendar_event".
        after_state: hash 처리된 식별자 + 메타 (수신자 hash, subject hash,
            thread_id, event_id 등).  본문 평문은 절대 포함 X.
        resource_id: thread_id / event_id 등 외부 식별자 (optional).
        conversation_id: chat_id (감사 추적용, optional).
    """
    try:
        meta: dict[str, Any] = {"user_id": user_id}
        if conversation_id:
            meta["conversation_id"] = conversation_id

        form = AuditLogCreateForm(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id or "",
            action=action.value,
            after_state=after_state,
            meta=meta,
        )
        AuditLogs.insert_audit_log(form)
        log.debug(
            "Google audit log: action=%s resource=%s/%s user=%s",
            action.value,
            resource_type,
            resource_id,
            user_id,
        )
    except Exception as exc:
        # 감사 실패가 비즈니스 로직을 막지 않도록 swallow + log only.
        log.exception("Failed to write Google audit log: %s", exc)


# ---------------------------------------------------------------------------
# HTTP — Google API 공통 호출
# ---------------------------------------------------------------------------

# 호출당 한 번만 새 client 를 만들고 즉시 닫는 코드베이스 미러 (mcp_client.py).
# Lifespan singleton 은 plan §5.3 가설 → 실제 코드베이스 패턴 우선.

_HTTP_TIMEOUT_DEFAULT = 30.0


@retry(
    retry=retry_if_exception_type(_Retryable),
    stop=stop_after_attempt(4),  # 최초 1 + 재시도 3 = 총 4회
    wait=wait_exponential_jitter(initial=1.0, max=10.0, jitter=2.0),
    reraise=True,
)
async def _call_google_api_with_retry(
    method: str,
    url: str,
    headers: dict[str, str],
    json: Optional[dict],
    params: Optional[dict],
    timeout: float,
    response_mode: str = "json",
) -> dict:
    """tenacity backoff 가 적용된 actual HTTP 호출.

    transient 오류 (429 / 5xx / network) 는 ``_Retryable`` 로 wrap 해 재시도.
    ``response_mode`` 는 ``_parse_response`` 로 그대로 관통 (json|text).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method, url, headers=headers, json=json, params=params
            )
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
        raise _Retryable(f"transient network error: {exc}") from exc

    if response.status_code == 429 or response.status_code >= 500:
        raise _Retryable(
            f"transient API error: {response.status_code} {response.text[:200]}"
        )
    return _parse_response(response, response_mode)


def _parse_response(response: httpx.Response, response_mode: str = "json") -> dict:
    """Google API 응답 파싱 + 4xx 처리.

    401 은 caller (call_google_api) 가 토큰 재발급 + retry 로 처리하므로
    별도 sentinel exception (``_AuthRetry``) 로 외부로 띄움.

    ``response_mode``:
        - ``"json"`` (기본): ``response.json()`` 파싱.
        - ``"text"``: ``{"text": response.text}`` 반환 (Drive export / alt=media
          가 CSV/plain 원문을 줄 때).  401 / >=400 / 빈 본문 가드는 mode 와
          무관하게 동일 순서 — 빈 본문은 text 모드에서도 ``{}`` (drive.py 는
          ``resp.get("text", "")`` 로 KeyError 회피).
    """
    if response.status_code == 401:
        raise _AuthRetry(response.text[:200])
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = response.text
        raise GoogleApiError(
            status_code=response.status_code,
            message=str(payload)[:300],
            payload=payload,
        )
    if not response.content:
        return {}
    if response_mode == "text":
        return {"text": response.text}
    if response_mode == "bytes":
        # 바이너리 다운로드 (Drive alt=media PDF/Office, Gmail 첨부) — 원문 bytes.
        # 빈 본문은 위 가드에서 {} 로 빠지므로 caller 는 .get("content_bytes", b"").
        return {"content_bytes": response.content}
    return response.json()


class _AuthRetry(Exception):
    """401 응답 — caller 가 토큰 재발급 후 한 번만 재시도."""


async def call_google_api(
    method: str,
    path: str,
    *,
    user_id: str,
    host: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: float = _HTTP_TIMEOUT_DEFAULT,
    response_mode: str = "json",
) -> dict:
    """Bearer + tenacity + 401 재발급 한 번 + invalid_grant 처리 통합 호출.

    Args:
        method: HTTP method (GET / POST / PATCH / DELETE).
        path: ``/gmail/v1/users/me/messages/send`` 같은 path (선행 슬래시).
        user_id: 호출 주체.  토큰 lookup 에 사용.
        host: ``gmail.googleapis.com`` / ``calendar.googleapis.com``.
        json: request body (선택).
        params: query string (선택).
        timeout: httpx 타임아웃 (초).

    Raises:
        GoogleReauthRequired: 토큰이 없거나 invalid_grant 일 때.  tool wrapper
            는 이를 잡아 사용자 재인증 안내 JSON 으로 변환.
        GoogleApiError: 다른 4xx 응답.
    """
    token = await get_token(user_id)
    url = f"https://{host}{path}"
    started = time.monotonic()

    async def _do_call(bearer: str) -> dict:
        return await _call_google_api_with_retry(
            method=method,
            url=url,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Accept": "application/json",
            },
            json=json,
            params=params,
            timeout=timeout,
            response_mode=response_mode,
        )

    try:
        result = await _do_call(token)
        emit_event(
            "google.tool.call",
            host=host,
            path=path,
            method=method,
            success=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return result
    except _AuthRetry:
        # 401 — 한 번만 토큰 재발급 후 재시도.  refresh 가 가능하면 새 토큰,
        # 안 되면 get_token() 자체가 GoogleReauthRequired 를 raise (token=None).
        log.warning("Google API 401 for user=%s — refreshing token once", user_id)
        try:
            fresh_token = await get_token(user_id)
        except GoogleReauthRequired:
            # 토큰 row 가 이미 삭제됐거나 refresh 실패 → 사용자 재인증 안내로 흐름.
            raise

        try:
            result = await _do_call(fresh_token)
            emit_event(
                "google.tool.call",
                host=host,
                path=path,
                method=method,
                success=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                reauth_retried=True,
            )
            return result
        except _AuthRetry:
            # 재발급 후에도 401 — invalid_grant 류 영구 실패 (F7).
            # T-B20: stale token row 를 명시적으로 삭제해 다음 호출이 곧바로
            # ``no_token`` 경로로 빠지게 한다 (silent failure 회피).
            log.warning(
                "Google API still 401 after refresh for user=%s — purging token row + reauth required",
                user_id,
            )
            _purge_invalid_google_token(user_id)
            emit_event(
                "google.tool.call",
                host=host,
                path=path,
                method=method,
                success=False,
                error_type="reauth_required",
            )
            raise GoogleReauthRequired(
                user_id=user_id, reason="auth_failed_after_refresh"
            )


def _purge_invalid_google_token(user_id: str) -> None:
    """invalid_grant 가 확정되면 ``UserOAuthTokens(provider='google')`` row 삭제.

    실패해도 비즈니스 흐름 막지 않음 (audit 와 동일 swallow 정책).  다음 호출
    에서 ``get_valid_access_token`` 이 None → ``GoogleReauthRequired(reason='no_token')``
    이 되어 사용자는 동일한 reauth 메시지를 본다.
    """
    try:
        from open_webui.models.user_oauth_tokens import UserOAuthTokens

        ok = UserOAuthTokens.delete(user_id, "google")
        if ok:
            log.info("Purged stale google OAuth token for user=%s", user_id)
        else:
            log.warning(
                "Google OAuth token purge returned False for user=%s "
                "(row may already be missing)",
                user_id,
            )
    except Exception as exc:
        log.exception("Failed to purge google OAuth token: %s", exc)


# ---------------------------------------------------------------------------
# 측정 hook (T-X03) — 구조화된 event log
# ---------------------------------------------------------------------------

# Plan §5.6 의 6 events:
# - google.toggle.toggle             (frontend emit — InputMenu change)
# - google.tool.call                 (success/failure/latency)
# - google.confirmation.shown        (HITL preview returned to frontend)
# - google.confirmation.confirmed    (user clicked Send/Create)
# - google.confirmation.canceled     (user clicked Cancel)
# - google.send_with_regret          (post-hoc, monitoring 외부 처리)
# - google.batch_quota_hit           (per-turn write quota raised)
#
# Frontend toggle event 은 별도 client-side observability 가 필요해 backend
# 에서는 emit 안 함.  toggle 의 효과는 결국 tool.call 로 측정 가능.


def emit_event(event: str, **fields: Any) -> None:
    """구조화된 한 줄 로그로 측정 event emit.

    각 event 는 ``[google.event] event=<name> key=value ...`` 형식.  log
    aggregator (Loki + Promtail) 가 라벨로 파싱해 Slack/PagerDuty 라우팅.

    실패는 swallow (audit / quota 와 동일 정책).  관측 손실이 비즈니스
    로직 막지 않게.
    """
    try:
        # str / int / bool / None / float 만 안전하게 직렬화.  복합 타입은 str() 으로.
        parts = []
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                parts.append(f"{k}={v}")
            else:
                parts.append(f"{k}={str(v)[:200]}")
        log.info("[google.event] event=%s %s", event, " ".join(parts))
    except Exception:
        # observability 손실은 swallow.
        pass


__all__ = [
    "GoogleReauthRequired",
    "GoogleApiError",
    "BatchQuotaExceeded",
    "DEFAULT_WRITE_QUOTA_PER_TURN",
    "get_token",
    "iana_timezone",
    "enforce_write_quota",
    "write_audit_log",
    "call_google_api",
    "emit_event",
]
