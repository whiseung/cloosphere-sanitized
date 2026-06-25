"""HITL confirmation marker → assistant content streaming (regression).

gmail_send / calendar_create_event / drive_create_doc return a
``[*_confirmation_required]`` + ```json {...}``` marker. The frontend
``ContentRenderer.svelte`` parses this OUT OF THE ASSISTANT CONTENT to render
the confirmation card (Create/Cancel buttons + the HMAC ``message_id`` needed to
confirm). The marker must therefore reach the assistant content VERBATIM.

Bug: the markers only landed in ``google_results_context`` (final-answer LLM
context), so the LLM paraphrased them into prose and the card never rendered —
no "Create event" button. These tests pin the pure helpers that decide which
ToolMessages are HITL confirmations and what content is streamed for them.
"""

from __future__ import annotations

from extension_modules.agent.hitl_confirmation import (
    extract_hitl_confirmation_content,
    hitl_ack_message,
    is_hitl_confirmation,
)
from langchain_core.messages import AIMessage, ToolMessage

CAL_MARKER = "[calendar_confirmation_required]"
GMAIL_MARKER = "[gmail_confirmation_required]"
DRIVE_MARKER = "[drive_confirmation_required]"


def _cal_msg() -> ToolMessage:
    return ToolMessage(
        content=(
            f"{CAL_MARKER}\n```json\n"
            '{"message_id": "abc.def", "tool": "calendar_create_event", '
            '"draft": {"title": "삼성미팅"}}\n```'
        ),
        tool_call_id="1",
        name="calendar_create_event",
    )


def test_is_hitl_confirmation_detects_each_marker():
    for marker in (CAL_MARKER, GMAIL_MARKER, DRIVE_MARKER):
        assert is_hitl_confirmation(f"{marker}\n```json\n{{}}\n```") is True


def test_is_hitl_confirmation_false_for_plain_results():
    assert is_hitl_confirmation('{"events": []}') is False
    assert is_hitl_confirmation("") is False
    assert is_hitl_confirmation(None) is False


def test_extract_returns_marker_block_verbatim():
    content = extract_hitl_confirmation_content([_cal_msg()])
    assert CAL_MARKER in content
    # message_id MUST survive — without it the frontend confirm cannot fire.
    assert '"message_id"' in content
    assert "삼성미팅" in content


def test_extract_skips_non_confirmation_tool_messages():
    search = ToolMessage(
        content='{"events": [{"id": "x"}]}',
        tool_call_id="2",
        name="calendar_list_events",
    )
    assert extract_hitl_confirmation_content([search]) == ""


def test_extract_ignores_non_tool_messages():
    # An AIMessage that merely echoes the marker text must NOT trigger a card.
    ai = AIMessage(content=f"I will show {CAL_MARKER}")
    assert extract_hitl_confirmation_content([ai]) == ""


def test_extract_concatenates_multiple_markers():
    gmail = ToolMessage(
        content=f"{GMAIL_MARKER}\n```json\n{{}}\n```",
        tool_call_id="3",
        name="gmail_send",
    )
    out = extract_hitl_confirmation_content([_cal_msg(), gmail])
    assert CAL_MARKER in out and GMAIL_MARKER in out


def test_extract_empty_for_no_messages():
    assert extract_hitl_confirmation_content([]) == ""
    assert extract_hitl_confirmation_content(None) == ""


def test_ack_message_is_localized():
    assert "확인" in hitl_ack_message("ko")
    assert "확인" in hitl_ack_message("Korean")
    # Non-Korean falls back to English.
    en = hitl_ack_message("en")
    assert "confirm" in en.lower()
