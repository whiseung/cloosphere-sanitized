"""In-process Google Workspace tool provider.

httpx AsyncClient + Bearer token 으로 Google API 를 직접 호출하는 형태.
미래에 `tool_connection/` provider 와 swap 가능하도록 entry point 를 분리.

각 모듈:
- ``_common``  : http client, tenacity backoff, IANA tz, audit_log, get_token,
                 GoogleReauthRequired, enforce_write_quota
- ``_hitl``    : HITL confirmation_required 응답 helper + risk classifier
- ``gmail``    : gmail_send / gmail_search / gmail_get
- ``calendar`` : calendar_create_event / calendar_list_events / find_free_slots
- ``drive``    : drive_search / drive_get_content / drive_create_doc
"""

from extension_modules.tools.google.inprocess.calendar import make_calendar_tools
from extension_modules.tools.google.inprocess.drive import make_drive_tools
from extension_modules.tools.google.inprocess.gmail import make_gmail_tools
from extension_modules.tools.google.inprocess.send import (
    create_calendar_event_now,
    create_drive_doc_now,
    send_gmail_now,
)

__all__ = [
    "make_gmail_tools",
    "make_calendar_tools",
    "make_drive_tools",
    "send_gmail_now",
    "create_calendar_event_now",
    "create_drive_doc_now",
]
