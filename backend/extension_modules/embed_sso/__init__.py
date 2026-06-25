"""Embed widget SSO token exchange.

호스트 사이트가 이미 보유한 SSO 토큰(Microsoft Entra ID, Google, GitHub,
Generic OIDC 등)을 받아 검증하고, 매칭되는 Cloosphere 사용자를 찾거나 자동
가입시킨 뒤 Cloosphere JWT를 발급하기 위한 모듈.
"""

from .registry import SSO_PROVIDERS, get_sso_provider
from .schemas import SSOExchangeRequest, SSOUserClaims

__all__ = [
    "SSO_PROVIDERS",
    "get_sso_provider",
    "SSOExchangeRequest",
    "SSOUserClaims",
]
