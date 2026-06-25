"""drive_select_files 의 respond-only 분류 + scoped 정책 리졸버 테스트."""

from __future__ import annotations

from extension_modules.agent.hitl_policy import (
    _RESPOND_ONLY,
    build_interrupt_policy,
    resolve_interrupt_policy,
)


class _T:
    def __init__(self, name):
        self.name = name


_TOOLS = [_T("drive_select_files"), _T("gmail_send"), _T("drive_search")]


def test_picker_in_respond_only():
    assert "drive_select_files" in _RESPOND_ONLY


def test_build_policy_gives_picker_respond_only():
    policy = build_interrupt_policy(_TOOLS)
    assert policy["drive_select_files"] == {"allowed_decisions": ["respond"]}
    # 회귀 보존: 마커는 그대로 interrupt 대상(True), read 는 자동승인(False)
    assert policy["gmail_send"] is True
    assert policy["drive_search"] is False


def test_resolve_enable_hitl_uses_full_policy():
    policy = resolve_interrupt_policy(_TOOLS, enable_hitl=True, picker_active=True)
    assert policy["gmail_send"] is True
    assert policy["drive_select_files"] == {"allowed_decisions": ["respond"]}


def test_resolve_scoped_intercepts_only_picker():
    policy = resolve_interrupt_policy(_TOOLS, enable_hitl=False, picker_active=True)
    assert policy == {"drive_select_files": {"allowed_decisions": ["respond"]}}
    # 마커가 정책에 없음 → 자동승인 → 마커 카드 보존(C-1 회피)
    assert "gmail_send" not in policy


def test_resolve_off_returns_empty():
    policy = resolve_interrupt_policy(_TOOLS, enable_hitl=False, picker_active=False)
    assert policy == {}
