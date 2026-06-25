import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text

####################
# Memory DB Schema
####################


class Memory(Base):
    __tablename__ = "memory"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    content = Column(Text)
    source = Column(String, default="manual")  # "manual" or "auto"
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)
    # Phase 4: governance
    scope = Column(String, server_default="user")
    org_id = Column(String, nullable=True)
    retention_class = Column(String, server_default="standard")
    deleted_at = Column(BigInteger, nullable=True)


class MemoryModel(BaseModel):
    id: str
    user_id: str
    content: str
    source: str = "manual"  # "manual" or "auto"
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch
    # Phase 4: governance
    scope: str = "user"
    org_id: Optional[str] = None
    retention_class: str = "standard"
    deleted_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class MemoriesTable:
    def insert_new_memory(
        self,
        user_id: str,
        content: str,
        source: str = "manual",
        retention_class: Optional[str] = None,
    ) -> Optional[MemoryModel]:
        from open_webui.models.memory_retention_policy import SOURCE_RETENTION_MAP

        if retention_class is None:
            retention_class = SOURCE_RETENTION_MAP.get(source, "standard")

        with get_db() as db:
            now = int(time.time())
            memory = MemoryModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                content=content,
                source=source,
                retention_class=retention_class,
                created_at=now,
                updated_at=now,
            )
            result = Memory(**memory.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            return MemoryModel.model_validate(result)

    def update_memory_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        content: str,
    ) -> Optional[MemoryModel]:
        with get_db() as db:
            try:
                db.query(Memory).filter_by(id=id, user_id=user_id).filter(
                    Memory.deleted_at.is_(None)
                ).update({"content": content, "updated_at": int(time.time())})
                db.commit()
                return self.get_memory_by_id(id)
            except Exception:
                return None

    def get_memories(self) -> list[MemoryModel]:
        with get_db() as db:
            try:
                memories = db.query(Memory).filter(Memory.deleted_at.is_(None)).all()
                return [MemoryModel.model_validate(memory) for memory in memories]
            except Exception:
                return []

    def get_memories_by_user_id(self, user_id: str) -> list[MemoryModel]:
        with get_db() as db:
            try:
                memories = (
                    db.query(Memory)
                    .filter_by(user_id=user_id)
                    .filter(Memory.deleted_at.is_(None))
                    .all()
                )
                return [MemoryModel.model_validate(memory) for memory in memories]
            except Exception:
                return []

    def get_memory_by_id(self, id: str) -> Optional[MemoryModel]:
        with get_db() as db:
            try:
                memory = (
                    db.query(Memory)
                    .filter_by(id=id)
                    .filter(Memory.deleted_at.is_(None))
                    .first()
                )
                return MemoryModel.model_validate(memory) if memory else None
            except Exception:
                return None

    # Hard delete methods removed in Phase 4 governance.
    # Use soft_delete_memory_by_id_and_user_id() or soft_delete_memories_by_user_id() instead.
    # Retention worker handles hard delete after 30-day grace period.

    def delete_memory_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        """Deprecated: kept for backward compatibility. Prefer soft_delete_*."""
        with get_db() as db:
            try:
                db.query(Memory).filter_by(id=id, user_id=user_id).delete()
                db.commit()

                return True
            except Exception:
                return False

    def get_memory_count_by_user_id(self, user_id: str) -> int:
        with get_db() as db:
            try:
                return (
                    db.query(Memory)
                    .filter_by(user_id=user_id)
                    .filter(Memory.deleted_at.is_(None))
                    .count()
                )
            except Exception:
                return 0

    def get_profile_by_user_id(self, user_id: str) -> Optional[MemoryModel]:
        with get_db() as db:
            try:
                profile = (
                    db.query(Memory)
                    .filter_by(user_id=user_id, source="profile")
                    .filter(Memory.deleted_at.is_(None))
                    .first()
                )
                return MemoryModel.model_validate(profile) if profile else None
            except Exception:
                return None

    def soft_delete_memory_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        """Soft delete: set deleted_at timestamp instead of removing row."""
        with get_db() as db:
            try:
                updated = (
                    db.query(Memory)
                    .filter_by(id=id, user_id=user_id)
                    .filter(Memory.deleted_at.is_(None))
                    .update({"deleted_at": int(time.time())})
                )
                db.commit()
                return updated > 0
            except Exception:
                return False

    def soft_delete_memories_by_user_id(self, user_id: str) -> list[str]:
        """Soft delete all user memories. Returns list of affected memory IDs."""
        with get_db() as db:
            try:
                ids = [
                    row.id
                    for row in (
                        db.query(Memory.id)
                        .filter_by(user_id=user_id)
                        .filter(Memory.deleted_at.is_(None))
                        .all()
                    )
                ]
                if ids:
                    (
                        db.query(Memory)
                        .filter(Memory.id.in_(ids))
                        .update(
                            {"deleted_at": int(time.time())},
                            synchronize_session=False,
                        )
                    )
                    db.commit()
                return ids
            except Exception:
                return []

    def get_org_memories(self, org_id: str) -> list[MemoryModel]:
        """Get all active org-scoped memories for an organization."""
        with get_db() as db:
            try:
                memories = (
                    db.query(Memory)
                    .filter_by(scope="org", org_id=org_id)
                    .filter(Memory.deleted_at.is_(None))
                    .all()
                )
                return [MemoryModel.model_validate(m) for m in memories]
            except Exception:
                return []

    def insert_org_memory(
        self, org_id: str, content: str, admin_user_id: str
    ) -> Optional[MemoryModel]:
        """Create org-scoped memory. Admin only."""
        with get_db() as db:
            now = int(time.time())
            memory = MemoryModel(
                id=str(uuid.uuid4()),
                user_id=admin_user_id,
                content=content,
                source="manual",
                scope="org",
                org_id=org_id,
                retention_class="permanent",
                created_at=now,
                updated_at=now,
            )
            result = Memory(**memory.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            return MemoryModel.model_validate(result)

    def get_memories_by_user_id_for_admin(self, user_id: str) -> list[MemoryModel]:
        """Admin view: get all user memories including retention info."""
        with get_db() as db:
            try:
                memories = (
                    db.query(Memory)
                    .filter_by(user_id=user_id)
                    .filter(Memory.deleted_at.is_(None))
                    .order_by(Memory.created_at.desc())
                    .all()
                )
                return [MemoryModel.model_validate(m) for m in memories]
            except Exception:
                return []

    def upsert_profile(self, user_id: str, content: str) -> Optional[MemoryModel]:
        with get_db() as db:
            try:
                existing = (
                    db.query(Memory)
                    .filter_by(user_id=user_id, source="profile")
                    .filter(Memory.deleted_at.is_(None))
                    .first()
                )
                if existing:
                    existing.content = content
                    existing.updated_at = int(time.time())
                    db.commit()
                    db.refresh(existing)
                    return MemoryModel.model_validate(existing)
                else:
                    return self.insert_new_memory(user_id, content, source="profile")
            except Exception:
                return None


Memories = MemoriesTable()
