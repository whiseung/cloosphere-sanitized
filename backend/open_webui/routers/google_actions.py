"""Google Workspace HITL confirm endpoints.

Gmail / Calendar 의 tool wrapper 는 외부 호출을 직접 하지 않고 LLM 에게
``confirmation_required`` 응답만 반환한다.  Frontend 가 그것을 사용자에게
보여주고, 사용자가 "Send" / "Create" 를 누르면 이 라우터의 endpoint 로
POST → 게이트 스택 재검증 후 실제 외부 호출.

T-B13 / T-B18 acceptance — Gmail send / Calendar create_event / Drive create_doc confirm:
- (a) owner == user.id  → HMAC sig 검증 (stateless, multi-worker safe)
- (b) features.{gmail,calendar,drive} group permission 재확인
- (c) ENABLE_{GMAIL,CALENDAR,DRIVE}_INTEGRATION admin flag 재확인
- (d) idempotency — audit log dedup on (resource_type, resource_id=message_id)
- (e) atomic state pending→sent — intra-process asyncio.Lock per message_id

세 endpoint 는 패턴이 동일 — 다른 점은 resource_type / 다른 audit action / 다른
external API 호출 함수만.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from typing import Optional

from extension_modules.tools.google.inprocess._common import (
    GoogleApiError,
    GoogleReauthRequired,
    emit_event,
    iana_timezone,
    write_audit_log,
)
from extension_modules.tools.google.inprocess._message_id import verify_message_id
from extension_modules.tools.google.inprocess.send import (
    create_calendar_event_now,
    create_drive_doc_now,
    send_gmail_now,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.audit_log import AuditAction, AuditLogs
from open_webui.utils.access_control import has_permission
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel, Field, field_validator, model_validator

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


# ---------------------------------------------------------------------------
# Gmail confirm
# ---------------------------------------------------------------------------

# Per-message_id in-process lock — 같은 worker 안의 "thundering herd"
# (frontend 더블클릭, race 한 retry) 차단.  Worker 간 race window 는 audit
# log 가 "already_sent" 응답으로 흡수 — 즉 같은 message_id 의 두 confirm 이
# 거의 동시에 두 worker 로 오면 둘 다 실제 발송할 수 있다 (희박).  Frontend
# 는 click 직후 버튼 disable + 응답 대기로 사실상 회피.
_gmail_locks: dict[str, asyncio.Lock] = {}


@contextlib.asynccontextmanager
async def _bounded_lock(locks: dict[str, asyncio.Lock], key: str):
    """``message_id`` 단위 일회성 lock — finally 에서 dict pop 으로 누수 방지.

    message_id 가 일회성 (HMAC 으로 한 번 mint 되고 confirm 한 번이 끝) 이므로
    lock 도 일회성.  pop 시점에 후속 동일 message_id 요청이 새 lock 을 만들어도
    audit replay 분기에서 lock body 진입 전에 return — 안전.
    """
    lock = locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            yield
    finally:
        locks.pop(key, None)


_GMAIL_RESOURCE_TYPE = "gmail_message"


class GmailConfirmBody(BaseModel):
    """``POST /gmail/confirm/{message_id}`` 의 body.

    Frontend confirmation UI 에서 사용자가 (편집 가능한) draft 를 확정하고
    보낸 결과.  ``GmailSendArgs`` 와 의도적으로 별도 schema — tool 인자 vs
    API 계약이 독립적으로 진화하도록.
    """

    to: list[str] = Field(..., min_length=1, description="수신자 목록 (최소 1명)")
    subject: str = Field(..., description="메일 제목")
    body: str = Field(..., description="메일 본문")
    cc: Optional[list[str]] = Field(default=None)
    bcc: Optional[list[str]] = Field(default=None)
    in_reply_to: Optional[str] = Field(default=None)
    conversation_id: Optional[str] = Field(
        default=None, description="audit log 추적용 chat_id (선택)"
    )

    @field_validator("to", mode="after")
    @classmethod
    def _at_least_one_to(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("'to' must contain at least one recipient")
        return v


class GmailConfirmResponse(BaseModel):
    status: str  # "sent" | "already_sent" | "previously_failed"
    message_id: str
    gmail_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    error: Optional[str] = None


def _hash_recipients(addresses: Optional[list[str]]) -> list[str]:
    """Privacy — 평문 이메일 대신 SHA-256 의 앞 32 hex chars 만 audit 에 저장."""
    return [
        hashlib.sha256(a.encode("utf-8")).hexdigest()[:32] for a in (addresses or [])
    ]


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def _prior_attempt(resource_type: str, message_id: str) -> Optional[dict]:
    """이 (resource_type, message_id) 로 이미 시도된 적이 있는지 audit log 에서 조회.

    Returns:
        ``{"action": str, "after_state": dict}`` (가장 최근 1건), 없으면 None.
    """
    rows = AuditLogs.get_audit_logs_by_resource(resource_type, message_id, limit=1)
    if not rows:
        return None
    row = rows[0]
    return {"action": row.action, "after_state": row.after_state or {}}


def _replay_response(message_id: str, prior: dict) -> Optional[GmailConfirmResponse]:
    """prior audit row 가 있으면 그것을 그대로 echo (true idempotency).

    이미 발송 성공 / 발송 실패 둘 다 새로 발송 X — replay 차단.  실패는
    "previously_failed" 로 응답해 frontend 가 새 draft 를 다시 mint 하게 한다.
    """
    action = prior.get("action", "")
    state = prior.get("after_state") or {}
    if action == AuditAction.GMAIL_SEND.value:
        return GmailConfirmResponse(
            status="already_sent",
            message_id=message_id,
            gmail_message_id=state.get("gmail_message_id"),
            thread_id=state.get("thread_id"),
        )
    if action == AuditAction.GMAIL_SEND_FAILED.value:
        return GmailConfirmResponse(
            status="previously_failed",
            message_id=message_id,
            error=state.get("error", "previous attempt failed; start a new draft"),
        )
    return None


@router.post("/gmail/confirm/{message_id}", response_model=GmailConfirmResponse)
async def confirm_gmail_send(
    message_id: str,
    request: Request,
    body: GmailConfirmBody,
    user=Depends(get_verified_user),
):
    """HITL preview 를 사용자가 확정한 뒤 Gmail send API 를 실제로 호출.

    게이트 스택 순서가 중요 — owner → permission → admin flag → idempotency
    → lock → send → audit.  각 게이트는 직전 게이트 통과를 전제로 한다.
    """
    # (a) Owner via HMAC — 404 (not 403) 로 응답해 valid message_id 의 존재
    #     자체를 leak 하지 않는다 (IDOR-safe).
    if not verify_message_id(message_id, user.id):
        log.warning("gmail confirm: invalid message_id signature user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # (b) features.gmail group permission 재확인 — 채팅 turn 시작 후 admin 이
    #     권한 회수했을 수 있음.  admin role 은 우회.
    if user.role != "admin" and not has_permission(
        user.id, "features.gmail", request.app.state.config.USER_PERMISSIONS
    ):
        log.warning("gmail confirm: features.gmail denied user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # (c) Admin instance flag 재확인 — admin 토글 OFF 이면 거부.
    if not request.app.state.config.ENABLE_GMAIL_INTEGRATION:
        log.warning("gmail confirm: ENABLE_GMAIL_INTEGRATION off user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # (d) Idempotency 1차 — lock 잡기 전 빠른 dedup.  이미 처리 끝난 경우는
    #     lock 대기 불필요.
    prior = _prior_attempt(_GMAIL_RESOURCE_TYPE, message_id)
    if prior is not None:
        replay = _replay_response(message_id, prior)
        if replay is not None:
            log.info(
                "gmail confirm: replay status=%s message_id=%s",
                replay.status,
                message_id,
            )
            return replay

    # (e) Atomic pending→sent — 같은 worker 안의 race 방어.  lock 획득 후
    #     audit 재조회로 lock 대기 중 다른 task 가 완료했는지 한 번 더 확인.
    async with _bounded_lock(_gmail_locks, message_id):
        prior = _prior_attempt(_GMAIL_RESOURCE_TYPE, message_id)
        if prior is not None:
            replay = _replay_response(message_id, prior)
            if replay is not None:
                return replay

        try:
            api_response = await send_gmail_now(
                user_id=user.id,
                to=body.to,
                subject=body.subject,
                body=body.body,
                cc=body.cc,
                bcc=body.bcc,
                in_reply_to=body.in_reply_to,
            )
        except GoogleReauthRequired as exc:
            log.warning(
                "gmail confirm: reauth required user=%s reason=%s",
                user.id,
                exc.reason,
            )
            write_audit_log(
                user_id=user.id,
                action=AuditAction.GMAIL_SEND_FAILED,
                resource_type=_GMAIL_RESOURCE_TYPE,
                resource_id=message_id,
                after_state={
                    "error": "google_reauth_required",
                    "reason": exc.reason,
                    "recipients_hash": _hash_recipients(body.to),
                    "subject_hash": _hash_text(body.subject),
                },
                conversation_id=body.conversation_id,
            )
            # 401 — frontend 는 OAuth reconnect 안내 UI 로 분기.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google reauth required",
            )
        except GoogleApiError as exc:
            log.warning(
                "gmail confirm: Google API error user=%s status=%d",
                user.id,
                exc.status_code,
            )
            write_audit_log(
                user_id=user.id,
                action=AuditAction.GMAIL_SEND_FAILED,
                resource_type=_GMAIL_RESOURCE_TYPE,
                resource_id=message_id,
                after_state={
                    "error": f"google_api_error_{exc.status_code}",
                    "message": str(exc.message)[:300],
                    "recipients_hash": _hash_recipients(body.to),
                    "subject_hash": _hash_text(body.subject),
                },
                conversation_id=body.conversation_id,
            )
            # 502 — 업스트림 외부 API 실패.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Gmail send failed ({exc.status_code}): {str(exc.message)[:400]}"
                ),
            )

        gmail_id = api_response.get("id", "")
        thread_id = api_response.get("threadId", "")
        write_audit_log(
            user_id=user.id,
            action=AuditAction.GMAIL_SEND,
            resource_type=_GMAIL_RESOURCE_TYPE,
            resource_id=message_id,
            after_state={
                "gmail_message_id": gmail_id,
                "thread_id": thread_id,
                "recipients_hash": _hash_recipients(body.to),
                "cc_count": len(body.cc or []),
                "bcc_count": len(body.bcc or []),
                "subject_hash": _hash_text(body.subject),
                "body_hash": _hash_text(body.body),
                "in_reply_to": body.in_reply_to,
            },
            conversation_id=body.conversation_id,
        )
        log.info(
            "gmail confirm: sent user=%s gmail_id=%s thread=%s",
            user.id,
            gmail_id,
            thread_id,
        )
        emit_event(
            "google.confirmation.confirmed",
            tool="gmail_send",
            user_id=user.id,
            conversation_id=body.conversation_id,
            recipients=len(body.to),
        )
        return GmailConfirmResponse(
            status="sent",
            message_id=message_id,
            gmail_message_id=gmail_id,
            thread_id=thread_id,
        )


# ---------------------------------------------------------------------------
# Calendar confirm
# ---------------------------------------------------------------------------


_calendar_locks: dict[str, asyncio.Lock] = {}

_CALENDAR_RESOURCE_TYPE = "calendar_event"
_VALID_SEND_UPDATES = ("all", "externalOnly", "none")


class CalendarConfirmBody(BaseModel):
    """``POST /calendar/confirm/{message_id}`` 의 body.

    Frontend confirmation UI 에서 사용자가 (편집 가능한) draft 를 확정한 결과.
    ``CalendarCreateEventArgs`` 와 의도적으로 별도 schema — tool 인자 vs API
    계약이 독립적으로 진화하도록.

    timezone / send_updates / start<end validation 은 confirm 단계에서도 다시
    수행 — 사용자가 frontend 에서 IANA 아닌 값을 강제로 보낸 케이스 방어.
    """

    title: str = Field(..., min_length=1, description="이벤트 제목")
    start: str = Field(..., description="시작 시각 ISO 8601")
    end: str = Field(..., description="종료 시각 ISO 8601")
    timezone: str = Field(..., description="IANA timezone ID (예: Asia/Seoul)")
    description: Optional[str] = Field(default=None, description="이벤트 설명")
    attendees: Optional[list[str]] = Field(
        default=None, description="참석자 이메일 목록"
    )
    send_updates: str = Field(
        default="all",
        description="all / externalOnly / none (F2 — 명시 필수)",
    )
    create_meet: bool = Field(default=False, description="Meet 링크 생성 (default off)")
    conversation_id: Optional[str] = Field(
        default=None, description="audit log 추적용 chat_id (선택)"
    )

    @field_validator("timezone", mode="after")
    @classmethod
    def _iana_only(cls, v: str) -> str:
        return iana_timezone(v)

    @field_validator("send_updates", mode="after")
    @classmethod
    def _send_updates_enum(cls, v: str) -> str:
        if v not in _VALID_SEND_UPDATES:
            raise ValueError(
                f"send_updates must be one of {_VALID_SEND_UPDATES}, got: {v}"
            )
        return v

    @field_validator("start", "end", mode="after")
    @classmethod
    def _iso_datetime(cls, v: str) -> str:
        from datetime import datetime

        try:
            parsed = datetime.fromisoformat(v)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"datetime must be ISO 8601 (e.g. '2026-05-20T14:00:00'), got: {v}"
            ) from exc
        # Normalize to canonical RFC3339 with seconds. The frontend
        # ``<input type="datetime-local">`` emits second-less values
        # ('2026-06-10T14:00') which fromisoformat accepts but Google Calendar's
        # events.insert rejects with 400 Bad Request. isoformat() restores the
        # seconds and preserves any offset; naive + timeZone stays naive.
        return parsed.isoformat()

    @model_validator(mode="after")
    def _start_before_end(self):
        """tool 쪽 ``CalendarCreateEventArgs`` 와 동일 — 프론트 편집 본문 방어."""
        from datetime import datetime

        try:
            s = datetime.fromisoformat(self.start)
            e = datetime.fromisoformat(self.end)
        except ValueError:
            return self
        if (s.tzinfo is None) != (e.tzinfo is None):
            s = s.replace(tzinfo=None)
            e = e.replace(tzinfo=None)
        if not (s < e):
            raise ValueError("'start' must be strictly before 'end'")
        return self


class CalendarConfirmResponse(BaseModel):
    status: str  # "created" | "already_created" | "previously_failed"
    message_id: str
    event_id: Optional[str] = None
    html_link: Optional[str] = None
    hangout_link: Optional[str] = None
    error: Optional[str] = None


def _calendar_replay_response(
    message_id: str, prior: dict
) -> Optional[CalendarConfirmResponse]:
    """prior audit row 가 있으면 그것을 그대로 echo (true idempotency)."""
    action = prior.get("action", "")
    state = prior.get("after_state") or {}
    if action == AuditAction.CALENDAR_CREATE_EVENT.value:
        return CalendarConfirmResponse(
            status="already_created",
            message_id=message_id,
            event_id=state.get("event_id"),
            html_link=state.get("html_link"),
            hangout_link=state.get("hangout_link"),
        )
    if action == AuditAction.CALENDAR_CREATE_EVENT_FAILED.value:
        return CalendarConfirmResponse(
            status="previously_failed",
            message_id=message_id,
            error=state.get("error", "previous attempt failed; start a new draft"),
        )
    return None


@router.post("/calendar/confirm/{message_id}", response_model=CalendarConfirmResponse)
async def confirm_calendar_create_event(
    message_id: str,
    request: Request,
    body: CalendarConfirmBody,
    user=Depends(get_verified_user),
):
    """HITL preview 를 사용자가 확정한 뒤 Calendar event create API 호출.

    Gmail confirm 과 동일한 5축 게이트 (owner / features.calendar / admin /
    idempotency / atomic) — 자세한 설명은 ``confirm_gmail_send`` 참조.
    """
    # (a) Owner via HMAC — 404 IDOR-safe
    if not verify_message_id(message_id, user.id):
        log.warning("calendar confirm: invalid message_id signature user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # (b) features.calendar group permission
    if user.role != "admin" and not has_permission(
        user.id, "features.calendar", request.app.state.config.USER_PERMISSIONS
    ):
        log.warning("calendar confirm: features.calendar denied user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # (c) admin instance flag
    if not request.app.state.config.ENABLE_CALENDAR_INTEGRATION:
        log.warning(
            "calendar confirm: ENABLE_CALENDAR_INTEGRATION off user=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # (d) Idempotency 1차
    prior = _prior_attempt(_CALENDAR_RESOURCE_TYPE, message_id)
    if prior is not None:
        replay = _calendar_replay_response(message_id, prior)
        if replay is not None:
            log.info(
                "calendar confirm: replay status=%s message_id=%s",
                replay.status,
                message_id,
            )
            return replay

    # (e) Atomic + send + audit
    async with _bounded_lock(_calendar_locks, message_id):
        prior = _prior_attempt(_CALENDAR_RESOURCE_TYPE, message_id)
        if prior is not None:
            replay = _calendar_replay_response(message_id, prior)
            if replay is not None:
                return replay

        try:
            api_response = await create_calendar_event_now(
                user_id=user.id,
                title=body.title,
                start=body.start,
                end=body.end,
                timezone=body.timezone,
                description=body.description or "",
                attendees=body.attendees,
                send_updates=body.send_updates,
                create_meet=body.create_meet,
            )
        except GoogleReauthRequired as exc:
            log.warning(
                "calendar confirm: reauth required user=%s reason=%s",
                user.id,
                exc.reason,
            )
            write_audit_log(
                user_id=user.id,
                action=AuditAction.CALENDAR_CREATE_EVENT_FAILED,
                resource_type=_CALENDAR_RESOURCE_TYPE,
                resource_id=message_id,
                after_state={
                    "error": "google_reauth_required",
                    "reason": exc.reason,
                    "title_hash": _hash_text(body.title),
                    "attendees_count": len(body.attendees or []),
                },
                conversation_id=body.conversation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google reauth required",
            )
        except GoogleApiError as exc:
            log.warning(
                "calendar confirm: Google API error user=%s status=%d",
                user.id,
                exc.status_code,
            )
            write_audit_log(
                user_id=user.id,
                action=AuditAction.CALENDAR_CREATE_EVENT_FAILED,
                resource_type=_CALENDAR_RESOURCE_TYPE,
                resource_id=message_id,
                after_state={
                    "error": f"google_api_error_{exc.status_code}",
                    "message": str(exc.message)[:300],
                    "title_hash": _hash_text(body.title),
                    "attendees_count": len(body.attendees or []),
                },
                conversation_id=body.conversation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Calendar event creation failed ({exc.status_code}): "
                    f"{str(exc.message)[:400]}"
                ),
            )

        event_id = api_response.get("id", "")
        html_link = api_response.get("htmlLink")
        hangout_link = api_response.get("hangoutLink")
        write_audit_log(
            user_id=user.id,
            action=AuditAction.CALENDAR_CREATE_EVENT,
            resource_type=_CALENDAR_RESOURCE_TYPE,
            resource_id=message_id,
            after_state={
                "event_id": event_id,
                "html_link": html_link,
                "hangout_link": hangout_link,
                "title_hash": _hash_text(body.title),
                "description_hash": _hash_text(body.description or ""),
                "attendees_count": len(body.attendees or []),
                "attendees_hash": _hash_recipients(body.attendees),
                "send_updates": body.send_updates,
                "create_meet": body.create_meet,
                "timezone": body.timezone,
            },
            conversation_id=body.conversation_id,
        )
        log.info(
            "calendar confirm: created user=%s event_id=%s meet=%s",
            user.id,
            event_id,
            bool(hangout_link),
        )
        emit_event(
            "google.confirmation.confirmed",
            tool="calendar_create_event",
            user_id=user.id,
            conversation_id=body.conversation_id,
            attendees=len(body.attendees or []),
            create_meet=body.create_meet,
        )
        return CalendarConfirmResponse(
            status="created",
            message_id=message_id,
            event_id=event_id,
            html_link=html_link,
            hangout_link=hangout_link,
        )


# ---------------------------------------------------------------------------
# Drive confirm
# ---------------------------------------------------------------------------


_drive_locks: dict[str, asyncio.Lock] = {}

_DRIVE_RESOURCE_TYPE = "drive_document"


class DriveConfirmBody(BaseModel):
    """``POST /drive/confirm/{message_id}`` 의 body.

    Frontend confirmation UI 에서 사용자가 (편집 가능한) draft 를 확정한 결과.
    tool 인자 schema 와 의도적으로 별도 — tool 인자 vs API 계약이 독립적으로
    진화하도록.
    """

    name: str = Field(..., min_length=1, description="생성할 Google Doc 제목")
    content: str = Field(..., description="문서 본문 (마크다운 허용)")
    folder_id: Optional[str] = Field(
        default=None, description="대상 폴더 ID (없으면 내 드라이브 루트)"
    )
    conversation_id: Optional[str] = Field(
        default=None, description="audit log 추적용 chat_id (선택)"
    )


class DriveConfirmResponse(BaseModel):
    status: str  # "created" | "already_created" | "previously_failed"
    message_id: str
    doc_id: Optional[str] = None
    web_link: Optional[str] = None
    error: Optional[str] = None


def _drive_replay_response(
    message_id: str, prior: dict
) -> Optional[DriveConfirmResponse]:
    """prior audit row 가 있으면 그것을 그대로 echo (true idempotency)."""
    action = prior.get("action", "")
    state = prior.get("after_state") or {}
    if action == AuditAction.DRIVE_CREATE_DOC.value:
        return DriveConfirmResponse(
            status="already_created",
            message_id=message_id,
            doc_id=state.get("doc_id"),
            web_link=state.get("web_link"),
        )
    if action == AuditAction.DRIVE_CREATE_DOC_FAILED.value:
        return DriveConfirmResponse(
            status="previously_failed",
            message_id=message_id,
            error=state.get("error", "previous attempt failed; start a new draft"),
        )
    return None


@router.post("/drive/confirm/{message_id}", response_model=DriveConfirmResponse)
async def confirm_drive_create_doc(
    message_id: str,
    request: Request,
    body: DriveConfirmBody,
    user=Depends(get_verified_user),
):
    """HITL preview 를 사용자가 확정한 뒤 Drive 문서 생성 API 호출.

    Gmail / Calendar confirm 과 동일한 5축 게이트 (owner / features.drive /
    admin / idempotency / atomic) — 자세한 설명은 ``confirm_gmail_send`` 참조.
    """
    # (a) Owner via HMAC — 404 IDOR-safe
    if not verify_message_id(message_id, user.id):
        log.warning("drive confirm: invalid message_id signature user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # (b) features.drive group permission
    if user.role != "admin" and not has_permission(
        user.id, "features.drive", request.app.state.config.USER_PERMISSIONS
    ):
        log.warning("drive confirm: features.drive denied user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # (c) admin instance flag
    if not request.app.state.config.ENABLE_DRIVE_INTEGRATION:
        log.warning("drive confirm: ENABLE_DRIVE_INTEGRATION off user=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # (d) Idempotency 1차
    prior = _prior_attempt(_DRIVE_RESOURCE_TYPE, message_id)
    if prior is not None:
        replay = _drive_replay_response(message_id, prior)
        if replay is not None:
            log.info(
                "drive confirm: replay status=%s message_id=%s",
                replay.status,
                message_id,
            )
            return replay

    # (e) Atomic + create + audit
    async with _bounded_lock(_drive_locks, message_id):
        prior = _prior_attempt(_DRIVE_RESOURCE_TYPE, message_id)
        if prior is not None:
            replay = _drive_replay_response(message_id, prior)
            if replay is not None:
                return replay

        try:
            api_response = await create_drive_doc_now(
                user_id=user.id,
                name=body.name,
                content=body.content,
                folder_id=body.folder_id,
            )
        except GoogleReauthRequired as exc:
            log.warning(
                "drive confirm: reauth required user=%s reason=%s",
                user.id,
                exc.reason,
            )
            # orphan 문서 추적 — Step1 성공 후 Step2 실패 시 생성된 doc_id 를
            # after_state 에 기록 (있으면). send.py 가 예외에 실은
            # ``.partial = {"id", "web_view_link", "name"}`` 에서 읽는다.
            # 없으면 None (Step1 자체가 실패한 경우 — orphan 없음).
            orphan = getattr(exc, "partial", None) or {}
            write_audit_log(
                user_id=user.id,
                action=AuditAction.DRIVE_CREATE_DOC_FAILED,
                resource_type=_DRIVE_RESOURCE_TYPE,
                resource_id=message_id,
                after_state={
                    "error": "google_reauth_required",
                    "reason": exc.reason,
                    "name_hash": _hash_text(body.name),
                    "content_hash": _hash_text(body.content),
                    "doc_id": orphan.get("id"),
                    "web_link": orphan.get("web_view_link"),
                },
                conversation_id=body.conversation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google reauth required",
            )
        except GoogleApiError as exc:
            log.warning(
                "drive confirm: Google API error user=%s status=%d",
                user.id,
                exc.status_code,
            )
            # orphan 문서 추적 — Step1 성공 / Step2(batchUpdate) 실패 시 빈
            # 문서가 남으므로 doc_id 를 after_state 에 기록.  send.py 가 예외에
            # 실은 ``.partial = {"id", "web_view_link", "name"}`` 에서 읽는다.
            orphan = getattr(exc, "partial", None) or {}
            write_audit_log(
                user_id=user.id,
                action=AuditAction.DRIVE_CREATE_DOC_FAILED,
                resource_type=_DRIVE_RESOURCE_TYPE,
                resource_id=message_id,
                after_state={
                    "error": f"google_api_error_{exc.status_code}",
                    "message": str(exc.message)[:300],
                    "name_hash": _hash_text(body.name),
                    "content_hash": _hash_text(body.content),
                    "doc_id": orphan.get("id"),
                    "web_link": orphan.get("web_view_link"),
                },
                conversation_id=body.conversation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                # Google 의 실행 가능한 메시지(예: "Docs API 활성화 필요 + 콘솔
                # 링크")를 사용자에게 그대로 노출 — 로그를 뒤지지 않게.
                detail=(
                    f"Drive document creation failed ({exc.status_code}): "
                    f"{str(exc.message)[:400]}"
                ),
            )

        doc_id = api_response.get("id", "")
        web_link = api_response.get("web_view_link")
        write_audit_log(
            user_id=user.id,
            action=AuditAction.DRIVE_CREATE_DOC,
            resource_type=_DRIVE_RESOURCE_TYPE,
            resource_id=message_id,
            after_state={
                "doc_id": doc_id,
                "web_link": web_link,
                "name_hash": _hash_text(body.name),
                "content_hash": _hash_text(body.content),
                "folder_id": body.folder_id,
            },
            conversation_id=body.conversation_id,
        )
        log.info(
            "drive confirm: created user=%s doc_id=%s folder=%s",
            user.id,
            doc_id,
            body.folder_id,
        )
        emit_event(
            "google.confirmation.confirmed",
            tool="drive_create_doc",
            user_id=user.id,
            conversation_id=body.conversation_id,
            folder_id=body.folder_id,
        )
        return DriveConfirmResponse(
            status="created",
            message_id=message_id,
            doc_id=doc_id,
            web_link=web_link,
        )
