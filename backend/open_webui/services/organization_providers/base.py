"""
Organization Provider Base Class

모든 Organization Provider가 구현해야 하는 인터페이스 정의.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


@dataclass
class OrgUnitData:
    """조직 단위 데이터 (부서, 팀 등)"""

    id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[str] = None
    level: int = 0
    type: Optional[str] = None  # department, team, group 등
    external_id: Optional[str] = None  # 외부 시스템 ID
    member_ids: list[str] = field(default_factory=list)
    children: list["OrgUnitData"] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class OrganizationData:
    """조직 데이터 (회사/테넌트)"""

    id: str
    tenant_id: str
    name: str
    display_name: Optional[str] = None
    domain: Optional[str] = None
    units: list[OrgUnitData] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class OrganizationProvider(ABC):
    """
    Organization Provider 추상 클래스

    모든 Provider는 이 클래스를 상속받아 구현해야 함.
    """

    provider_type: str = "base"

    @abstractmethod
    async def fetch_organization(self) -> Optional[OrganizationData]:
        """
        조직 정보 가져오기

        Returns:
            OrganizationData 또는 None
        """
        pass

    @abstractmethod
    async def fetch_organizational_units(
        self, organization_id: Optional[str] = None
    ) -> list[OrgUnitData]:
        """
        조직 단위 목록 가져오기 (계층 구조 포함)

        Args:
            organization_id: 특정 조직의 단위만 가져올 경우

        Returns:
            OrgUnitData 리스트 (계층 구조는 children 필드에 포함)
        """
        pass

    @abstractmethod
    async def fetch_unit_members(self, unit_id: str) -> list[str]:
        """
        특정 조직 단위의 멤버 ID 목록 가져오기

        Args:
            unit_id: 조직 단위 ID

        Returns:
            사용자 ID 리스트
        """
        pass

    async def fetch_unit_members_with_detail(
        self, unit_id: str
    ) -> tuple[list[str], list[dict]]:
        """
        특정 조직 단위의 멤버 ID + 상세 정보 가져오기

        기본 구현: fetch_unit_members를 호출하여 ID만 반환 (detail은 빈 리스트).
        Provider가 상세 정보를 제공할 수 있는 경우 override.

        Returns:
            (member_ids, members_detail)
            members_detail 형식: [{"id", "name", "email", "job_title"}, ...]
        """
        member_ids = await self.fetch_unit_members(unit_id)
        return member_ids, []

    def flatten_units(
        self, units: list[OrgUnitData], parent_id: Optional[str] = None, level: int = 0
    ) -> list[OrgUnitData]:
        """
        계층 구조의 조직 단위를 평탄화 (DB 저장용)

        Args:
            units: 계층 구조의 OrgUnitData 리스트
            parent_id: 부모 ID
            level: 현재 레벨

        Returns:
            평탄화된 OrgUnitData 리스트
        """
        result = []
        for unit in units:
            unit.parent_id = parent_id
            unit.level = level
            # children은 별도로 처리하므로 복사본에서 제거
            children = unit.children
            unit.children = []
            result.append(unit)

            if children:
                result.extend(self.flatten_units(children, unit.id, level + 1))

        return result

    async def sync_to_db(self) -> dict:
        """
        Provider에서 데이터를 가져와 DB에 동기화

        Returns:
            동기화 결과 (created, updated, deleted 카운트)
        """
        from open_webui.models.organization import (
            OrganizationalUnitForm,
            OrganizationalUnitModel,
            OrganizationalUnits,
            OrganizationalUnitUpdateForm,
            OrganizationForm,
            Organizations,
        )

        result = {
            "organization": {"created": 0, "updated": 0},
            "units": {"created": 0, "updated": 0, "deleted": 0},
        }

        # 조직 정보 동기화
        org_data = await self.fetch_organization()
        if not org_data:
            log.warning("No organization data fetched from provider")
            return result

        existing_org = Organizations.get_organization_by_tenant_id(org_data.tenant_id)
        if existing_org:
            # 업데이트
            from open_webui.models.organization import OrganizationUpdateForm

            Organizations.update_organization_by_id(
                existing_org.id,
                OrganizationUpdateForm(
                    name=org_data.name,
                    display_name=org_data.display_name,
                    domain=org_data.domain,
                    meta=org_data.meta,
                ),
            )
            org_id = existing_org.id
            result["organization"]["updated"] = 1
        else:
            # 생성
            new_org = Organizations.insert_new_organization(
                OrganizationForm(
                    tenant_id=org_data.tenant_id,
                    name=org_data.name,
                    display_name=org_data.display_name,
                    domain=org_data.domain,
                    meta=org_data.meta,
                )
            )
            if new_org:
                org_id = new_org.id
                result["organization"]["created"] = 1
            else:
                log.error("Failed to create organization")
                return result

        # 조직 단위 동기화 (upsert — external_id 기준)
        units = await self.fetch_organizational_units(org_id)
        flat_units = self.flatten_units(units)

        # 기존 unit을 external_id로 인덱싱
        existing_units = (
            OrganizationalUnits.get_organizational_units_by_organization_id(org_id)
        )
        existing_by_ext_id: dict[str, OrganizationalUnitModel] = {
            u.external_id: u for u in existing_units if u.external_id
        }

        # original_id -> database_id 매핑 (parent_id 참조 해결용)
        id_mapping: dict[str, str] = {}
        seen_ext_ids: set[str] = set()

        # Phase 1: 모든 unit의 멤버를 병렬로 fetch (Provider 자체 semaphore로 동시성 제어)
        async def _populate_members(unit: OrgUnitData) -> None:
            ext_id = unit.external_id or unit.id
            if unit.member_ids or not ext_id:
                return
            try:
                (
                    member_ids,
                    members_detail,
                ) = await self.fetch_unit_members_with_detail(ext_id)
                unit.member_ids = member_ids
                if members_detail:
                    if unit.meta is None:
                        unit.meta = {}
                    unit.meta["members"] = members_detail
                    unit.meta["member_count"] = len(members_detail)
            except Exception as e:
                log.warning(f"Failed to fetch members for unit {unit.id}: {e}")

        await asyncio.gather(*(_populate_members(u) for u in flat_units))

        # Phase 2: DB upsert (parent_id 의존성 때문에 순차 처리 필요)
        for unit in flat_units:
            ext_id = unit.external_id or unit.id

            # parent_id를 실제 DB id로 변환
            db_parent_id = None
            if unit.parent_id:
                db_parent_id = id_mapping.get(unit.parent_id)
                if not db_parent_id:
                    log.warning(f"Parent {unit.parent_id} not found for unit {unit.id}")

            seen_ext_ids.add(ext_id)
            existing = existing_by_ext_id.get(ext_id)

            if existing:
                # 기존 unit 업데이트 (ID 유지)
                OrganizationalUnits.update_organizational_unit_by_id(
                    existing.id,
                    OrganizationalUnitUpdateForm(
                        parent_id=db_parent_id,
                        name=unit.name,
                        display_name=unit.display_name,
                        description=unit.description,
                        level=unit.level,
                        type=unit.type,
                        member_ids=unit.member_ids,
                        meta=unit.meta,
                    ),
                )
                id_mapping[unit.id] = existing.id
                result["units"]["updated"] += 1
            else:
                # 신규 unit 생성
                new_unit = OrganizationalUnits.insert_new_organizational_unit(
                    OrganizationalUnitForm(
                        organization_id=org_id,
                        parent_id=db_parent_id,
                        name=unit.name,
                        display_name=unit.display_name,
                        description=unit.description,
                        level=unit.level,
                        type=unit.type,
                        external_id=ext_id,
                        member_ids=unit.member_ids,
                        meta=unit.meta,
                    )
                )
                if new_unit:
                    id_mapping[unit.id] = new_unit.id
                    result["units"]["created"] += 1

        # 이번에 동기화한 type 범위 내에서만 삭제 (OU만 동기화 시 Groups는 보존)
        # 빈 응답(synced_types=set())으로 전체 삭제되는 것을 방지하기 위해
        # synced_types가 비어있거나 type 일치 안 하면 삭제 건너뜀
        synced_types = {u.type for u in flat_units if u.type}
        for ext_id, existing in existing_by_ext_id.items():
            if ext_id in seen_ext_ids:
                continue
            if not synced_types or existing.type not in synced_types:
                continue
            OrganizationalUnits.delete_organizational_unit_by_id(existing.id)
            result["units"]["deleted"] += 1

        log.info(
            f"Sync completed: created {result['units']['created']}, "
            f"updated {result['units']['updated']}, "
            f"deleted {result['units']['deleted']} units"
        )
        return result
