"""
Microsoft Graph Organization Provider

Microsoft Entra ID (Azure AD)에서 조직 구조를 가져오는 Provider.

필요한 MS Graph 권한:
- Organization.Read.All: 조직 정보 읽기
- Directory.Read.All: 디렉터리 정보 (Administrative Units, 그룹) 읽기
- User.Read.All: 사용자 정보 읽기 (멤버 목록용)
- GroupMember.Read.All: 그룹 멤버 읽기

계층 구조 가져오기 전략:
1. Administrative Units 사용 (권장) - 조직 계층 구조를 명시적으로 정의
2. 그룹 계층 사용 - 그룹의 memberOf 관계로 계층 구성
3. 부서(department) 기반 - 사용자의 department 필드로 계층 추론
"""

import logging
from typing import Optional

import aiohttp

from open_webui.env import SRC_LOG_LEVELS

from .base import OrganizationData, OrganizationProvider, OrgUnitData

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_API_BETA = "https://graph.microsoft.com/beta"


class MSGraphOrganizationProvider(OrganizationProvider):
    """
    Microsoft Graph API 기반 Organization Provider

    사용 예시:
    ```python
    provider = MSGraphOrganizationProvider(
        access_token="eyJ0eXAi...",
        use_admin_units=True,  # Administrative Units 사용
        use_groups=True,       # 그룹도 가져올지
        group_filter="startswith(displayName, 'Dept-')"  # 특정 그룹만
    )
    await provider.sync_to_db()
    ```
    """

    provider_type: str = "msgraph"

    def __init__(
        self,
        access_token: str,
        use_admin_units: bool = True,
        use_groups: bool = False,
        use_departments: bool = False,
        group_filter: Optional[str] = None,
        include_nested_groups: bool = True,
        **kwargs,
    ):
        """
        Args:
            access_token: MS Graph API 액세스 토큰
            use_admin_units: Administrative Units 사용 여부
            use_groups: 그룹을 조직 단위로 사용할지
            use_departments: 사용자 department 필드 기반 구조 생성
            group_filter: 그룹 필터 (OData $filter)
            include_nested_groups: 중첩 그룹 포함 여부
        """
        self.access_token = access_token
        self.use_admin_units = use_admin_units
        self.use_groups = use_groups
        self.use_departments = use_departments
        self.group_filter = group_filter
        self.include_nested_groups = include_nested_groups

        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    async def _graph_request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        use_beta: bool = False,
    ) -> Optional[dict]:
        """MS Graph API 요청"""
        base_url = GRAPH_API_BETA if use_beta else GRAPH_API_BASE
        url = f"{base_url}{endpoint}"

        log.info(f"MS Graph API request: {url} params={params}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers, params=params
                ) as resp:
                    if resp.ok:
                        data = await resp.json()
                        log.info(
                            f"MS Graph API response: {len(data.get('value', []))} items"
                        )
                        return data
                    else:
                        error_text = await resp.text()
                        log.error(f"MS Graph API error: {resp.status} - {error_text}")
                        return None
        except Exception as e:
            log.error(f"MS Graph API request failed: {e}")
            return None

    async def _get_all_pages(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        use_beta: bool = False,
    ) -> list[dict]:
        """페이지네이션 처리하여 모든 결과 가져오기"""
        results = []
        next_link = None

        while True:
            if next_link:
                # @odata.nextLink는 전체 URL
                async with aiohttp.ClientSession() as session:
                    async with session.get(next_link, headers=self._headers) as resp:
                        if resp.ok:
                            data = await resp.json()
                        else:
                            break
            else:
                data = await self._graph_request(endpoint, params, use_beta)

            if not data:
                break

            results.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")

            if not next_link:
                break

        return results

    async def fetch_organization(self) -> Optional[OrganizationData]:
        """MS Graph에서 조직 정보 가져오기"""
        log.info("Fetching organization from MS Graph...")
        data = await self._graph_request("/organization")
        if not data or not data.get("value"):
            log.warning("No organization data returned from MS Graph")
            return None
        log.info(f"Organization fetched: {data['value'][0].get('displayName')}")

        org = data["value"][0]  # 보통 하나의 조직만 있음

        # 검증된 도메인 중 기본 도메인 찾기
        verified_domains = org.get("verifiedDomains", [])
        primary_domain = None
        for domain in verified_domains:
            if domain.get("isDefault"):
                primary_domain = domain.get("name")
                break

        return OrganizationData(
            id=org.get("id"),
            tenant_id=org.get("id"),  # Azure에서는 org ID가 tenant ID
            name=org.get("displayName", "Unknown"),
            display_name=org.get("displayName"),
            domain=primary_domain,
            meta={
                "verified_domains": [d.get("name") for d in verified_domains],
                "country": org.get("countryLetterCode"),
                "created_datetime": org.get("createdDateTime"),
                "tenant_type": org.get("tenantType"),
            },
        )

    async def fetch_organizational_units(
        self, organization_id: Optional[str] = None
    ) -> list[OrgUnitData]:
        """
        MS Graph에서 조직 단위 가져오기

        우선순위:
        1. Administrative Units (use_admin_units=True)
        2. Groups (use_groups=True)
        3. Departments (use_departments=True)
        """
        units = []
        log.info(
            f"Fetching organizational units: admin_units={self.use_admin_units}, groups={self.use_groups}, departments={self.use_departments}"
        )

        if self.use_admin_units:
            admin_units = await self._fetch_administrative_units()
            log.info(f"Fetched {len(admin_units)} administrative units")
            units.extend(admin_units)

        if self.use_groups:
            groups = await self._fetch_groups()
            log.info(f"Fetched {len(groups)} groups")
            units.extend(groups)

        if self.use_departments:
            dept_units = await self._fetch_department_structure()
            log.info(f"Fetched {len(dept_units)} departments")
            units.extend(dept_units)

        log.info(f"Total units fetched: {len(units)}")
        return units

    async def _fetch_administrative_units(self) -> list[OrgUnitData]:
        """
        Administrative Units 가져오기

        Administrative Units는 Azure AD에서 조직 구조를 명시적으로 정의하는 방법.
        현재 MS Graph v1.0에서는 계층 구조를 직접 지원하지 않음.
        Beta API에서 일부 지원.
        """
        units = []

        # Administrative Units 목록 가져오기
        admin_units = await self._get_all_pages(
            "/directory/administrativeUnits",
            params={"$select": "id,displayName,description,membershipType"},
        )

        for au in admin_units:
            units.append(
                OrgUnitData(
                    id=au.get("id"),
                    name=au.get("displayName", "Unnamed"),
                    display_name=au.get("displayName"),
                    description=au.get("description"),
                    type="administrative_unit",
                    external_id=au.get("id"),
                    meta={
                        "membership_type": au.get("membershipType"),
                        "source": "msgraph_admin_unit",
                    },
                )
            )

        return units

    async def _fetch_groups(self) -> list[OrgUnitData]:
        """
        그룹을 조직 단위로 가져오기

        그룹 계층 구조:
        - memberOf 관계를 통해 부모-자식 관계 파악
        - 그룹이 다른 그룹의 멤버인 경우 중첩 구조
        """
        units = []
        group_hierarchy = {}  # id -> parent_ids

        # 그룹 목록 가져오기
        params = {
            "$select": "id,displayName,description,groupTypes,membershipRule",
        }
        if self.group_filter:
            params["$filter"] = self.group_filter

        groups = await self._get_all_pages("/groups", params=params)

        for group in groups:
            group_id = group.get("id")

            # 부모 그룹 찾기 (이 그룹이 멤버인 다른 그룹들)
            if self.include_nested_groups:
                parent_groups = await self._get_all_pages(
                    f"/groups/{group_id}/memberOf",
                    params={"$select": "id"},
                )
                parent_ids = [
                    p.get("id")
                    for p in parent_groups
                    if p.get("@odata.type") == "#microsoft.graph.group"
                ]
                group_hierarchy[group_id] = parent_ids

            group_types = group.get("groupTypes", [])
            group_type = "security_group"
            if "Unified" in group_types:
                group_type = "microsoft_365_group"
            elif "DynamicMembership" in group_types:
                group_type = "dynamic_group"

            units.append(
                OrgUnitData(
                    id=group_id,
                    name=group.get("displayName", "Unnamed"),
                    display_name=group.get("displayName"),
                    description=group.get("description"),
                    type=group_type,
                    external_id=group_id,
                    meta={
                        "group_types": group_types,
                        "membership_rule": group.get("membershipRule"),
                        "source": "msgraph_group",
                    },
                )
            )

        # 계층 구조 적용 (가장 적은 부모를 가진 것이 상위)
        if self.include_nested_groups and group_hierarchy:
            for unit in units:
                parent_ids = group_hierarchy.get(unit.id, [])
                if parent_ids:
                    # 첫 번째 부모만 사용 (다중 상속 미지원)
                    unit.parent_id = parent_ids[0]

        return units

    async def _fetch_department_structure(self) -> list[OrgUnitData]:
        """
        사용자의 department 필드 기반으로 조직 구조 생성

        사용자 정보에서 department, jobTitle 등을 수집하여
        고유한 부서 목록을 조직 단위로 변환.
        """
        units = []
        departments = {}  # name -> {"member_ids": [], "members": []}

        # 모든 사용자의 부서 정보 가져오기 (이름, 이메일 포함)
        users = await self._get_all_pages(
            "/users",
            params={
                "$select": "id,displayName,mail,userPrincipalName,department,jobTitle,companyName"
            },
        )

        for user in users:
            dept_name = user.get("department")
            if dept_name:
                if dept_name not in departments:
                    departments[dept_name] = {"member_ids": [], "members": []}

                user_id = user.get("id")
                departments[dept_name]["member_ids"].append(user_id)
                departments[dept_name]["members"].append(
                    {
                        "id": user_id,
                        "name": user.get("displayName", ""),
                        "email": user.get("mail") or user.get("userPrincipalName", ""),
                        "job_title": user.get("jobTitle", ""),
                    }
                )

        # 부서를 조직 단위로 변환
        for dept_name, dept_data in departments.items():
            units.append(
                OrgUnitData(
                    id=f"dept-{dept_name.lower().replace(' ', '-')}",
                    name=dept_name,
                    display_name=dept_name,
                    type="department",
                    external_id=f"dept:{dept_name}",
                    member_ids=dept_data["member_ids"],
                    meta={
                        "source": "msgraph_department",
                        "member_count": len(dept_data["member_ids"]),
                        "members": dept_data["members"],  # 멤버 상세 정보 저장
                    },
                )
            )

        return units

    async def fetch_unit_members(self, unit_id: str) -> list[str]:
        """특정 조직 단위의 멤버 ID 목록 가져오기"""
        member_ids = []

        # Administrative Unit 멤버
        members = await self._get_all_pages(
            f"/directory/administrativeUnits/{unit_id}/members",
            params={"$select": "id"},
        )

        if not members:
            # 그룹 멤버로 시도
            members = await self._get_all_pages(
                f"/groups/{unit_id}/members",
                params={"$select": "id"},
            )

        for member in members:
            # 사용자만 포함 (그룹, 서비스 프린시펄 제외)
            if member.get("@odata.type") == "#microsoft.graph.user":
                member_ids.append(member.get("id"))

        return member_ids

    @classmethod
    async def from_client_credentials(
        cls,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        **kwargs,
    ) -> "MSGraphOrganizationProvider":
        """
        클라이언트 자격 증명으로 Provider 생성 (앱 전용 인증)

        백그라운드 동기화에 사용.
        """
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        log.info(
            f"Getting access token from {token_url} for client_id={client_id[:8]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            ) as resp:
                if resp.ok:
                    token_data = await resp.json()
                    access_token = token_data.get("access_token")
                    log.info("Access token obtained successfully")
                    return cls(access_token=access_token, **kwargs)
                else:
                    error = await resp.text()
                    log.error(f"Failed to get access token: {error}")
                    raise Exception(f"Failed to get access token: {error}")
