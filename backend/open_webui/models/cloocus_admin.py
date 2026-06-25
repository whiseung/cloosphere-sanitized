"""
Cloocus Admin Database Models

Cloocus 중앙 관리 DB 테이블 정의.
CloocusBase를 사용하여 앱 DB와 완전 분리.
"""

import time

from open_webui.internal.cloocus_db import CloocusBase
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    String,
    Text,
)


class CloocusCustomer(CloocusBase):
    """고객사 정보 테이블."""

    __tablename__ = "cloocus_customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    contact_name = Column(String(255), nullable=True)
    admin_contact_name = Column(String(255), nullable=True)
    sales_contact_name = Column(String(255), nullable=True)
    web_url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    credit = Column(Integer, default=0, nullable=False)
    approval_email = Column(String(255), nullable=True)
    email_channel = Column(String(100), nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)
    updated_at = Column(
        Integer,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    license_type = Column(String(20), nullable=True)  # "poc" or "contract"
    start_date = Column(Integer, nullable=True)  # Unix timestamp
    sr_key = Column(String(255), nullable=True, unique=True)


class CloocusLicenseRecord(CloocusBase):
    """발급된 라이선스 키 이력 테이블."""

    __tablename__ = "cloocus_license_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    tier = Column(String(50), nullable=False)
    max_users = Column(Integer, default=0, nullable=False)
    issued_at = Column(Integer, default=lambda: int(time.time()), nullable=False)
    expires_at = Column(Integer, nullable=True)
    # NOTE: License/feature/registry tokens stay as plaintext TEXT — they are
    # signed JWTs (RS256) whose authenticity is enforced by signature, not
    # confidentiality. Encrypting them in the central admin DB would block
    # operational support flows (re-display, re-issue, audit) without adding
    # real security since these tokens are also held by customer deployments
    # in plaintext.
    token = Column(Text, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)


class CloocusFeatureKeyRecord(CloocusBase):
    """발급된 피처 키 이력 테이블."""

    __tablename__ = "cloocus_feature_key_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    module = Column(String(100), nullable=False)
    issued_at = Column(Integer, default=lambda: int(time.time()), nullable=False)
    expires_at = Column(Integer, nullable=True)
    token = Column(Text, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)


class CloocusFeatureRegistry(CloocusBase):
    """기능 레지스트리 - 등록된 모듈 목록."""

    __tablename__ = "cloocus_feature_registry"

    module_id = Column(String(100), primary_key=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tier_minimum = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)


class CloocusRegistryToken(CloocusBase):
    """고객사별 컨테이너 레지스트리 토큰 테이블."""

    __tablename__ = "cloocus_registry_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    token_name = Column(String(255), nullable=False)
    token_key = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)
    updated_at = Column(
        Integer,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
        nullable=False,
    )


class CloocusWorkCategory(CloocusBase):
    """작업 카테고리 테이블."""

    __tablename__ = "cloocus_work_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)
    updated_at = Column(
        Integer,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
        nullable=False,
    )


class CloocusWorkLog(CloocusBase):
    """작업 내역 테이블."""

    __tablename__ = "cloocus_work_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False)
    category_id = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    work_hours = Column(Float, nullable=False)
    work_date = Column(Integer, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    approval_token = Column(String(255), nullable=True)
    approved_at = Column(Integer, nullable=True)
    reject_reason = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()), nullable=False)
    updated_at = Column(
        Integer,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
        nullable=False,
    )
