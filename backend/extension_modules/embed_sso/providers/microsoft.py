"""Microsoft Entra ID (Azure AD) SSO provider.

Microsoft Entra ID는 표준 OIDC를 따르므로 `GenericOIDCProvider`를 거의
그대로 사용할 수 있다. 다만 두 가지 편의 기능이 있다:

- 테넌트 ID만 받아 issuer URL을 자동 생성
- access_token이 있을 때 Graph API `/me`를 호출해 부서/직책 등 추가 정보 수집
"""

from __future__ import annotations

import logging
from typing import Optional

from ..schemas import SSOExchangeRequest, SSOUserClaims
from .base import BaseSSOProvider
from .oidc import GenericOIDCProvider

log = logging.getLogger(__name__)

GRAPH_ME_URL = (
    "https://graph.microsoft.com/v1.0/me"
    "?$select=id,displayName,jobTitle,department,companyName,officeLocation,mail,userPrincipalName"
)


class MicrosoftSSOProvider(BaseSSOProvider):
    name = "microsoft"

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        trusted_audiences: Optional[list[str]] = None,
    ):
        # tenant_id가 주어지면 해당 테넌트만 신뢰. 'common'이면 다중 테넌트.
        if tenant_id:
            issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
            trusted_issuers = [issuer]
        else:
            trusted_issuers = []
        self._oidc = GenericOIDCProvider(
            trusted_issuers=trusted_issuers,
            trusted_audiences=trusted_audiences,
        )
        self._tenant_id = tenant_id

    async def verify(self, request: SSOExchangeRequest) -> SSOUserClaims:
        # issuer 힌트 자동 주입
        if request.id_token and not request.issuer and self._tenant_id:
            request = request.model_copy(
                update={
                    "issuer": f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"
                }
            )
        claims = await self._oidc.verify(request)

        # access_token이 있으면 Graph API에서 추가 정보 가져와 raw에 머지
        if request.access_token:
            try:
                graph_data = await self._http_get_json(
                    GRAPH_ME_URL,
                    headers={"Authorization": f"Bearer {request.access_token}"},
                )
                claims.raw["graph"] = graph_data
                # 우선순위: id_token name > graph displayName
                if not claims.name and graph_data.get("displayName"):
                    claims.name = graph_data["displayName"]
            except Exception as e:
                log.warning(f"Microsoft Graph /me call failed: {e}")

        return claims
