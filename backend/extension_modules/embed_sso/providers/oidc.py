"""Generic OIDC provider — verify any provider that supports OIDC discovery + JWKS.

이 provider는 두 가지 모드로 동작한다:

1. **id_token 검증 모드** (권장)
   - 호스트가 OIDC id_token (JWT)을 보내면 issuer의 JWKS로 서명 검증
   - 가장 안전하고 빠름 (네트워크 호출 1회, 캐시 가능)

2. **userinfo 호출 모드** (fallback)
   - id_token이 없고 access_token만 있으면 issuer의 userinfo 엔드포인트를 호출
   - provider가 OIDC discovery를 지원해야 함
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import jwt
from jwt import PyJWKClient

from ..schemas import SSOExchangeRequest, SSOUserClaims
from .base import BaseSSOProvider

log = logging.getLogger(__name__)

# JWKS 클라이언트 캐시 (issuer URL → PyJWKClient)
_JWKS_CACHE: dict[str, PyJWKClient] = {}
# Discovery 캐시 (issuer URL → metadata dict)
_DISCOVERY_CACHE: dict[str, dict[str, Any]] = {}
_DISCOVERY_CACHE_TTL = 3600  # 1시간
_DISCOVERY_CACHE_TS: dict[str, float] = {}


class GenericOIDCProvider(BaseSSOProvider):
    name = "oidc"

    #: 명시적으로 신뢰하는 audience 목록 (위젯 config에서 주입 가능). 비어있으면
    #: audience 검증을 건너뛴다 (호스트가 다양한 client_id로 발급할 수 있음).
    trusted_audiences: Optional[list[str]] = None
    #: 명시적으로 신뢰하는 issuer 목록. 비어있으면 토큰의 iss를 그대로 사용.
    trusted_issuers: Optional[list[str]] = None

    def __init__(
        self,
        trusted_issuers: Optional[list[str]] = None,
        trusted_audiences: Optional[list[str]] = None,
    ):
        self.trusted_issuers = trusted_issuers or []
        self.trusted_audiences = trusted_audiences or []

    async def verify(self, request: SSOExchangeRequest) -> SSOUserClaims:
        if request.id_token:
            return await self._verify_id_token(request.id_token, request.issuer)
        if request.access_token and request.issuer:
            return await self._verify_via_userinfo(request.access_token, request.issuer)
        raise ValueError(
            "OIDC provider requires either id_token or (access_token + issuer)"
        )

    # ---- mode 1: JWT signature verification ---------------------------------

    async def _verify_id_token(
        self, id_token: str, issuer_hint: Optional[str]
    ) -> SSOUserClaims:
        # iss, aud는 unverified로 먼저 꺼내본다
        try:
            unverified = jwt.decode(id_token, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid id_token format: {e}")

        iss = issuer_hint or unverified.get("iss")
        if not iss:
            raise ValueError("id_token missing 'iss' claim and no issuer hint")

        if self.trusted_issuers and iss not in self.trusted_issuers:
            raise ValueError(f"Issuer not trusted: {iss}")

        metadata = await self._get_oidc_metadata(iss)
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise ValueError(f"OIDC discovery missing jwks_uri for issuer {iss}")

        # JWKS client 캐싱
        jwks_client = _JWKS_CACHE.get(jwks_uri)
        if jwks_client is None:
            jwks_client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
            _JWKS_CACHE[jwks_uri] = jwks_client

        try:
            signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        except Exception as e:
            raise ValueError(f"Failed to fetch signing key: {e}")

        decode_options = {
            "verify_signature": True,
            "verify_iss": True,
            "verify_exp": True,
        }
        decode_kwargs: dict[str, Any] = {
            "issuer": iss,
            "options": decode_options,
        }
        if self.trusted_audiences:
            decode_kwargs["audience"] = self.trusted_audiences
        else:
            decode_options["verify_aud"] = False

        try:
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256"],
                **decode_kwargs,
            )
        except jwt.PyJWTError as e:
            raise ValueError(f"id_token verification failed: {e}")

        return self._claims_to_user(claims)

    # ---- mode 2: userinfo endpoint ------------------------------------------

    async def _verify_via_userinfo(
        self, access_token: str, issuer: str
    ) -> SSOUserClaims:
        metadata = await self._get_oidc_metadata(issuer)
        userinfo_endpoint = metadata.get("userinfo_endpoint")
        if not userinfo_endpoint:
            raise ValueError(
                f"OIDC discovery missing userinfo_endpoint for issuer {issuer}"
            )

        claims = await self._http_get_json(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return self._claims_to_user(claims)

    # ---- helpers -------------------------------------------------------------

    async def _get_oidc_metadata(self, issuer: str) -> dict[str, Any]:
        now = time.time()
        cached_ts = _DISCOVERY_CACHE_TS.get(issuer, 0)
        if issuer in _DISCOVERY_CACHE and now - cached_ts < _DISCOVERY_CACHE_TTL:
            return _DISCOVERY_CACHE[issuer]

        # OIDC discovery URL: {issuer}/.well-known/openid-configuration
        discovery_url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        metadata = await self._http_get_json(discovery_url)
        _DISCOVERY_CACHE[issuer] = metadata
        _DISCOVERY_CACHE_TS[issuer] = now
        return metadata

    def _claims_to_user(self, claims: dict[str, Any]) -> SSOUserClaims:
        sub = claims.get("sub") or claims.get("oid")
        if not sub:
            raise ValueError("Token missing 'sub' claim")
        email = self._require_email(claims)
        return SSOUserClaims(
            sub=str(sub),
            email=email,
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name") or claims.get("preferred_username"),
            picture=claims.get("picture"),
            raw=claims,
        )
