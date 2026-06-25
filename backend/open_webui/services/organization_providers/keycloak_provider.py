"""
Keycloak Organization Provider

Keycloak Admin REST API에서 조직 구조를 가져오는 Provider.

지원하는 동기화 소스:
1. Groups: Keycloak 그룹 계층 구조 → 조직 단위 (기본)
2. Organizations: Keycloak 26+ Organizations 기능 (선택)

필요한 설정:
- server_url: Keycloak 서버 URL (e.g., http://localhost:8180)
- realm: Realm 이름
- admin_token 또는 client_credentials: 인증 정보
"""

import logging
from typing import Optional

import aiohttp

from open_webui.env import SRC_LOG_LEVELS

from .base import OrganizationData, OrganizationProvider, OrgUnitData

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class KeycloakOrganizationProvider(OrganizationProvider):
    """
    Keycloak Admin REST API 기반 Organization Provider

    사용 예시:
    ```python
    provider = await KeycloakOrganizationProvider.from_client_credentials(
        server_url="http://localhost:8180",
        realm="cloosphere",
        client_id="admin-cli",
        client_secret="...",
    )
    await provider.sync_to_db()
    ```
    """

    provider_type: str = "keycloak"

    def __init__(
        self,
        server_url: str,
        realm: str,
        admin_token: str,
        use_groups: bool = True,
        use_organizations: bool = False,
        group_filter: Optional[str] = None,
        **kwargs,
    ):
        self.server_url = server_url.rstrip("/")
        self.realm = realm
        self.admin_token = admin_token
        self.use_groups = use_groups
        self.use_organizations = use_organizations
        self.group_filter = group_filter

        self._admin_base = f"{self.server_url}/admin/realms/{self.realm}"
        self._headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        }

    async def _api_request(
        self, endpoint: str, params: Optional[dict] = None
    ) -> Optional[dict | list]:
        """Keycloak Admin REST API 요청"""
        url = f"{self._admin_base}{endpoint}"
        log.info(f"Keycloak API request: {url}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers, params=params
                ) as resp:
                    if resp.ok:
                        return await resp.json()
                    else:
                        error_text = await resp.text()
                        log.error(f"Keycloak API error: {resp.status} - {error_text}")
                        return None
        except Exception as e:
            log.error(f"Keycloak API request failed: {e}")
            return None

    async def fetch_organization(self) -> Optional[OrganizationData]:
        """Keycloak Realm 정보를 조직으로 변환"""
        realm_info = await self._api_request("")
        if not realm_info:
            return None

        return OrganizationData(
            id=realm_info.get("id", self.realm),
            tenant_id=self.realm,
            name=realm_info.get("displayName") or self.realm,
            display_name=realm_info.get("displayName"),
            domain=None,
            meta={
                "source": "keycloak",
                "realm": self.realm,
                "server_url": self.server_url,
            },
        )

    async def fetch_organizational_units(
        self, organization_id: Optional[str] = None
    ) -> list[OrgUnitData]:
        """Keycloak에서 조직 단위 가져오기"""
        units = []

        if self.use_groups:
            groups = await self._fetch_groups()
            units.extend(groups)

        if self.use_organizations:
            orgs = await self._fetch_organizations()
            units.extend(orgs)

        return units

    async def _fetch_groups(self) -> list[OrgUnitData]:
        """
        Keycloak 그룹 계층 구조를 조직 단위로 변환

        Keycloak 26+에서는 subGroups가 자동 포함되지 않으므로
        /children 엔드포인트로 하위 그룹을 재귀 조회.
        """
        params = {"briefRepresentation": "false"}
        if self.group_filter:
            params["search"] = self.group_filter

        groups = await self._api_request("/groups", params=params)
        if not groups:
            return []

        return await self._build_group_tree(groups)

    async def _build_group_tree(self, groups: list[dict]) -> list[OrgUnitData]:
        """Keycloak 그룹 트리를 재귀적으로 빌드 (children API 사용)"""
        units = []

        for group in groups:
            group_id = group.get("id")

            # subGroups가 비어있으면 children API로 조회
            sub_groups = group.get("subGroups", [])
            if not sub_groups:
                sub_groups = (
                    await self._api_request(f"/groups/{group_id}/children") or []
                )

            children = await self._build_group_tree(sub_groups) if sub_groups else []

            units.append(
                OrgUnitData(
                    id=group_id,
                    name=group.get("name", "Unnamed"),
                    display_name=group.get("name"),
                    type="group",
                    external_id=group_id,
                    children=children,
                    meta={
                        "source": "keycloak_group",
                        "path": group.get("path", ""),
                        "attributes": group.get("attributes", {}),
                    },
                )
            )

        return units

    async def _fetch_organizations(self) -> list[OrgUnitData]:
        """
        Keycloak 26+ Organizations 기능 사용

        Organizations API: /admin/realms/{realm}/organizations
        """
        orgs = await self._api_request("/organizations")
        if not orgs:
            log.info("No Keycloak organizations found (feature may not be enabled)")
            return []

        units = []
        for org in orgs:
            org_id = org.get("id")

            # 조직 멤버 가져오기
            members = await self._api_request(f"/organizations/{org_id}/members")
            member_ids = self._extract_member_ids(members or [])

            units.append(
                OrgUnitData(
                    id=org_id,
                    name=org.get("name", "Unnamed"),
                    display_name=org.get("name"),
                    description=org.get("description"),
                    type="organization",
                    external_id=org_id,
                    member_ids=member_ids,
                    meta={
                        "source": "keycloak_organization",
                        "domains": org.get("domains", []),
                        "attributes": org.get("attributes", {}),
                    },
                )
            )

        return units

    def _extract_member_ids(self, members: list[dict]) -> list[str]:
        """멤버를 Cloosphere가 매칭할 수 있는 ID로 변환.

        oauth.py의 update_user_org_units는 oauth_sub, email 등으로 매칭하므로
        이메일을 우선 사용하고, 없으면 oauth_sub 형식(oidc@{keycloak_id})으로 저장.
        """
        ids = []
        for m in members:
            email = m.get("email")
            if email:
                ids.append(email)
            else:
                kc_id = m.get("id")
                if kc_id:
                    ids.append(f"oidc@{kc_id}")
        return ids

    async def fetch_unit_members(self, unit_id: str) -> list[str]:
        """그룹 또는 조직의 멤버 ID 목록"""
        # 그룹 멤버 시도
        members = await self._api_request(f"/groups/{unit_id}/members")
        if members:
            return self._extract_member_ids(members)

        # Organizations 멤버 시도
        members = await self._api_request(f"/organizations/{unit_id}/members")
        if members:
            return self._extract_member_ids(members)

        return []

    @classmethod
    async def from_client_credentials(
        cls,
        server_url: str,
        realm: str,
        client_id: str = "admin-cli",
        client_secret: Optional[str] = None,
        admin_username: Optional[str] = None,
        admin_password: Optional[str] = None,
        **kwargs,
    ) -> "KeycloakOrganizationProvider":
        """
        클라이언트 자격 증명 또는 관리자 계정으로 Provider 생성

        client_secret이 있으면 client_credentials grant,
        없으면 admin_username/password로 password grant.
        """
        token_url = f"{server_url}/realms/{realm}/protocol/openid-connect/token"

        if client_secret:
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        elif admin_username and admin_password:
            data = {
                "grant_type": "password",
                "client_id": client_id,
                "username": admin_username,
                "password": admin_password,
            }
        else:
            raise ValueError(
                "Either client_secret or admin_username/admin_password required"
            )

        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=data) as resp:
                if resp.ok:
                    token_data = await resp.json()
                    admin_token = token_data.get("access_token")
                    return cls(
                        server_url=server_url,
                        realm=realm,
                        admin_token=admin_token,
                        **kwargs,
                    )
                else:
                    error = await resp.text()
                    raise Exception(f"Failed to get Keycloak admin token: {error}")
