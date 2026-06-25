"""routers/email_integration.py 의 기능별 scope 충족 판정(_gws_feature_flags) 테스트.

``GET /api/v1/email/connections`` 응답의 google ``features`` 필드는 프론트
채팅 토글(InputMenu)의 OAuth 축 게이트 소스다 — 토큰 row 존재(connected)와
별개로, 기능별 필수 scope 전부 보유 시에만 true.
"""

from __future__ import annotations

from open_webui.config import GWS_FEATURE_REQUIRED_SCOPES
from open_webui.routers.email_integration import _gws_feature_flags


def test_empty_scope_blocks_all():
    flags = _gws_feature_flags(None)
    assert flags == {"gmail": False, "calendar": False, "drive": False}
    assert _gws_feature_flags("") == flags


def test_full_delegated_scopes_enable_all():
    scope_str = " ".join(sorted(set().union(*GWS_FEATURE_REQUIRED_SCOPES.values())))
    assert _gws_feature_flags(scope_str) == {
        "gmail": True,
        "calendar": True,
        "drive": True,
    }


def test_legacy_sso_scope_blocks_all():
    # GWS delegated scope 도입 이전 SSO 토큰 (openid email profile)
    flags = _gws_feature_flags("openid email profile")
    assert flags == {"gmail": False, "calendar": False, "drive": False}


def test_partial_scopes_judged_per_feature():
    scope_str = (
        "openid email profile "
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar.events"
    )
    flags = _gws_feature_flags(scope_str)
    assert flags["gmail"] is True
    assert flags["calendar"] is True
    assert flags["drive"] is False  # drive + documents 누락
