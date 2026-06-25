"""
Trusted Audiences — 외부 IDP(Entra / Google) ID 토큰 passthrough 인증용.

고객사 앱이 자기네 Entra/Google OAuth 로 받은 ID 토큰을 `Authorization: Bearer`
헤더로 Cloosphere API 에 그대로 전달하면, 우리는 이 audience 테이블에 등록된 항목과
`iss`/`aud` 매칭 + JWKS 서명 검증 후 `oauth_oid`/`oauth_sub`/`email` 로 Cloosphere
사용자에 매핑한다.

관리자가 신뢰할 audience 를 명시적으로 등록해야 외부 토큰이 받아들여진다.
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, BigInteger, Boolean, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# DB Schema
####################


class TrustedAudience(Base):
    __tablename__ = "trusted_audience"

    id = Column(Text, unique=True, primary_key=True)
    idp_type = Column(Text, nullable=False)  # "entra" | "google"
    audience = Column(Text, nullable=False, index=True)  # aud 값 (app_id / client_id)
    tenant_id = Column(Text, nullable=True)  # Entra 전용; 빈 값이면 아무 tenant 허용
    issuer = Column(Text, nullable=True)  # 명시적 iss override; 빈 값이면 자동 계산
    name = Column(Text, nullable=True)  # 관리자 식별용 label
    enabled = Column(Boolean, default=True)
    auto_provision = Column(Boolean, default=False)
    default_role = Column(Text, default="user")  # auto_provision 시 부여 role
    default_group_ids = Column(
        JSON, nullable=True
    )  # auto_provision 시 소속 group id 목록
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


####################
# Pydantic
####################


class TrustedAudienceModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idp_type: str
    audience: str
    tenant_id: Optional[str] = None
    issuer: Optional[str] = None
    name: Optional[str] = None
    enabled: bool = True
    auto_provision: bool = False
    default_role: str = "user"
    default_group_ids: Optional[list[str]] = None
    meta: Optional[dict] = None
    created_at: int
    updated_at: int


class TrustedAudienceForm(BaseModel):
    idp_type: str = Field(..., pattern="^(entra|google)$")
    audience: str
    tenant_id: Optional[str] = ""
    issuer: Optional[str] = ""
    name: Optional[str] = ""
    enabled: bool = True
    auto_provision: bool = False
    default_role: str = "user"
    default_group_ids: Optional[list[str]] = None


####################
# CRUD
####################


class TrustedAudiencesTable:
    def list_all(self) -> list[TrustedAudienceModel]:
        with get_db() as db:
            rows = (
                db.query(TrustedAudience)
                .order_by(TrustedAudience.updated_at.desc())
                .all()
            )
            return [TrustedAudienceModel.model_validate(r) for r in rows]

    def list_enabled(self) -> list[TrustedAudienceModel]:
        """토큰 검증 hot-path 용. enabled 만 반환."""
        with get_db() as db:
            rows = (
                db.query(TrustedAudience)
                .filter(TrustedAudience.enabled.is_(True))
                .all()
            )
            return [TrustedAudienceModel.model_validate(r) for r in rows]

    def get_by_id(self, id: str) -> Optional[TrustedAudienceModel]:
        with get_db() as db:
            row = db.query(TrustedAudience).filter(TrustedAudience.id == id).first()
            return TrustedAudienceModel.model_validate(row) if row else None

    def insert(self, form: TrustedAudienceForm) -> Optional[TrustedAudienceModel]:
        with get_db() as db:
            now = int(time.time())
            row = TrustedAudience(
                id=str(uuid.uuid4()),
                idp_type=form.idp_type,
                audience=form.audience.strip(),
                tenant_id=(form.tenant_id or "").strip() or None,
                issuer=(form.issuer or "").strip() or None,
                name=(form.name or "").strip() or None,
                enabled=bool(form.enabled),
                auto_provision=bool(form.auto_provision),
                default_role=form.default_role or "user",
                default_group_ids=form.default_group_ids or None,
                meta=None,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return TrustedAudienceModel.model_validate(row)

    def update(
        self, id: str, form: TrustedAudienceForm
    ) -> Optional[TrustedAudienceModel]:
        with get_db() as db:
            row = db.query(TrustedAudience).filter(TrustedAudience.id == id).first()
            if not row:
                return None
            row.idp_type = form.idp_type
            row.audience = form.audience.strip()
            row.tenant_id = (form.tenant_id or "").strip() or None
            row.issuer = (form.issuer or "").strip() or None
            row.name = (form.name or "").strip() or None
            row.enabled = bool(form.enabled)
            row.auto_provision = bool(form.auto_provision)
            row.default_role = form.default_role or "user"
            row.default_group_ids = form.default_group_ids or None
            row.updated_at = int(time.time())
            db.commit()
            db.refresh(row)
            return TrustedAudienceModel.model_validate(row)

    def delete(self, id: str) -> bool:
        with get_db() as db:
            row = db.query(TrustedAudience).filter(TrustedAudience.id == id).first()
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True


TrustedAudiences = TrustedAudiencesTable()
