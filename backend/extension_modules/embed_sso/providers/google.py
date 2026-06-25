"""Google Sign-In SSO provider.

Google ID token은 표준 OIDC라 GenericOIDCProvider를 그대로 사용한다.
issuer는 항상 `https://accounts.google.com`로 고정.
"""

from __future__ import annotations

from typing import Optional

from ..schemas import SSOExchangeRequest, SSOUserClaims
from .base import BaseSSOProvider
from .oidc import GenericOIDCProvider

GOOGLE_ISSUER = "https://accounts.google.com"


class GoogleSSOProvider(BaseSSOProvider):
    name = "google"

    def __init__(self, trusted_audiences: Optional[list[str]] = None):
        self._oidc = GenericOIDCProvider(
            trusted_issuers=[GOOGLE_ISSUER, "accounts.google.com"],
            trusted_audiences=trusted_audiences,
        )

    async def verify(self, request: SSOExchangeRequest) -> SSOUserClaims:
        if request.id_token and not request.issuer:
            request = request.model_copy(update={"issuer": GOOGLE_ISSUER})
        return await self._oidc.verify(request)
