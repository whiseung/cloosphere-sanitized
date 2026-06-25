"""
JSON Organization Provider

JSON 데이터로 조직 구조를 직접 입력하는 Provider.
관리자가 수동으로 조직 구조를 설정할 때 사용.
"""

import logging
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS

from .base import OrganizationData, OrganizationProvider, OrgUnitData

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class JsonOrganizationProvider(OrganizationProvider):
    """
    JSON 데이터 기반 Organization Provider

    사용 예시:
    ```python
    provider = JsonOrganizationProvider(
        organization={
            "tenant_id": "my-company",
            "name": "My Company",
            "display_name": "My Company Inc.",
            "domain": "mycompany.com"
        },
        units=[
            {
                "id": "dept-1",
                "name": "Engineering",
                "type": "department",
                "children": [
                    {"id": "team-1", "name": "Backend Team", "type": "team"},
                    {"id": "team-2", "name": "Frontend Team", "type": "team"}
                ]
            },
            {
                "id": "dept-2",
                "name": "Sales",
                "type": "department"
            }
        ]
    )
    ```
    """

    provider_type: str = "json"

    def __init__(
        self,
        organization: Optional[dict] = None,
        units: Optional[list[dict]] = None,
        **kwargs,
    ):
        """
        Args:
            organization: 조직 정보 딕셔너리
            units: 조직 단위 리스트 (계층 구조 지원)
        """
        self.organization_data = organization or {}
        self.units_data = units or []

    def _parse_unit(self, data: dict, parent_id: Optional[str] = None) -> OrgUnitData:
        """딕셔너리를 OrgUnitData로 변환"""
        unit_id = data.get("id") or str(uuid.uuid4())
        children_data = data.get("children", [])

        children = [self._parse_unit(child, unit_id) for child in children_data]

        return OrgUnitData(
            id=unit_id,
            name=data.get("name", "Unnamed"),
            display_name=data.get("display_name"),
            description=data.get("description"),
            parent_id=parent_id,
            level=0,  # flatten_units에서 계산됨
            type=data.get("type"),
            external_id=data.get("external_id"),
            member_ids=data.get("member_ids", []),
            children=children,
            meta=data.get("meta", {}),
        )

    async def fetch_organization(self) -> Optional[OrganizationData]:
        """JSON 데이터에서 조직 정보 파싱"""
        if not self.organization_data:
            return None

        tenant_id = self.organization_data.get("tenant_id")
        if not tenant_id:
            log.warning("JSON organization data missing tenant_id")
            return None

        return OrganizationData(
            id=self.organization_data.get("id") or str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=self.organization_data.get("name", tenant_id),
            display_name=self.organization_data.get("display_name"),
            domain=self.organization_data.get("domain"),
            meta=self.organization_data.get("meta", {}),
        )

    async def fetch_organizational_units(
        self, organization_id: Optional[str] = None
    ) -> list[OrgUnitData]:
        """JSON 데이터에서 조직 단위 파싱 (계층 구조 유지)"""
        units = []
        for unit_data in self.units_data:
            units.append(self._parse_unit(unit_data))
        return units

    async def fetch_unit_members(self, unit_id: str) -> list[str]:
        """JSON 데이터에서 특정 단위의 멤버 ID 반환"""

        def find_unit(units_data: list[dict], target_id: str) -> Optional[dict]:
            for unit in units_data:
                if unit.get("id") == target_id or unit.get("external_id") == target_id:
                    return unit
                children = unit.get("children", [])
                if children:
                    found = find_unit(children, target_id)
                    if found:
                        return found
            return None

        unit = find_unit(self.units_data, unit_id)
        if unit:
            return unit.get("member_ids", [])
        return []

    @classmethod
    def from_json_string(cls, json_str: str) -> "JsonOrganizationProvider":
        """JSON 문자열에서 Provider 생성"""
        import json

        data = json.loads(json_str)
        return cls(
            organization=data.get("organization"),
            units=data.get("units", []),
        )

    @classmethod
    def from_file(cls, file_path: str) -> "JsonOrganizationProvider":
        """JSON 파일에서 Provider 생성"""
        import json

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            organization=data.get("organization"),
            units=data.get("units", []),
        )
