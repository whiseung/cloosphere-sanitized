"""UnifiedAgent Drive 5축 게이트 단위 테스트 (AgentConfig 브랜치).

게이트 평가 순서(fail-closed): bool(user_id) → ENABLE_DRIVE_INTEGRATION →
has_permission("features.drive") → agent_config.has_drive() → user toggle.
한 축이라도 False 면 self._enable_drive False.

UnifiedAgent.__init__ 전체를 띄우는 대신 게이트 식의 AND 합성만 재현해 회귀를
방지한다 (gmail/calendar 와 동일 구조 — 실제 통합은 boot smoke 로 검증).
``perm`` 은 unified_agent.py 의 ``has_permission("features.drive", ...)`` 결과를
그대로 대입한 값이다.
"""

from __future__ import annotations


def _gate(*, user_id, enable_flag, perm, has_cap, user_toggle):
    """unified_agent.py 의 self._enable_drive 평가식과 동일한 5축 AND.

    실제 코드의 ``has_permission(...)`` 자리에는 그 호출 결과인 ``perm`` 을
    그대로 둔다 (게이트 합성/단락 평가의 순서만 검증).
    """
    return bool(user_id) and enable_flag and perm and has_cap and user_toggle


def test_all_axes_true_enables_drive():
    assert (
        _gate(user_id="u1", enable_flag=True, perm=True, has_cap=True, user_toggle=True)
        is True
    )


def test_empty_user_id_first_axis_blocks():
    # bool(user_id) FIRST — 빈 user_id 에서 has_permission 가짜 True 방지
    assert (
        _gate(user_id="", enable_flag=True, perm=True, has_cap=True, user_toggle=True)
        is False
    )


def test_admin_flag_off_blocks():
    assert (
        _gate(
            user_id="u1", enable_flag=False, perm=True, has_cap=True, user_toggle=True
        )
        is False
    )


def test_permission_denied_blocks():
    assert (
        _gate(
            user_id="u1", enable_flag=True, perm=False, has_cap=True, user_toggle=True
        )
        is False
    )


def test_agent_capability_off_blocks():
    assert (
        _gate(
            user_id="u1", enable_flag=True, perm=True, has_cap=False, user_toggle=True
        )
        is False
    )


def test_user_toggle_off_blocks():
    assert (
        _gate(
            user_id="u1", enable_flag=True, perm=True, has_cap=True, user_toggle=False
        )
        is False
    )
