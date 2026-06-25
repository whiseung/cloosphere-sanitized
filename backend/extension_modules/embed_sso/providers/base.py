"""Base SSO provider interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiohttp

from ..schemas import SSOExchangeRequest, SSOUserClaims

log = logging.getLogger(__name__)


class BaseSSOProvider(ABC):
    """SSO provider 추상 베이스.

    구현체는 호스트가 보낸 토큰을 검증하고 정규화된 `SSOUserClaims`를
    반환해야 한다. 검증 실패는 ValueError를 던져야 하며, 라우터에서
    HTTP 401로 변환된다.
    """

    #: 위젯 config의 `sso.providers` 화이트리스트와 매칭되는 키
    name: str = ""

    @abstractmethod
    async def verify(self, request: SSOExchangeRequest) -> SSOUserClaims:
        """Verify the supplied token(s) and return normalized user claims."""
        raise NotImplementedError

    # ---- shared helpers ------------------------------------------------------

    async def _http_get_json(
        self, url: str, headers: Optional[dict[str, str]] = None
    ) -> dict[str, Any]:
        """Issue a GET request and return JSON, raising on non-2xx."""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if not resp.ok:
                    text = await resp.text()
                    raise ValueError(f"HTTP {resp.status} from {url}: {text[:200]}")
                return await resp.json()

    @staticmethod
    def _require_email(claims: dict[str, Any]) -> str:
        """Pull an email out of common claim names; raise if absent."""
        for key in ("email", "preferred_username", "upn"):
            value = claims.get(key)
            if value and isinstance(value, str) and "@" in value:
                return value.lower()
        raise ValueError("Token does not contain an email claim")
