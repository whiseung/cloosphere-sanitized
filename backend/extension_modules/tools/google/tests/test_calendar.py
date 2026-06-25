"""Calendar tool 단위 테스트 — F2/F3/F4 회귀, send_updates 강제 default, IANA tz,
list_events singleEvents/orderBy 강제, freebusy 공통 free slot 산출.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from extension_modules.tools.google.inprocess._common import (
    BatchQuotaExceeded,
    GoogleApiError,
    GoogleReauthRequired,
)
from extension_modules.tools.google.inprocess._message_id import verify_message_id
from extension_modules.tools.google.inprocess.calendar import (
    CALENDAR_CONFIRM_MARKER,
    CALENDAR_QUOTA_MARKER,
    CalendarCreateEventArgs,
    CalendarFindFreeSlotsArgs,
    CalendarListEventsArgs,
    _compute_free_slots,
    _pick_event_fields,
    _to_rfc3339,
    make_calendar_tools,
)

# ---------------------------------------------------------------------------
# CalendarCreateEventArgs validators
# ---------------------------------------------------------------------------


class TestCalendarCreateEventArgs:
    def test_minimum_valid(self):
        args = CalendarCreateEventArgs(
            title="Sync",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
        )
        # F2 — default 가 "all" (아니라면 attendees 추가 시 invite 안 감)
        assert args.send_updates == "all"
        # MVP — Meet defer
        assert args.create_meet is False

    @pytest.mark.parametrize(
        "tz", ["Asia/Seoul", "America/New_York", "Europe/London", "UTC/+09"]
    )
    def test_iana_passes(self, tz):
        if tz == "UTC/+09":
            with pytest.raises(Exception):
                CalendarCreateEventArgs(
                    title="t",
                    start="2026-05-20T10:00:00",
                    end="2026-05-20T11:00:00",
                    timezone=tz,
                )
            return
        args = CalendarCreateEventArgs(
            title="t",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone=tz,
        )
        assert args.timezone == tz

    @pytest.mark.parametrize(
        "bad_tz",
        ["+09:00", "-05:00", "+0900", "GMT+9", "Z", "GMT"],
    )
    def test_offset_and_alias_tz_rejected(self, bad_tz):
        # F3 — DST 사고 회피.  UTC 는 DST 가 없어 허용 (별도 test_utc_allowed).
        with pytest.raises(Exception):
            CalendarCreateEventArgs(
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone=bad_tz,
            )

    def test_utc_allowed(self):
        # F3 — UTC 는 DST 없으므로 IANA 화이트리스트 통과.
        args = CalendarCreateEventArgs(
            title="t",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="UTC",
        )
        assert args.timezone == "UTC"

    @pytest.mark.parametrize("send", ["all", "externalOnly", "none"])
    def test_send_updates_valid(self, send):
        args = CalendarCreateEventArgs(
            title="t",
            start="2026-05-20T10:00:00",
            end="2026-05-20T11:00:00",
            timezone="Asia/Seoul",
            send_updates=send,
        )
        assert args.send_updates == send

    @pytest.mark.parametrize("bad", ["everyone", "yes", "All", ""])
    def test_send_updates_invalid(self, bad):
        with pytest.raises(Exception):
            CalendarCreateEventArgs(
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
                send_updates=bad,
            )

    def test_start_after_end_rejects(self):
        with pytest.raises(Exception):
            CalendarCreateEventArgs(
                title="t",
                start="2026-05-20T11:00:00",
                end="2026-05-20T10:00:00",
                timezone="Asia/Seoul",
            )

    def test_start_equal_end_rejects(self):
        with pytest.raises(Exception):
            CalendarCreateEventArgs(
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T10:00:00",
                timezone="Asia/Seoul",
            )

    def test_empty_title_rejects(self):
        with pytest.raises(Exception):
            CalendarCreateEventArgs(
                title="",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
            )

    @pytest.mark.parametrize("bad_dt", ["not-a-date", "2026-13-40T99:99:99"])
    def test_invalid_iso_datetime_rejects(self, bad_dt):
        with pytest.raises(Exception):
            CalendarCreateEventArgs(
                title="t",
                start=bad_dt,
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
            )


# ---------------------------------------------------------------------------
# make_calendar_tools factory
# ---------------------------------------------------------------------------


class TestMakeCalendarTools:
    def test_returns_three_tools(self):
        tools = make_calendar_tools("u")
        assert [t.name for t in tools] == [
            "calendar_create_event",
            "calendar_list_events",
            "calendar_find_free_slots",
        ]

    def test_create_sync_list_freebusy_async(self):
        tools = {t.name: t for t in make_calendar_tools("u")}
        # create_event: HITL preview only — sync
        assert tools["calendar_create_event"].coroutine is None
        # list / find_free_slots: external API — async
        assert tools["calendar_list_events"].coroutine is not None
        assert tools["calendar_find_free_slots"].coroutine is not None


# ---------------------------------------------------------------------------
# calendar_create_event tool HITL output
# ---------------------------------------------------------------------------


class TestCalendarCreateEventTool:
    @pytest.fixture(autouse=True)
    def _reset_quota(self):
        from extension_modules.tools.google.inprocess._common import (
            _reset_write_quota_for_test,
        )

        _reset_write_quota_for_test()
        yield
        _reset_write_quota_for_test()

    def _invoke(self, user_id="u", **overrides):
        tool = make_calendar_tools(user_id)[0]
        kwargs = {
            "title": "Sync",
            "start": "2026-05-20T14:00:00",
            "end": "2026-05-20T15:00:00",
            "timezone": "Asia/Seoul",
        }
        kwargs.update(overrides)
        return tool.func(**kwargs)

    def test_returns_marker_plus_json(self, with_internal_domain):
        result = self._invoke()
        assert result.startswith(CALENDAR_CONFIRM_MARKER)
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["confirmation_required"] is True
        assert payload["tool"] == "calendar_create_event"

    def test_message_id_hmac_bound(self, with_internal_domain):
        result = self._invoke(user_id="user-x")
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert verify_message_id(payload["message_id"], "user-x") is True
        assert verify_message_id(payload["message_id"], "user-y") is False

    def test_attendees_list_str_converts_to_dict(self, with_internal_domain):
        result = self._invoke(attendees=["a@cloocus.com", "b@external.com"])
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["draft"]["attendees"] == [
            {"email": "a@cloocus.com"},
            {"email": "b@external.com"},
        ]
        # external 한 명이라도 있으면 high (with_internal_domain — cloocus.com 만 내부)
        assert payload["risk_level"] == "high"

    def test_default_send_updates_all(self, with_internal_domain):
        result = self._invoke()
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["draft"]["send_updates"] == "all"

    def test_default_create_meet_false(self, with_internal_domain):
        result = self._invoke()
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["draft"]["create_meet"] is False

    def test_tool_does_not_call_external_api(self, with_internal_domain):
        """HITL preview 만 — 외부 호출 절대 안 함."""
        with patch(
            "extension_modules.tools.google.inprocess._common.call_google_api"
        ) as mock_api:
            self._invoke()
            mock_api.assert_not_called()

    def test_quota_exceeded_returns_quota_marker(self, with_internal_domain):
        with patch(
            "extension_modules.tools.google.inprocess.calendar.enforce_write_quota",
            side_effect=BatchQuotaExceeded(
                user_id="u", tool_name="calendar_create_event", limit=3
            ),
        ):
            result = self._invoke()
        assert result.startswith(CALENDAR_QUOTA_MARKER)
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["error"] == "batch_quota_exceeded"
        assert payload["tool"] == "calendar_create_event"

    def test_solo_event_low_risk(self, with_internal_domain):
        # attendees 없음, description 짧음, send_updates default=all → 알림 없음 (attendees=0)
        # → risk: send_updates="all" + attendees 0 → classify 가 "all" 보고 high
        # 의도: send_updates="none" 으로 명시하면 low
        result = self._invoke(send_updates="none")
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["risk_level"] == "low"

    def test_conversation_id_threaded_to_quota(self, with_internal_domain):
        """T-B21 quota scope — make_calendar_create_event 가 conversation_id 를
        enforce_write_quota 로 전달."""
        from extension_modules.tools.google.inprocess.calendar import (
            make_calendar_create_event,
        )

        tool = make_calendar_create_event("user-x", conversation_id="conv-xyz")
        with patch(
            "extension_modules.tools.google.inprocess.calendar.enforce_write_quota"
        ) as quota_mock:
            tool.func(
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
            )
        quota_mock.assert_called_once()
        kwargs = quota_mock.call_args.kwargs
        assert kwargs["user_id"] == "user-x"
        assert kwargs["conversation_id"] == "conv-xyz"
        assert kwargs["tool_name"] == "calendar_create_event"


# ---------------------------------------------------------------------------
# _to_rfc3339 helper
# ---------------------------------------------------------------------------


class TestToRfc3339:
    def test_naive_gets_iana_offset(self):
        # Asia/Seoul = UTC+09:00 (no DST)
        result = _to_rfc3339("2026-05-20T10:00:00", "Asia/Seoul")
        assert result == "2026-05-20T10:00:00+09:00"

    def test_offset_passthrough(self):
        # 이미 offset 이 있으면 그대로 (재해석 X)
        result = _to_rfc3339("2026-05-20T10:00:00+09:00", "Asia/Seoul")
        # parse + reisoformat — 동일 의미여야 함
        assert "2026-05-20T10:00:00" in result
        assert "+09:00" in result

    def test_utc_passthrough(self):
        result = _to_rfc3339("2026-05-20T10:00:00+00:00", "Asia/Seoul")
        # UTC offset 유지 (Seoul 로 재해석 X)
        assert "+00:00" in result


# ---------------------------------------------------------------------------
# _pick_event_fields helper
# ---------------------------------------------------------------------------


class TestPickEventFields:
    def test_whitelist_basic_fields(self):
        event = {
            "id": "e1",
            "summary": "Sync",
            "description": "agenda",
            "location": "Room A",
            "status": "confirmed",
            "htmlLink": "https://cal/e1",
            "creator": {"email": "a@x.com"},  # 노출 X
            "iCalUID": "abc",  # 노출 X
            "etag": "etag-xyz",  # 노출 X
            "start": {
                "dateTime": "2026-05-20T10:00:00+09:00",
                "timeZone": "Asia/Seoul",
            },
            "end": {"dateTime": "2026-05-20T11:00:00+09:00", "timeZone": "Asia/Seoul"},
        }
        out = _pick_event_fields(event)
        assert out["id"] == "e1"
        assert out["summary"] == "Sync"
        assert "iCalUID" not in out
        assert "creator" not in out
        assert "etag" not in out
        assert out["start"]["dateTime"] == "2026-05-20T10:00:00+09:00"

    def test_all_day_event(self):
        event = {
            "id": "all-day",
            "summary": "Holiday",
            "start": {"date": "2026-05-20"},
            "end": {"date": "2026-05-21"},
        }
        out = _pick_event_fields(event)
        assert out["start"] == {"date": "2026-05-20"}
        assert out["end"] == {"date": "2026-05-21"}

    def test_attendees_normalized(self):
        event = {
            "id": "e1",
            "summary": "S",
            "attendees": [
                {
                    "email": "a@x.com",
                    "responseStatus": "accepted",
                    "organizer": True,
                    "self": True,
                },
                {"email": "b@x.com", "responseStatus": "needsAction"},
            ],
        }
        out = _pick_event_fields(event)
        assert len(out["attendees"]) == 2
        assert out["attendees"][0] == {
            "email": "a@x.com",
            "response_status": "accepted",
            "organizer": True,
            "self": True,
        }
        assert out["attendees"][1]["organizer"] is False  # missing → False

    def test_organizer_email_only(self):
        event = {
            "id": "e1",
            "summary": "S",
            "organizer": {"email": "boss@x.com", "displayName": "Boss"},
        }
        out = _pick_event_fields(event)
        assert out["organizer"] == "boss@x.com"


# ---------------------------------------------------------------------------
# _compute_free_slots helper
# ---------------------------------------------------------------------------


def _dt(s):
    return datetime.fromisoformat(s)


class TestComputeFreeSlots:
    def test_no_busy_returns_whole_range(self):
        slots = _compute_free_slots(
            range_start=_dt("2026-05-20T09:00:00"),
            range_end=_dt("2026-05-20T17:00:00"),
            busy_intervals=[],
            min_duration_minutes=30,
        )
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 480  # 8h

    def test_single_busy_creates_two_gaps(self):
        slots = _compute_free_slots(
            range_start=_dt("2026-05-20T09:00:00"),
            range_end=_dt("2026-05-20T17:00:00"),
            busy_intervals=[(_dt("2026-05-20T11:00:00"), _dt("2026-05-20T12:00:00"))],
            min_duration_minutes=30,
        )
        assert len(slots) == 2
        assert slots[0]["start"] == "2026-05-20T09:00:00"
        assert slots[0]["end"] == "2026-05-20T11:00:00"
        assert slots[1]["start"] == "2026-05-20T12:00:00"
        assert slots[1]["end"] == "2026-05-20T17:00:00"

    def test_overlapping_busy_merged(self):
        slots = _compute_free_slots(
            range_start=_dt("2026-05-20T09:00:00"),
            range_end=_dt("2026-05-20T17:00:00"),
            busy_intervals=[
                (_dt("2026-05-20T10:00:00"), _dt("2026-05-20T12:00:00")),
                (_dt("2026-05-20T11:00:00"), _dt("2026-05-20T13:00:00")),  # overlaps
            ],
            min_duration_minutes=30,
        )
        # 두 busy 가 merge → [10:00, 13:00], gap: [09:00, 10:00] + [13:00, 17:00]
        assert len(slots) == 2
        assert slots[0]["end"] == "2026-05-20T10:00:00"
        assert slots[1]["start"] == "2026-05-20T13:00:00"

    def test_min_duration_filters_short_gaps(self):
        slots = _compute_free_slots(
            range_start=_dt("2026-05-20T09:00:00"),
            range_end=_dt("2026-05-20T17:00:00"),
            busy_intervals=[
                (_dt("2026-05-20T09:00:00"), _dt("2026-05-20T11:50:00")),
                # 10분 gap (11:50-12:00) — min_duration=30 으로 필터됨
                (_dt("2026-05-20T12:00:00"), _dt("2026-05-20T16:55:00")),
                # 5분 gap (16:55-17:00) — 필터됨
            ],
            min_duration_minutes=30,
        )
        assert len(slots) == 0  # 모두 짧아서 필터됨

    def test_busy_outside_range_ignored(self):
        slots = _compute_free_slots(
            range_start=_dt("2026-05-20T09:00:00"),
            range_end=_dt("2026-05-20T17:00:00"),
            busy_intervals=[
                # 범위 이전 — clip 되어 무시
                (_dt("2026-05-20T07:00:00"), _dt("2026-05-20T08:00:00")),
                # 범위 이후 — clip 되어 무시
                (_dt("2026-05-20T18:00:00"), _dt("2026-05-20T19:00:00")),
            ],
            min_duration_minutes=30,
        )
        assert len(slots) == 1
        assert slots[0]["duration_minutes"] == 480

    def test_busy_clipped_to_range(self):
        slots = _compute_free_slots(
            range_start=_dt("2026-05-20T09:00:00"),
            range_end=_dt("2026-05-20T17:00:00"),
            busy_intervals=[
                # 범위 일부만 걸침 — 8:00-10:00 → 9:00-10:00 으로 clip
                (_dt("2026-05-20T08:00:00"), _dt("2026-05-20T10:00:00")),
            ],
            min_duration_minutes=30,
        )
        assert len(slots) == 1
        assert slots[0]["start"] == "2026-05-20T10:00:00"
        assert slots[0]["end"] == "2026-05-20T17:00:00"

    def test_tz_aware_inputs(self):
        seoul = ZoneInfo("Asia/Seoul")
        slots = _compute_free_slots(
            range_start=datetime(2026, 5, 20, 9, 0, tzinfo=seoul),
            range_end=datetime(2026, 5, 20, 17, 0, tzinfo=seoul),
            busy_intervals=[
                (
                    datetime(2026, 5, 20, 11, 0, tzinfo=seoul),
                    datetime(2026, 5, 20, 12, 0, tzinfo=seoul),
                )
            ],
            min_duration_minutes=30,
        )
        assert len(slots) == 2

    def test_naive_busy_with_tz_range_skipped(self):
        # tz mismatch — busy 가 naive 면 무시 (안전 default)
        seoul = ZoneInfo("Asia/Seoul")
        slots = _compute_free_slots(
            range_start=datetime(2026, 5, 20, 9, 0, tzinfo=seoul),
            range_end=datetime(2026, 5, 20, 17, 0, tzinfo=seoul),
            busy_intervals=[
                (_dt("2026-05-20T11:00:00"), _dt("2026-05-20T12:00:00")),
            ],
            min_duration_minutes=30,
        )
        # busy 무시되고 전체가 free
        assert len(slots) == 1


# ---------------------------------------------------------------------------
# CalendarListEventsArgs validators
# ---------------------------------------------------------------------------


class TestCalendarListEventsArgs:
    def test_minimum_valid(self):
        args = CalendarListEventsArgs(
            time_min="2026-05-20T00:00:00",
            time_max="2026-05-20T23:59:59",
            timezone="Asia/Seoul",
        )
        assert args.max_results == 10
        assert args.q is None
        assert args.page_token is None

    @pytest.mark.parametrize("bad", ["+09:00", "Z", "GMT"])
    def test_iana_only(self, bad):
        # UTC 는 IANA ID 이고 DST 없어 허용 (별도 test_utc_allowed).
        with pytest.raises(Exception):
            CalendarListEventsArgs(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-21T00:00:00",
                timezone=bad,
            )

    def test_utc_allowed(self):
        args = CalendarListEventsArgs(
            time_min="2026-05-20T00:00:00",
            time_max="2026-05-21T00:00:00",
            timezone="UTC",
        )
        assert args.timezone == "UTC"

    def test_time_min_after_max_rejects(self):
        with pytest.raises(Exception):
            CalendarListEventsArgs(
                time_min="2026-05-21T00:00:00",
                time_max="2026-05-20T00:00:00",
                timezone="Asia/Seoul",
            )

    @pytest.mark.parametrize("bad", [0, 26, 100])
    def test_max_results_range(self, bad):
        with pytest.raises(Exception):
            CalendarListEventsArgs(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-21T00:00:00",
                timezone="Asia/Seoul",
                max_results=bad,
            )


# ---------------------------------------------------------------------------
# calendar_list_events tool end-to-end
# ---------------------------------------------------------------------------


class TestCalendarListEventsTool:
    def _tool(self):
        return [
            t for t in make_calendar_tools("u") if t.name == "calendar_list_events"
        ][0]

    async def test_forces_single_events_and_order_by(self):
        captured = {}

        async def mock_call(
            method, path, *, user_id, host, json=None, params=None, timeout=30.0
        ):
            captured.update(method=method, path=path, host=host, params=params)
            return {"items": [], "timeZone": "Asia/Seoul"}

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await self._tool().coroutine(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-20T23:59:59",
                timezone="Asia/Seoul",
            )
        # F4 — singleEvents=true + orderBy=startTime 강제
        assert captured["params"]["singleEvents"] == "true"
        assert captured["params"]["orderBy"] == "startTime"
        # naive datetime + tz → RFC 3339 with offset
        assert captured["params"]["timeMin"] == "2026-05-20T00:00:00+09:00"
        assert captured["params"]["timeMax"] == "2026-05-20T23:59:59+09:00"
        assert captured["params"]["timeZone"] == "Asia/Seoul"
        assert captured["method"] == "GET"
        assert captured["path"] == "/calendar/v3/calendars/primary/events"

    async def test_returns_picked_events(self):
        async def mock_call(*_a, **_k):
            return {
                "items": [
                    {
                        "id": "e1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-05-20T10:00:00+09:00"},
                        "end": {"dateTime": "2026-05-20T10:30:00+09:00"},
                        "iCalUID": "secret",  # should be filtered out
                    },
                ],
                "nextPageToken": "next-page",
                "timeZone": "Asia/Seoul",
            }

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-20T23:59:59",
                timezone="Asia/Seoul",
            )
        data = json.loads(result)
        assert len(data["events"]) == 1
        assert data["events"][0]["summary"] == "Standup"
        assert "iCalUID" not in data["events"][0]
        assert data["next_page_token"] == "next-page"

    async def test_q_and_page_token_propagate(self):
        captured = {}

        async def mock_call(*_a, **kwargs):
            captured["params"] = kwargs.get("params")
            return {"items": []}

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await self._tool().coroutine(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-20T23:59:59",
                timezone="Asia/Seoul",
                q="standup",
                page_token="tok123",
            )
        assert captured["params"]["q"] == "standup"
        assert captured["params"]["pageToken"] == "tok123"

    async def test_reauth_error_aborts(self):
        async def mock_call(*_a, **_k):
            raise GoogleReauthRequired(user_id="u", reason="invalid_grant")

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-20T23:59:59",
                timezone="Asia/Seoul",
            )
        data = json.loads(result)
        assert data["error"] == "google_reauth_required"

    async def test_api_error_returns_json(self):
        async def mock_call(*_a, **_k):
            raise GoogleApiError(403, "insufficient scope")

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                time_min="2026-05-20T00:00:00",
                time_max="2026-05-20T23:59:59",
                timezone="Asia/Seoul",
            )
        data = json.loads(result)
        assert data["error"] == "calendar_api_error_403"


# ---------------------------------------------------------------------------
# CalendarFindFreeSlotsArgs validators
# ---------------------------------------------------------------------------


class TestCalendarFindFreeSlotsArgs:
    def test_minimum_valid(self):
        args = CalendarFindFreeSlotsArgs(
            time_min="2026-05-20T09:00:00",
            time_max="2026-05-20T17:00:00",
            timezone="Asia/Seoul",
            attendees=["a@x.com"],
        )
        assert args.min_duration_minutes == 30

    def test_empty_attendees_rejects(self):
        with pytest.raises(Exception):
            CalendarFindFreeSlotsArgs(
                time_min="2026-05-20T09:00:00",
                time_max="2026-05-20T17:00:00",
                timezone="Asia/Seoul",
                attendees=[],
            )

    @pytest.mark.parametrize("bad", [4, 481, 0, -1])
    def test_min_duration_range(self, bad):
        with pytest.raises(Exception):
            CalendarFindFreeSlotsArgs(
                time_min="2026-05-20T09:00:00",
                time_max="2026-05-20T17:00:00",
                timezone="Asia/Seoul",
                attendees=["a@x.com"],
                min_duration_minutes=bad,
            )


# ---------------------------------------------------------------------------
# calendar_find_free_slots tool end-to-end
# ---------------------------------------------------------------------------


class TestCalendarFindFreeSlotsTool:
    def _tool(self):
        return [
            t for t in make_calendar_tools("u") if t.name == "calendar_find_free_slots"
        ][0]

    async def test_request_body_shape(self):
        captured = {}

        async def mock_call(*_a, **kwargs):
            captured.update(kwargs)
            return {"calendars": {}}

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await self._tool().coroutine(
                time_min="2026-05-20T09:00:00",
                time_max="2026-05-20T17:00:00",
                timezone="Asia/Seoul",
                attendees=["a@x.com", "primary"],
            )
        body = captured["json"]
        # tz aware (offset 부여됨)
        assert body["timeMin"] == "2026-05-20T09:00:00+09:00"
        assert body["timeMax"] == "2026-05-20T17:00:00+09:00"
        assert body["timeZone"] == "Asia/Seoul"
        assert body["items"] == [{"id": "a@x.com"}, {"id": "primary"}]

    async def test_computes_common_free_slots(self):
        async def mock_call(*_a, **_k):
            # 두 attendee 의 busy 가 다름 → 공통 free 는 둘 다 비어있는 시간만
            return {
                "calendars": {
                    "a@x.com": {
                        "busy": [
                            {
                                "start": "2026-05-20T10:00:00+09:00",
                                "end": "2026-05-20T11:00:00+09:00",
                            }
                        ]
                    },
                    "b@x.com": {
                        "busy": [
                            {
                                "start": "2026-05-20T13:00:00+09:00",
                                "end": "2026-05-20T14:00:00+09:00",
                            }
                        ]
                    },
                }
            }

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                time_min="2026-05-20T09:00:00",
                time_max="2026-05-20T17:00:00",
                timezone="Asia/Seoul",
                attendees=["a@x.com", "b@x.com"],
                min_duration_minutes=30,
            )
        data = json.loads(result)
        # 09-10, 11-13, 14-17 세 slot
        assert len(data["common_free_slots"]) == 3
        durations = [s["duration_minutes"] for s in data["common_free_slots"]]
        assert durations == [60, 120, 180]
        # busy_by_attendee 는 raw 그대로
        assert "a@x.com" in data["busy_by_attendee"]
        assert "b@x.com" in data["busy_by_attendee"]
        assert data["timezone"] == "Asia/Seoul"

    async def test_errors_surfaced(self):
        async def mock_call(*_a, **_k):
            return {
                "calendars": {
                    "private@x.com": {
                        "errors": [{"domain": "global", "reason": "notFound"}],
                        "busy": [],
                    }
                }
            }

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                time_min="2026-05-20T09:00:00",
                time_max="2026-05-20T17:00:00",
                timezone="Asia/Seoul",
                attendees=["private@x.com"],
            )
        data = json.loads(result)
        assert "private@x.com" in data["errors_by_attendee"]
        # 본인 캘린더 못 봤지만 free slot 은 전체 범위 (busy 가 빈 list)
        assert len(data["common_free_slots"]) == 1

    async def test_reauth_aborts(self):
        async def mock_call(*_a, **_k):
            raise GoogleReauthRequired(user_id="u")

        with patch(
            "extension_modules.tools.google.inprocess.calendar.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                time_min="2026-05-20T09:00:00",
                time_max="2026-05-20T17:00:00",
                timezone="Asia/Seoul",
                attendees=["a@x.com"],
            )
        data = json.loads(result)
        assert data["error"] == "google_reauth_required"
