"""hitl_policy 의 Google read 도구 auto-approve 분류 테스트 (M4/P4).

ENABLE_HITL=true 환경에서 deny-by-default 인 build_interrupt_policy 가 Google
'읽기' 도구까지 승인카드를 띄우던 선재 불일치를 막는다.  write/마커 HITL 도구
(gmail_send/drive_create_doc/calendar_create_event)는 auto-approve 대상이 아니다.
"""

from __future__ import annotations

import pytest
from extension_modules.agent.hitl_policy import _is_auto_approve

_READ_TOOLS = [
    "drive_search",
    "drive_get_content",
    "drive_get_contents",
    "gmail_search",
    "gmail_get",
    "gmail_get_batch",
    "calendar_list_events",
    "calendar_find_free_slots",
]

_WRITE_TOOLS = [
    "gmail_send",
    "drive_create_doc",
    "calendar_create_event",
]


@pytest.mark.parametrize("name", _READ_TOOLS)
def test_google_read_tools_auto_approve(name):
    assert _is_auto_approve(name) is True


@pytest.mark.parametrize("name", _WRITE_TOOLS)
def test_google_write_tools_not_auto_approve(name):
    assert _is_auto_approve(name) is False
