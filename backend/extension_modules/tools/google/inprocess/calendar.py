"""Google Calendar in-process tools — LangChain StructuredTool builders.

설계:
- ``make_calendar_create_event`` (restricted scope ``calendar.events``):
  tool 자체는 외부 호출을 하지 않고 HITL preview 만 반환.  실제 생성은
  frontend 가 확인 후 호출하는 ``POST /api/v1/google/calendar/confirm/
  {message_id}`` (T-B18) 가 처리.
- ``make_calendar_list_events`` (restricted scope ``calendar.events``):
  read-only, HITL 없음.  Calendar API events.list 호출.
- ``make_calendar_find_free_slots`` (sensitive scope ``calendar.events.freebusy``):
  read-only, HITL 없음.  freeBusy 응답에서 모든 attendee 의 busy 합집합 을 빼서
  ``[timeMin, timeMax]`` 안의 공통 free slot 산출.

함정 회피:
- F2 (``sendUpdates`` 기본 ``"none"``): create_event tool 인자의 default 를 ``"all"`` 로 강제.
- F3 (UTC offset DST 사고): timezone 인자는 ``_common.iana_timezone`` 으로 IANA
  ID 만 통과.  ``+09:00`` / ``UTC`` / ``Z`` 거부.
- F4 (``singleEvents=false`` 반복 이벤트 펼침 안 됨): list_events 가 항상
  ``singleEvents=true`` 강제 + ``orderBy=startTime``.
- create_meet 기본 ``False`` (Meet defer — plan §11 / OQ#11).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from extension_modules.tools.google.inprocess._common import (
    BatchQuotaExceeded,
    GoogleApiError,
    GoogleReauthRequired,
    call_google_api,
    emit_event,
    enforce_write_quota,
    iana_timezone,
)
from extension_modules.tools.google.inprocess._hitl import make_calendar_confirmation
from extension_modules.tools.google.inprocess._message_id import mint_message_id
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, field_validator, model_validator

log = logging.getLogger(__name__)

# Frontend 가 ToolMessage 안에서 marker 를 보면 CalendarConfirmation.svelte 를
# 렌더한다 (gmail.py 의 GMAIL_CONFIRM_MARKER 패턴 미러).
CALENDAR_CONFIRM_MARKER = "[calendar_confirmation_required]"
CALENDAR_QUOTA_MARKER = "[calendar_batch_quota_exceeded]"

_VALID_SEND_UPDATES = ("all", "externalOnly", "none")


# ---------------------------------------------------------------------------
# Pydantic args schema
# ---------------------------------------------------------------------------


class CalendarCreateEventArgs(BaseModel):
    """``calendar_create_event`` 의 인자.

    HITL 응답 단계에서는 validate 만 수행 — 실제 생성은 confirm endpoint 가 받은
    수정본으로 진행.  caller (LLM) 는 ISO 8601 datetime 과 IANA timezone 을
    분리해서 전달해야 함 (datetime 안에 ``+09:00`` 같은 offset 포함 X — F3).
    """

    title: str = Field(..., min_length=1, description="이벤트 제목.")
    start: str = Field(
        ...,
        description=(
            "시작 시각 — ISO 8601 datetime, timezone offset 없음.  예: "
            "``2026-05-20T14:00:00``.  timezone 은 별도 인자."
        ),
    )
    end: str = Field(
        ...,
        description=(
            "종료 시각 — ISO 8601 datetime, timezone offset 없음.  ``start`` 보다 뒤."
        ),
    )
    timezone: str = Field(
        ...,
        description=(
            "IANA timezone ID.  예: ``Asia/Seoul``, ``America/New_York``.  "
            "UTC offset (``+09:00``) / ``UTC`` / ``Z`` 거부됨 — DST 사고 회피."
        ),
    )
    description: Optional[str] = Field(default=None, description="이벤트 설명 (선택).")
    attendees: Optional[list[str]] = Field(
        default=None,
        description=(
            "참석자 이메일 목록 (선택).  주최자(=사용자)는 자동 포함되니 명시 X."
        ),
    )
    send_updates: str = Field(
        default="all",
        description=(
            "참석자에게 초대 메일 발송 정책: ``all`` (전체) / ``externalOnly`` "
            "(외부만) / ``none`` (안 보냄).  attendees 없으면 무의미."
        ),
    )
    create_meet: bool = Field(
        default=False,
        description=(
            "Google Meet 링크 자동 생성 여부.  기본 False (MVP).  True 면 "
            "conferenceData 가 추가되지만 hangoutLink 는 비동기 pending 일 수 있음."
        ),
    )

    @field_validator("timezone", mode="after")
    @classmethod
    def _iana_only(cls, v: str) -> str:
        # iana_timezone() 는 IANA ID 가 아니거나 zoneinfo 가 모르는 값에서 ValueError.
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
        # 시각이 ISO 8601 로 파싱되는지만 확인 (timezone offset 포함은 _no_tz_offset 에서).
        from datetime import datetime

        try:
            datetime.fromisoformat(v)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"datetime must be ISO 8601 (e.g. '2026-05-20T14:00:00'), got: {v}"
            ) from exc
        return v

    @model_validator(mode="after")
    def _start_before_end(self):
        try:
            s = datetime.fromisoformat(self.start)
            e = datetime.fromisoformat(self.end)
        except ValueError:
            # 개별 필드 validator 에서 이미 에러 raise 됐어야 함 — 방어용 noop.
            return self
        # LLM 이 한쪽만 ``Z``/offset 을 붙여 와도 비교 가능하도록 tzinfo 통일.
        if (s.tzinfo is None) != (e.tzinfo is None):
            s = s.replace(tzinfo=None)
            e = e.replace(tzinfo=None)
        if not (s < e):
            raise ValueError("'start' must be strictly before 'end'")
        return self


class _TimeRangeArgs(BaseModel):
    """``time_min``/``time_max``/``timezone`` 공통 검증 (list_events / find_free_slots)."""

    time_min: str = Field(
        ...,
        description=(
            "조회 시작 (ISO 8601 datetime).  ``2026-05-20T00:00:00`` 같은 naive 면 "
            "``timezone`` 으로 해석.  ``...+09:00`` / ``Z`` offset 도 허용."
        ),
    )
    time_max: str = Field(
        ...,
        description="조회 종료 (ISO 8601 datetime).  time_min 보다 뒤.",
    )
    timezone: str = Field(
        ...,
        description=(
            "IANA timezone ID (예: ``Asia/Seoul``).  naive datetime 을 RFC 3339 "
            "로 변환할 때 사용 + Calendar API 에 ``timeZone`` 으로 전달."
        ),
    )

    @field_validator("timezone", mode="after")
    @classmethod
    def _iana_only(cls, v: str) -> str:
        return iana_timezone(v)

    @field_validator("time_min", "time_max", mode="after")
    @classmethod
    def _iso_datetime(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"datetime must be ISO 8601 (e.g. '2026-05-20T10:00:00'), got: {v}"
            ) from exc
        return v

    @model_validator(mode="after")
    def _time_min_before_max(self):
        try:
            s = datetime.fromisoformat(self.time_min)
            e = datetime.fromisoformat(self.time_max)
        except ValueError:
            return self
        if (s.tzinfo is None) != (e.tzinfo is None):
            s = s.replace(tzinfo=None)
            e = e.replace(tzinfo=None)
        if not (s < e):
            raise ValueError("'time_min' must be strictly before 'time_max'")
        return self


class CalendarListEventsArgs(_TimeRangeArgs):
    """``calendar_list_events`` 의 인자."""

    q: Optional[str] = Field(
        default=None,
        description="이벤트 free-text 검색 (제목/설명/위치/참석자).  선택.",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description="반환할 최대 이벤트 수 (1-25, 기본 10).",
    )
    page_token: Optional[str] = Field(
        default=None,
        description="이전 응답의 ``next_page_token`` — 다음 페이지 fetch 시 사용.",
    )


class CalendarFindFreeSlotsArgs(_TimeRangeArgs):
    """``calendar_find_free_slots`` 의 인자."""

    attendees: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "freebusy 조회할 참석자 email 목록.  본인 캘린더는 ``primary`` 또는 "
            "본인 이메일 명시.  최소 1명."
        ),
    )
    min_duration_minutes: int = Field(
        default=30,
        ge=5,
        le=480,
        description=(
            "공통 free slot 으로 인정할 최소 길이 (분).  5-480 분, 기본 30 분."
        ),
    )


# ---------------------------------------------------------------------------
# Constants — Calendar API endpoints
# ---------------------------------------------------------------------------


_CAL_HOST = "www.googleapis.com"
_CAL_EVENTS_PATH = "/calendar/v3/calendars/primary/events"
_CAL_FREEBUSY_PATH = "/calendar/v3/freeBusy"

# Event 응답에서 LLM 에 노출할 필드 화이트리스트.  나머지 (creator/updated/iCalUID
# 등) 는 노이즈.
_EVENT_LLM_FIELDS = (
    "id",
    "summary",
    "description",
    "location",
    "status",
    "htmlLink",
    "hangoutLink",
)


# ---------------------------------------------------------------------------
# Tool builders
# ---------------------------------------------------------------------------


_CALENDAR_CREATE_DESCRIPTION = (
    "Compose a calendar event and request user confirmation before creating it. "
    "Use this when the user asks you to schedule / book / create / set up "
    "an event or meeting. The tool returns a confirmation_required preview — "
    "the actual event creation happens only after the user explicitly confirms "
    "in the UI. Always pass an IANA timezone ('Asia/Seoul', 'America/New_York'), "
    "NOT a UTC offset. Datetimes are without timezone (e.g. '2026-05-20T14:00:00'). "
    "send_updates defaults to 'all' (attendees get invite mail) — change only "
    "if user explicitly says not to notify."
)


def make_calendar_create_event(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """user_id + conversation_id 바인딩 + HITL confirm 응답을 만드는 ``calendar_create_event`` tool.

    Tool 자체는 외부 API 를 호출하지 않는다.  per-turn write quota 통과 시
    HITL preview 를 반환하고, frontend 가 사용자에게 보여준 뒤 confirm
    endpoint 로 실제 생성을 보낸다.
    """

    def _calendar_create_event(**kwargs) -> str:
        args = CalendarCreateEventArgs(**kwargs)
        log.info(
            "calendar_create_event draft requested: user_id=%s title_len=%d attendees=%d send_updates=%s create_meet=%s",
            user_id,
            len(args.title or ""),
            len(args.attendees or []),
            args.send_updates,
            args.create_meet,
        )

        try:
            enforce_write_quota(
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="calendar_create_event",
            )
        except BatchQuotaExceeded as exc:
            log.warning(
                "calendar_create_event quota exceeded: user=%s tool=%s limit=%d",
                exc.user_id,
                exc.tool_name,
                exc.limit,
            )
            return _format_quota_error(tool_name=exc.tool_name, limit=exc.limit)

        message_id = mint_message_id(user_id)
        # attendees: tool args 의 list[str] 을 HITL helper 의 list[{email}] 로 변환.
        attendees_dicts = [{"email": e} for e in (args.attendees or [])]
        payload = make_calendar_confirmation(
            message_id=message_id,
            title=args.title,
            start=args.start,
            end=args.end,
            timezone=args.timezone,
            description=args.description or "",
            attendees=attendees_dicts,
            send_updates=args.send_updates,
            create_meet=args.create_meet,
        )
        emit_event(
            "google.confirmation.shown",
            tool="calendar_create_event",
            user_id=user_id,
            conversation_id=conversation_id,
            risk_level=payload.get("risk_level"),
            attendees=len(args.attendees or []),
            create_meet=args.create_meet,
        )
        return _format_confirmation(payload)

    return StructuredTool.from_function(
        func=_calendar_create_event,
        name="calendar_create_event",
        description=_CALENDAR_CREATE_DESCRIPTION,
        args_schema=CalendarCreateEventArgs,
    )


_CALENDAR_LIST_DESCRIPTION = (
    "List the user's calendar events within a time range. "
    "Use this when the user asks 'what's on my calendar', 'my schedule for X', "
    "'do I have meetings on Y'. Pass an IANA timezone ('Asia/Seoul') — datetimes "
    "without offset are interpreted in that tz. Returns a list of events with "
    "summary, start/end, attendees, location, and Google Calendar links. "
    "Recurring events are automatically expanded as individual instances."
)


def make_calendar_list_events(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """``calendar_list_events`` — Calendar events.list 조회 (read-only).

    F4 회피: ``singleEvents=true`` + ``orderBy=startTime`` 항상 강제.
    naive ISO 8601 입력은 IANA tz 로 보정해 RFC 3339 로 변환.
    """

    async def _calendar_list_events(**kwargs) -> str:
        args = CalendarListEventsArgs(**kwargs)
        log.info(
            "calendar_list_events: user_id=%s tz=%s max=%d q=%s",
            user_id,
            args.timezone,
            args.max_results,
            "yes" if args.q else "no",
        )

        params: dict[str, Any] = {
            "timeMin": _to_rfc3339(args.time_min, args.timezone),
            "timeMax": _to_rfc3339(args.time_max, args.timezone),
            "timeZone": args.timezone,
            "singleEvents": "true",  # F4 — 반복 이벤트 펼침
            "orderBy": "startTime",  # singleEvents=true 일 때만 동작
            "maxResults": args.max_results,
            "showDeleted": "false",
        }
        if args.q:
            params["q"] = args.q
        if args.page_token:
            params["pageToken"] = args.page_token

        try:
            resp = await call_google_api(
                method="GET",
                path=_CAL_EVENTS_PATH,
                user_id=user_id,
                host=_CAL_HOST,
                params=params,
            )
        except GoogleReauthRequired as exc:
            return _format_error("google_reauth_required", reason=exc.reason)
        except GoogleApiError as exc:
            return _format_error(
                f"calendar_api_error_{exc.status_code}",
                message=str(exc.message)[:300],
            )

        events = [_pick_event_fields(e) for e in resp.get("items") or []]
        return json.dumps(
            {
                "events": events,
                "next_page_token": resp.get("nextPageToken"),
                "default_timezone": resp.get("timeZone"),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_calendar_list_events,
        name="calendar_list_events",
        description=_CALENDAR_LIST_DESCRIPTION,
        args_schema=CalendarListEventsArgs,
    )


_CALENDAR_FREEBUSY_DESCRIPTION = (
    "Find common free time slots across multiple attendees within a time range. "
    "Use this when the user asks 'when are we all free', 'find a meeting time', "
    "or 'check if [people] are available'. Pass attendee emails (use 'primary' "
    "for the current user). Returns the common free slots (intersection of "
    "everyone's availability) plus each attendee's busy intervals. "
    "Default minimum slot duration is 30 minutes — adjust via min_duration_minutes."
)


def make_calendar_find_free_slots(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """``calendar_find_free_slots`` — freeBusy API + 공통 free slot 산출."""

    async def _calendar_find_free_slots(**kwargs) -> str:
        args = CalendarFindFreeSlotsArgs(**kwargs)
        log.info(
            "calendar_find_free_slots: user_id=%s attendees=%d tz=%s min_dur=%dmin",
            user_id,
            len(args.attendees),
            args.timezone,
            args.min_duration_minutes,
        )

        body = {
            "timeMin": _to_rfc3339(args.time_min, args.timezone),
            "timeMax": _to_rfc3339(args.time_max, args.timezone),
            "timeZone": args.timezone,
            "items": [{"id": e} for e in args.attendees],
        }

        try:
            resp = await call_google_api(
                method="POST",
                path=_CAL_FREEBUSY_PATH,
                user_id=user_id,
                host=_CAL_HOST,
                json=body,
            )
        except GoogleReauthRequired as exc:
            return _format_error("google_reauth_required", reason=exc.reason)
        except GoogleApiError as exc:
            return _format_error(
                f"calendar_api_error_{exc.status_code}",
                message=str(exc.message)[:300],
            )

        calendars = resp.get("calendars") or {}
        busy_by_attendee: dict[str, list[dict]] = {}
        errors_by_attendee: dict[str, list[dict]] = {}
        all_busy: list[tuple[datetime, datetime]] = []
        for email, info in calendars.items():
            busy = info.get("busy") or []
            busy_by_attendee[email] = busy
            errs = info.get("errors") or []
            if errs:
                errors_by_attendee[email] = errs
            for interval in busy:
                try:
                    s = datetime.fromisoformat(interval["start"])
                    e = datetime.fromisoformat(interval["end"])
                    all_busy.append((s, e))
                except (KeyError, ValueError, TypeError):
                    continue

        range_start = datetime.fromisoformat(body["timeMin"])
        range_end = datetime.fromisoformat(body["timeMax"])
        common_free_slots = _compute_free_slots(
            range_start=range_start,
            range_end=range_end,
            busy_intervals=all_busy,
            min_duration_minutes=args.min_duration_minutes,
        )

        return json.dumps(
            {
                "common_free_slots": common_free_slots,
                "busy_by_attendee": busy_by_attendee,
                "errors_by_attendee": errors_by_attendee,
                "timezone": args.timezone,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_calendar_find_free_slots,
        name="calendar_find_free_slots",
        description=_CALENDAR_FREEBUSY_DESCRIPTION,
        args_schema=CalendarFindFreeSlotsArgs,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_rfc3339(naive_or_offset: str, tz: str) -> str:
    """Naive ISO 8601 + IANA tz → RFC 3339 with offset.

    이미 offset 이 있으면 (``+09:00`` / ``Z``) 그대로 반환.  naive 면 IANA
    timezone 으로 localize 해서 offset 부여.
    """
    from zoneinfo import ZoneInfo

    try:
        dt = datetime.fromisoformat(naive_or_offset)
    except ValueError:
        return naive_or_offset  # 검증은 caller 가 이미 — 만약 통과했다면 그대로 전달
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.isoformat()


def _pick_event_fields(event: dict) -> dict:
    """events.list 응답의 한 항목을 LLM-친화 형식으로 정제.

    ``_EVENT_LLM_FIELDS`` 화이트리스트 + start/end + attendees 만 노출.
    """
    out: dict[str, Any] = {}
    for k in _EVENT_LLM_FIELDS:
        if event.get(k):
            out[k] = event[k]
    # start/end 는 ``{date, dateTime, timeZone}`` 등 dict — flatten 해서
    # ``dateTime`` 또는 ``date`` (종일) 만 노출.
    for boundary in ("start", "end"):
        block = event.get(boundary) or {}
        if "dateTime" in block:
            out[boundary] = {
                "dateTime": block["dateTime"],
                "timeZone": block.get("timeZone"),
            }
        elif "date" in block:
            out[boundary] = {"date": block["date"]}  # all-day
    attendees = event.get("attendees") or []
    if attendees:
        out["attendees"] = [
            {
                "email": a.get("email"),
                "response_status": a.get("responseStatus"),
                "organizer": bool(a.get("organizer")),
                "self": bool(a.get("self")),
            }
            for a in attendees
        ]
    organizer = event.get("organizer") or {}
    if organizer.get("email"):
        out["organizer"] = organizer["email"]
    return out


def _compute_free_slots(
    *,
    range_start: datetime,
    range_end: datetime,
    busy_intervals: list[tuple[datetime, datetime]],
    min_duration_minutes: int,
) -> list[dict]:
    """``[range_start, range_end]`` 에서 모든 ``busy_intervals`` 합집합 을 뺀
    공통 free slot 목록.

    겹치는 busy 들은 merge.  ``min_duration_minutes`` 보다 짧은 slot 은 제외.
    각 slot 은 ``{"start": ISO, "end": ISO, "duration_minutes": int}``.
    """
    if range_start >= range_end:
        return []
    # tz-aware vs naive 통일 — range 가 aware 면 busy 도 aware 강제.
    range_is_aware = range_start.tzinfo is not None
    normalized: list[tuple[datetime, datetime]] = []
    for s, e in busy_intervals:
        if (s.tzinfo is not None) != range_is_aware:
            # tzinfo 불일치는 비교 불가 — skip (안전 default).
            continue
        # 범위 밖 잘라내기
        s = max(s, range_start)
        e = min(e, range_end)
        if s < e:
            normalized.append((s, e))
    normalized.sort(key=lambda x: x[0])

    # Merge overlapping
    merged: list[tuple[datetime, datetime]] = []
    for s, e in normalized:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Compute gaps
    slots: list[dict] = []
    cursor = range_start
    for s, e in merged:
        if cursor < s:
            _emit_slot(slots, cursor, s, min_duration_minutes)
        cursor = max(cursor, e)
    if cursor < range_end:
        _emit_slot(slots, cursor, range_end, min_duration_minutes)
    return slots


def _emit_slot(
    slots: list[dict], start: datetime, end: datetime, min_minutes: int
) -> None:
    duration = int((end - start).total_seconds() // 60)
    if duration >= min_minutes:
        slots.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_minutes": duration,
            }
        )


def _format_error(error_code: str, **fields: Any) -> str:
    """list/find_free_slots 의 외부 호출 실패를 LLM-친화 JSON 으로."""
    payload: dict[str, Any] = {"error": error_code, **fields}
    if error_code == "google_reauth_required":
        payload.setdefault(
            "hint",
            "Google 계정 재인증이 필요합니다.  사용자에게 설정 > 연결에서 "
            "Google 다시 연결을 안내해 주세요.",
        )
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Response formatters — marker + JSON payload
# ---------------------------------------------------------------------------


def _format_confirmation(payload: dict) -> str:
    """Frontend 가 CalendarConfirmation.svelte 를 렌더할 수 있는 직렬화 응답."""
    return (
        f"{CALENDAR_CONFIRM_MARKER}\n```json\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n```"
    )


def _format_quota_error(tool_name: str, limit: int) -> str:
    """per-turn write quota 초과 — LLM 에 사용자 확인 안내 유도용 응답."""
    payload = {
        "error": "batch_quota_exceeded",
        "tool": tool_name,
        "limit": limit,
        "hint": (
            "이번 메시지에서 가능한 일정 생성 횟수를 초과했습니다.  사용자에게 "
            "한 번에 진행할지 확인해 주세요."
        ),
    }
    return (
        f"{CALENDAR_QUOTA_MARKER}\n```json\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n```"
    )


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


__all__ = [
    "CALENDAR_CONFIRM_MARKER",
    "CALENDAR_QUOTA_MARKER",
    "CalendarCreateEventArgs",
    "CalendarFindFreeSlotsArgs",
    "CalendarListEventsArgs",
    "make_calendar_create_event",
    "make_calendar_find_free_slots",
    "make_calendar_list_events",
    "make_calendar_tools",
]


def make_calendar_tools(
    user_id: str, conversation_id: Optional[str] = None
) -> list[StructuredTool]:
    """user_id + conversation_id 바인딩 Calendar 툴 모음.

    구성:
    - ``calendar_create_event``    (restricted ``calendar.events``) — HITL preview
    - ``calendar_list_events``     (restricted ``calendar.events``) — read-only
    - ``calendar_find_free_slots`` (sensitive ``calendar.events.freebusy``) — read-only

    ``conversation_id`` 는 ``calendar_create_event`` 의 per-turn write quota scope.
    read-only 툴은 사용 안 함.
    """
    return [
        make_calendar_create_event(user_id, conversation_id=conversation_id),
        make_calendar_list_events(user_id, conversation_id=conversation_id),
        make_calendar_find_free_slots(user_id, conversation_id=conversation_id),
    ]
