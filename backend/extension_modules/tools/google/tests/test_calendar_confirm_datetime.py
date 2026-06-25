"""CalendarConfirmBody datetime normalization (regression).

The frontend ``CalendarConfirmation.svelte`` uses ``<input type="datetime-local">``
which, with no ``step``, yields second-less values like ``2026-06-10T14:00`` and
submits them verbatim. Python's ``datetime.fromisoformat`` accepts that, so the
old validator passed it through, and Google Calendar's ``events.insert`` rejected
the non-RFC3339 string with ``400 Bad Request`` ("일정 등록에 실패했습니다", surfaced
as a 502 from the confirm route). The confirm body is the sole choke point before
the Google call, so it normalizes start/end to include seconds.
"""

from __future__ import annotations

import pytest
from open_webui.routers.google_actions import CalendarConfirmBody


def _body(start: str, end: str) -> CalendarConfirmBody:
    return CalendarConfirmBody(title="t", start=start, end=end, timezone="Asia/Seoul")


def test_seconds_added_when_missing():
    # The actual datetime-local output — the bug repro.
    b = _body("2026-06-10T14:00", "2026-06-10T15:00")
    assert b.start == "2026-06-10T14:00:00"
    assert b.end == "2026-06-10T15:00:00"


def test_seconds_preserved_when_present():
    b = _body("2026-06-10T14:00:00", "2026-06-10T15:30:45")
    assert b.start == "2026-06-10T14:00:00"
    assert b.end == "2026-06-10T15:30:45"


def test_offset_preserved():
    # Naive+timeZone and offset+timeZone are both valid for Google; don't drop offset.
    b = _body("2026-06-10T14:00:00+09:00", "2026-06-10T15:00:00+09:00")
    assert b.start == "2026-06-10T14:00:00+09:00"
    assert b.end == "2026-06-10T15:00:00+09:00"


def test_start_before_end_still_enforced_after_normalization():
    # Normalization must not weaken the start < end guard (second-less inputs).
    with pytest.raises(Exception):
        _body("2026-06-10T15:00", "2026-06-10T14:00")
    with pytest.raises(Exception):
        _body("2026-06-10T14:00", "2026-06-10T14:00")


def test_invalid_datetime_still_rejected():
    with pytest.raises(Exception):
        _body("not-a-date", "2026-06-10T15:00")
