"""Current date/time anchor in the tool-calling system prompt (regression).

Without an explicit "today" the LLM guesses relative dates — "내일 14시" was
booked on today's date. ``get_unified_system_prompt`` now accepts
``current_datetime`` and injects a reference the LLM resolves against.
"""

from __future__ import annotations

from extension_modules.agent.prompts import get_unified_system_prompt

NOW = "2026-06-09 (Tue) 08:51, timezone Asia/Seoul"


def test_datetime_hint_present_when_provided():
    p = get_unified_system_prompt(
        active_capabilities=["calendar"], current_datetime=NOW
    )
    assert "Current date and time" in p
    assert "2026-06-09" in p
    assert "Asia/Seoul" in p
    # Relative-date guidance (both locales) so the LLM resolves 내일/tomorrow.
    assert "tomorrow" in p and "내일" in p


def test_no_datetime_hint_when_absent():
    # Back-compat: callers that don't pass current_datetime get the old prompt.
    p = get_unified_system_prompt(active_capabilities=["calendar"])
    assert "Current date and time" not in p


def test_datetime_hint_independent_of_capabilities():
    # The anchor applies to all time reasoning, not just calendar.
    p = get_unified_system_prompt(active_capabilities=[], current_datetime=NOW)
    assert "Current date and time" in p
