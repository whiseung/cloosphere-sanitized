"""
Organization Models

조직 및 조직 단위 관리를 위한 모델.
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Integer, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Organization DB Schema
####################


class Organization(Base):
    __tablename__ = "organization"

    id = Column(Text, unique=True, primary_key=True)
    tenant_id = Column(Text, unique=True, index=True)  # 외부 시스템의 테넌트 ID
    name = Column(Text)
    display_name = Column(Text, nullable=True)
    domain = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class OrganizationalUnit(Base):
    __tablename__ = "organizational_unit"

    id = Column(Text, unique=True, primary_key=True)
    organization_id = Column(Text, index=True)  # 소속 조직
    parent_id = Column(Text, nullable=True, index=True)  # 부모 단위 (계층 구조)
    name = Column(Text)
    display_name = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    level = Column(Integer, default=0)  # 계층 레벨 (0 = 최상위)
    type = Column(Text, nullable=True)  # department, team, group 등
    external_id = Column(Text, nullable=True, index=True)  # 외부 시스템 ID
    member_ids = Column(JSON, nullable=True)  # 멤버 사용자 ID 목록
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


####################
# Pydantic Models
####################


class OrganizationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    display_name: Optional[str] = None
    domain: Optional[str] = None
    meta: Optional[dict] = None
    created_at: int
    updated_at: int


class OrganizationalUnitModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    parent_id: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    level: int = 0
    type: Optional[str] = None
    external_id: Optional[str] = None
    member_ids: list[str] = []
    meta: Optional[dict] = None
    created_at: int
    updated_at: int


####################
# Forms
####################


class OrganizationForm(BaseModel):
    tenant_id: str
    name: str
    display_name: Optional[str] = None
    domain: Optional[str] = None
    meta: Optional[dict] = None


class OrganizationUpdateForm(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    domain: Optional[str] = None
    meta: Optional[dict] = None


class OrganizationalUnitForm(BaseModel):
    organization_id: str
    parent_id: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    level: int = 0
    type: Optional[str] = None
    external_id: Optional[str] = None
    member_ids: list[str] = []
    meta: Optional[dict] = None


class OrganizationalUnitUpdateForm(BaseModel):
    parent_id: Optional[str] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None
    type: Optional[str] = None
    member_ids: Optional[list[str]] = None
    meta: Optional[dict] = None


####################
# Organization Table Operations
####################


class OrganizationTable:
    def insert_new_organization(
        self, form_data: OrganizationForm
    ) -> Optional[OrganizationModel]:
        with get_db() as db:
            organization = OrganizationModel(
                **{
                    **form_data.model_dump(exclude_none=True),
                    "id": str(uuid.uuid4()),
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Organization(**organization.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return OrganizationModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting organization: {e}")
                return None

    def get_all_organizations(self) -> list[OrganizationModel]:
        with get_db() as db:
            return [
                OrganizationModel.model_validate(org)
                for org in db.query(Organization)
                .order_by(Organization.updated_at.desc())
                .all()
            ]

    def get_organization_by_id(self, id: str) -> Optional[OrganizationModel]:
        try:
            with get_db() as db:
                org = db.query(Organization).filter_by(id=id).first()
                return OrganizationModel.model_validate(org) if org else None
        except Exception:
            return None

    def get_organization_by_tenant_id(
        self, tenant_id: str
    ) -> Optional[OrganizationModel]:
        try:
            with get_db() as db:
                org = db.query(Organization).filter_by(tenant_id=tenant_id).first()
                return OrganizationModel.model_validate(org) if org else None
        except Exception:
            return None

    def update_organization_by_id(
        self, id: str, form_data: OrganizationUpdateForm
    ) -> Optional[OrganizationModel]:
        try:
            with get_db() as db:
                org = db.query(Organization).filter_by(id=id).first()
                if org:
                    for key, value in form_data.model_dump(exclude_none=True).items():
                        setattr(org, key, value)
                    org.updated_at = int(time.time())
                    db.commit()
                    db.refresh(org)
                    return OrganizationModel.model_validate(org)
                return None
        except Exception as e:
            log.exception(f"Error updating organization: {e}")
            return None

    def delete_organization_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                org = db.query(Organization).filter_by(id=id).first()
                if org:
                    # 하위 조직 단위 일괄 삭제
                    db.query(OrganizationalUnit).filter_by(organization_id=id).delete(
                        synchronize_session=False
                    )
                    db.delete(org)
                    db.commit()
                    return True
                return False
        except Exception:
            return False


####################
# OrganizationalUnit Table Operations
####################


class OrganizationalUnitTable:
    def insert_new_organizational_unit(
        self, form_data: OrganizationalUnitForm
    ) -> Optional[OrganizationalUnitModel]:
        with get_db() as db:
            unit = OrganizationalUnitModel(
                **{
                    **form_data.model_dump(exclude_none=True),
                    "id": str(uuid.uuid4()),
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = OrganizationalUnit(**unit.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return OrganizationalUnitModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting organizational unit: {e}")
                return None

    def get_all_organizational_units(self) -> list[OrganizationalUnitModel]:
        with get_db() as db:
            return [
                OrganizationalUnitModel.model_validate(unit)
                for unit in db.query(OrganizationalUnit)
                .order_by(OrganizationalUnit.level, OrganizationalUnit.name)
                .all()
            ]

    def get_organizational_units_by_organization_id(
        self, organization_id: str
    ) -> list[OrganizationalUnitModel]:
        with get_db() as db:
            return [
                OrganizationalUnitModel.model_validate(unit)
                for unit in db.query(OrganizationalUnit)
                .filter_by(organization_id=organization_id)
                .order_by(OrganizationalUnit.level, OrganizationalUnit.name)
                .all()
            ]

    def get_organizational_unit_by_id(
        self, id: str
    ) -> Optional[OrganizationalUnitModel]:
        try:
            with get_db() as db:
                unit = db.query(OrganizationalUnit).filter_by(id=id).first()
                return OrganizationalUnitModel.model_validate(unit) if unit else None
        except Exception:
            return None

    def get_organizational_unit_by_external_id(
        self, external_id: str
    ) -> Optional[OrganizationalUnitModel]:
        try:
            with get_db() as db:
                unit = (
                    db.query(OrganizationalUnit)
                    .filter_by(external_id=external_id)
                    .first()
                )
                return OrganizationalUnitModel.model_validate(unit) if unit else None
        except Exception:
            return None

    def update_organizational_unit_by_id(
        self, id: str, form_data: OrganizationalUnitUpdateForm
    ) -> Optional[OrganizationalUnitModel]:
        try:
            with get_db() as db:
                unit = db.query(OrganizationalUnit).filter_by(id=id).first()
                if unit:
                    for key, value in form_data.model_dump(exclude_none=True).items():
                        setattr(unit, key, value)
                    unit.updated_at = int(time.time())
                    db.commit()
                    db.refresh(unit)
                    return OrganizationalUnitModel.model_validate(unit)
                return None
        except Exception as e:
            log.exception(f"Error updating organizational unit: {e}")
            return None

    def delete_organizational_unit_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                ou = db.query(OrganizationalUnit).filter_by(id=id).first()
                if ou:
                    db.delete(ou)
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def delete_organizational_units_by_organization_id(
        self, organization_id: str
    ) -> bool:
        try:
            with get_db() as db:
                db.query(OrganizationalUnit).filter_by(
                    organization_id=organization_id
                ).delete()
                db.commit()
                return True
        except Exception:
            return False


# Singleton instances
Organizations = OrganizationTable()
OrganizationalUnits = OrganizationalUnitTable()
