"""UnifiedAgent GWS 5축 게이트의 (5) OAuth scope 축 단위 테스트.

4축(user_id / admin flag / group permission / capability+user toggle) 통과 후
사용자 google 토큰의 scope 가 ``GWS_FEATURE_REQUIRED_SCOPES[feature]`` 를 전부
보유해야 도구가 노출된다 (fail-closed).  GWS delegated scope 도입 이전 SSO
토큰은 row 가 있어도 scope 미달 → 비활성.

test_drive_gate.py 와 동일하게 UnifiedAgent.__init__ 전체를 띄우는 대신
unified_agent.py 의 scope AND 식만 재현해 회귀를 방지한다.  필수 scope 상수는
실제 ``open_webui.config.GWS_FEATURE_REQUIRED_SCOPES`` 를 임포트해 계약을 고정.
"""

from __future__ import annotations

from open_webui.config import GWS_FEATURE_REQUIRED_SCOPES


def _scope_axis(feature: str, *, gate: bool, granted: set[str]) -> bool:
    """unified_agent.py 의 ``self._enable_<feature> and REQUIRED <= granted`` 식."""
    return gate and GWS_FEATURE_REQUIRED_SCOPES[feature] <= granted


ALL_DELEGATED = set().union(*GWS_FEATURE_REQUIRED_SCOPES.values())


def test_no_token_blocks_all_features():
    # 토큰 row 없음 → granted 빈 set → 3개 기능 전부 차단
    for feature in ("gmail", "calendar", "drive"):
        assert _scope_axis(feature, gate=True, granted=set()) is False


def test_full_delegated_scopes_pass_all_features():
    for feature in ("gmail", "calendar", "drive"):
        assert _scope_axis(feature, gate=True, granted=ALL_DELEGATED) is True


def test_partial_gmail_scope_blocks_gmail():
    # gmail.readonly 만 보유 (send 누락) → gmail 차단
    granted = {"https://www.googleapis.com/auth/gmail.readonly"}
    assert _scope_axis("gmail", gate=True, granted=granted) is False


def test_calendar_scope_alone_enables_calendar_only():
    granted = {"https://www.googleapis.com/auth/calendar.events"}
    assert _scope_axis("calendar", gate=True, granted=granted) is True
    assert _scope_axis("gmail", gate=True, granted=granted) is False
    assert _scope_axis("drive", gate=True, granted=granted) is False


def test_drive_requires_documents_scope_too():
    # drive_create_doc 은 Drive files.create + Docs batchUpdate 2-call —
    # documents scope 가 빠지면 drive 기능 차단
    granted = {"https://www.googleapis.com/auth/drive"}
    assert _scope_axis("drive", gate=True, granted=granted) is False


def test_scope_axis_does_not_resurrect_failed_gate():
    # 앞 4축에서 이미 False 면 scope 가 충분해도 False 유지
    for feature in ("gmail", "calendar", "drive"):
        assert _scope_axis(feature, gate=False, granted=ALL_DELEGATED) is False
