"""
External IDP(Entra / Google) ID 토큰 passthrough 인증.

고객사 앱이 자체 OAuth (Entra / Google) 로 받은 ID 토큰을 `Authorization: Bearer`
헤더로 Cloosphere API 에 전달하면, 이 모듈이:

  1) 토큰 header 에서 `kid` 추출
  2) issuer 의 OIDC discovery (`/.well-known/openid-configuration`) 로 JWKS URI 획득
  3) JWKS 에서 해당 kid 의 공개키 로드 (인메모리 TTL 캐시)
  4) 서명/만료/audience/issuer 검증
  5) claim (Entra: `oid`/`sub`, Google: `sub`) → Cloosphere User 매핑

관리자는 `TrustedAudiences` 테이블에 허용할 audience(app_id/client_id) 를 등록해야
한다. 등록되지 않은 audience 의 토큰은 전부 거부된다.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.trusted_audiences import (
    TrustedAudienceModel,
    TrustedAudiences,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", "INFO"))


_JWKS_TTL_SEC = 3600  # JWKS 1시간 캐시 (Entra/Google 권장)
_DISCOVERY_TTL_SEC = 24 * 3600  # OIDC discovery doc 는 거의 불변
_HTTP_TIMEOUT = 5.0

# { issuer: (expires_at_epoch, { 'jwks_uri': str, 'issuer': str }) }
_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}
# { jwks_uri: (expires_at_epoch, { kid: key_dict }) }
_JWKS_CACHE: dict[str, tuple[float, dict]] = {}


class ExternalTokenError(Exception):
    """인증 실패 사유를 구체화하는 예외. 상위 레이어가 로그용으로 사용."""


def _expected_issuers(aud: TrustedAudienceModel) -> list[str]:
    """명시적 `issuer` 가 있으면 그것, 없으면 idp_type 기반 자동 계산.

    Entra: https://login.microsoftonline.com/{tenant}/v2.0  (tenant 빈 값이면 common)
    Google: https://accounts.google.com  (또는 https://accounts.google.com prefix 허용)
    """
    if aud.issuer:
        return [aud.issuer.rstrip("/")]
    if aud.idp_type == "entra":
        tenant = (aud.tenant_id or "").strip() or "common"
        return [f"https://login.microsoftonline.com/{tenant}/v2.0"]
    if aud.idp_type == "google":
        return ["https://accounts.google.com"]
    return []


def _fetch_discovery(issuer: str) -> dict:
    now = time.time()
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached and cached[0] > now:
        return cached[1]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(url)
    resp.raise_for_status()
    doc = resp.json()
    _DISCOVERY_CACHE[issuer] = (now + _DISCOVERY_TTL_SEC, doc)
    return doc


def _fetch_jwks_keys(jwks_uri: str) -> dict:
    """{ kid: jwk_dict }"""
    now = time.time()
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and cached[0] > now:
        return cached[1]
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(jwks_uri)
    resp.raise_for_status()
    doc = resp.json()
    keys_by_kid = {}
    for k in doc.get("keys") or []:
        kid = k.get("kid")
        if kid:
            keys_by_kid[kid] = k
    _JWKS_CACHE[jwks_uri] = (now + _JWKS_TTL_SEC, keys_by_kid)
    return keys_by_kid


def _peek_aud(token: str) -> str:
    """서명 검증 없이 payload.aud 만 추출 (trusted_audience 매칭용)."""
    try:
        decoded = jwt.decode(
            token, options={"verify_signature": False, "verify_exp": False}
        )
    except jwt.PyJWTError as e:
        raise ExternalTokenError(f"Malformed token: {e}") from e
    aud = decoded.get("aud")
    if isinstance(aud, list):
        # 배열이면 첫 값 반환 (실 검증은 아래 decode 가 리스트로 받아 통과 처리)
        return aud[0] if aud else ""
    return aud or ""


def _peek_iss(token: str) -> str:
    try:
        decoded = jwt.decode(
            token, options={"verify_signature": False, "verify_exp": False}
        )
    except jwt.PyJWTError as e:
        raise ExternalTokenError(f"Malformed token: {e}") from e
    return decoded.get("iss") or ""


def _peek_kid(token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise ExternalTokenError(f"Malformed token header: {e}") from e
    return header.get("kid") or ""


def _match_audience(aud_value: str, iss_value: str) -> Optional[TrustedAudienceModel]:
    """TrustedAudiences 중 `audience` 가 일치하고 issuer 허용 목록에 iss 가 포함되면
    그 row 반환. enabled 항목만 고려."""
    for row in TrustedAudiences.list_enabled():
        if row.audience != aud_value:
            continue
        allowed = _expected_issuers(row)
        iss_norm = (iss_value or "").rstrip("/")
        if any(iss_norm == e.rstrip("/") for e in allowed):
            return row
        # Entra v2 의 경우 token iss 가 `https://login.microsoftonline.com/<tenant>/v2.0`
        # 형태지만 row 의 tenant_id 가 비어있으면 common 허용으로 간주 — 모든 테넌트 통과.
        if row.idp_type == "entra" and not (row.tenant_id or "").strip():
            if iss_norm.startswith(
                "https://login.microsoftonline.com/"
            ) and iss_norm.endswith("/v2.0"):
                return row
    return None


def verify_external_id_token(token: str) -> tuple[dict, TrustedAudienceModel]:
    """전체 검증 수행. 성공 시 (claims, matched_audience_row) 반환.
    실패 시 ExternalTokenError."""
    if not token:
        raise ExternalTokenError("Empty token")

    aud_value = _peek_aud(token)
    iss_value = _peek_iss(token)
    if not aud_value or not iss_value:
        raise ExternalTokenError("Token missing aud/iss")

    matched = _match_audience(aud_value, iss_value)
    if matched is None:
        raise ExternalTokenError(
            f"Audience not trusted: aud={aud_value} iss={iss_value}"
        )

    # JWKS 기반 서명 검증
    kid = _peek_kid(token)
    if not kid:
        raise ExternalTokenError("Token missing kid in header")
    try:
        discovery = _fetch_discovery(iss_value.rstrip("/"))
    except Exception as e:
        raise ExternalTokenError(f"OIDC discovery failed for {iss_value}: {e}") from e
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        raise ExternalTokenError("OIDC discovery missing jwks_uri")

    keys = _fetch_jwks_keys(jwks_uri)
    jwk = keys.get(kid)
    if jwk is None:
        # JWKS 가 rotate 됐을 수 있음 — 강제 refresh 후 재시도
        _JWKS_CACHE.pop(jwks_uri, None)
        keys = _fetch_jwks_keys(jwks_uri)
        jwk = keys.get(kid)
    if jwk is None:
        raise ExternalTokenError(f"JWKS has no key for kid={kid}")

    try:
        public_key = RSAAlgorithm.from_jwk(jwk)
    except Exception as e:
        raise ExternalTokenError(f"Failed to parse JWK: {e}") from e

    try:
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=[jwk.get("alg") or "RS256"],
            audience=aud_value,  # decode 가 aud claim 검증
            issuer=iss_value,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise ExternalTokenError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise ExternalTokenError(f"Token invalid: {e}") from e

    return claims, matched


def extract_user_identity(
    claims: dict, audience: TrustedAudienceModel
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """claims → (oauth_oid, oauth_sub, email, name).
    Entra: oid 우선, 그 다음 sub. Google: sub.
    """
    oid = None
    sub = claims.get("sub")
    if audience.idp_type == "entra":
        oid = claims.get("oid") or None
    email = claims.get("email") or claims.get("preferred_username") or None
    name = claims.get("name") or None
    return oid, sub, email, name
