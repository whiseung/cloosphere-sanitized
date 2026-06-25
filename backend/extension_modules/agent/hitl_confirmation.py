"""HITL confirmation marker handling for UnifiedAgent streaming.

``gmail_send`` / ``calendar_create_event`` / ``drive_create_doc`` are HITL-gated:
the tool does NOT perform the write, it returns a ``[*_confirmation_required]``
marker + a ```json {...}``` block (built by ``inprocess/_hitl.py``) carrying the
editable draft and an HMAC-bound ``message_id``.

The frontend ``ContentRenderer.svelte`` parses this block OUT OF THE ASSISTANT
CONTENT (regex ``HITL_RE``) to render the Gmail/Calendar/Drive confirmation card
(Create/Cancel buttons → ``POST /api/v1/google/{gmail,calendar,drive}/confirm/
{message_id}``). The marker must therefore reach the assistant content VERBATIM,
mirroring the image (``![Generated Image]``) and document (``DOCUMENT_TOOL_MARKER``)
direct-stream paths in ``unified_agent._run_stream``.

Regression this guards: the markers used to land only in
``google_results_context`` (the final-answer LLM context), so the LLM paraphrased
them into prose and the card — and its "Create event" button — never rendered.

The marker strings are duplicated here on purpose. They are also defined in each
tool module (``{gmail,calendar,drive}.py`` ``*_CONFIRM_MARKER``) and in the
frontend ``HITL_RE`` regex — a stable cross-layer contract, not shared state.
"""

from __future__ import annotations

from langchain_core.messages import ToolMessage

# Mirror of GMAIL_CONFIRM_MARKER / CALENDAR_CONFIRM_MARKER / DRIVE_CONFIRM_MARKER
# in extension_modules/tools/google/inprocess/{gmail,calendar,drive}.py and the
# HITL_RE regex in src/lib/components/chat/Messages/ContentRenderer.svelte.
HITL_CONFIRM_MARKERS: tuple[str, ...] = (
    "[gmail_confirmation_required]",
    "[calendar_confirmation_required]",
    "[drive_confirmation_required]",
)


def is_hitl_confirmation(content) -> bool:
    """True if ``content`` carries any HITL confirmation marker."""
    return isinstance(content, str) and any(m in content for m in HITL_CONFIRM_MARKERS)


def extract_hitl_confirmation_content(messages) -> str:
    """Verbatim confirmation marker block(s) from ToolMessages, joined by a blank line.

    Only ``ToolMessage`` content is considered — an ``AIMessage`` that merely
    echoes the marker text must never trigger a card. Returns ``""`` when no tool
    confirmation is present (the common case).
    """
    parts: list[str] = []
    for msg in messages or []:
        if isinstance(msg, ToolMessage) and is_hitl_confirmation(
            getattr(msg, "content", None)
        ):
            parts.append(msg.content.strip())
    return "\n\n".join(parts)


def hitl_ack_message(language: str) -> str:
    """Short, deterministic acknowledgment streamed alongside the card.

    The card itself carries every editable field and the action buttons, so this
    is a single friendly line (not a re-listing of the draft). Keyed off the
    agent's detected language; Korean vs. English only (the product's two locales).
    """
    raw = language or ""
    lang = raw.lower()
    if "ko" in lang or "korean" in lang or "한" in raw:
        return "요청하신 내용을 아래에서 확인한 뒤 진행해 주세요."
    return "Please review the details below and confirm to proceed."


__all__ = [
    "HITL_CONFIRM_MARKERS",
    "is_hitl_confirmation",
    "extract_hitl_confirmation_content",
    "hitl_ack_message",
]
