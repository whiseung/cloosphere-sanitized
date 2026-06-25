"""Pydantic schemas for SSO token exchange."""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SSOExchangeRequest(BaseModel):
    """호스트 사이트가 위젯에 넘겨주는 SSO 토큰.

    `id_token`과 `access_token` 둘 중 하나는 필수.
    `id_token`이 있으면 JWKS로 서명 검증, 없으면 access_token으로 userinfo
    엔드포인트를 호출한다.
    """

    provider: str  # "microsoft" | "google" | "github" | "oidc"
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    # OIDC 전용: discovery URL을 위젯 config가 아닌 호출 시점에 전달하고 싶을 때
    issuer: Optional[str] = None


class SSOUserClaims(BaseModel):
    """Provider 별 검증 결과를 정규화한 사용자 클레임."""

    model_config = ConfigDict(extra="allow")

    sub: str  # provider 내부 고유 ID
    email: str
    email_verified: bool = False
    name: Optional[str] = None
    picture: Optional[str] = None
    # 원본 클레임 보관 (organization 매칭 등에 사용)
    raw: dict[str, Any] = {}
