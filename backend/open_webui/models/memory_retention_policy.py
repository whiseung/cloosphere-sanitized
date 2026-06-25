"""Memory retention policy — class-based TTL configuration."""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, UniqueConstraint

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# Default retention policies
RETENTION_DEFAULTS = {
    "temporary": {"ttl_days": 30, "on_expire": "soft_delete"},
    "standard": {"ttl_days": 180, "on_expire": "soft_delete"},
    "permanent": {"ttl_days": None, "on_expire": "soft_delete"},
}

# Source → retention_class mapping
SOURCE_RETENTION_MAP = {
    "auto": "temporary",
    "manual": "standard",
    "profile": "permanent",
}


class MemoryRetentionPolicy(Base):
    __tablename__ = "memory_retention_policy"

    id = Column(String, primary_key=True)
    retention_class = Column(String, nullable=False)
    ttl_days = Column(BigInteger, nullable=True)  # null = indefinite
    on_expire = Column(String, nullable=False, server_default="soft_delete")
    org_id = Column(String, nullable=True)  # Phase 5
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("retention_class", "org_id", name="uq_retention_class_org"),
    )


class MemoryRetentionPolicyModel(BaseModel):
    id: str
    retention_class: str
    ttl_days: Optional[int] = None
    on_expire: str = "soft_delete"
    org_id: Optional[str] = None
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class MemoryRetentionPolicyTable:
    def get_policy(self, retention_class: str) -> Optional[MemoryRetentionPolicyModel]:
        with get_db() as db:
            try:
                policy = (
                    db.query(MemoryRetentionPolicy)
                    .filter_by(retention_class=retention_class, org_id=None)
                    .first()
                )
                return (
                    MemoryRetentionPolicyModel.model_validate(policy)
                    if policy
                    else None
                )
            except Exception:
                return None

    def get_all_policies(self) -> list[MemoryRetentionPolicyModel]:
        with get_db() as db:
            try:
                policies = db.query(MemoryRetentionPolicy).filter_by(org_id=None).all()
                return [MemoryRetentionPolicyModel.model_validate(p) for p in policies]
            except Exception:
                return []

    def update_policy(
        self, id: str, ttl_days: Optional[int]
    ) -> Optional[MemoryRetentionPolicyModel]:
        with get_db() as db:
            try:
                policy = db.query(MemoryRetentionPolicy).filter_by(id=id).first()
                if not policy:
                    return None
                if policy.retention_class == "permanent":
                    return MemoryRetentionPolicyModel.model_validate(policy)
                policy.ttl_days = ttl_days
                policy.updated_at = int(time.time())
                db.commit()
                db.refresh(policy)
                return MemoryRetentionPolicyModel.model_validate(policy)
            except Exception:
                return None

    def seed_defaults(self) -> None:
        """Insert default retention policies if not present."""
        with get_db() as db:
            try:
                existing = (
                    db.query(MemoryRetentionPolicy).filter_by(org_id=None).count()
                )
                if existing > 0:
                    return

                now = int(time.time())
                for cls_name, config in RETENTION_DEFAULTS.items():
                    policy = MemoryRetentionPolicy(
                        id=str(uuid.uuid4()),
                        retention_class=cls_name,
                        ttl_days=config["ttl_days"],
                        on_expire=config["on_expire"],
                        org_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(policy)
                db.commit()
                log.info("[RetentionPolicy] Seeded default policies")
            except Exception as e:
                log.warning(f"[RetentionPolicy] Seed failed: {e}")


RetentionPolicies = MemoryRetentionPolicyTable()
