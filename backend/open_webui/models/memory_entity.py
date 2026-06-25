"""Memory entity models — Knowledge Plane entities extracted from memories."""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Index, String, UniqueConstraint

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

DEFAULT_ENTITY_TYPES = [
    {"name": "tech", "description": "Technologies, frameworks, tools, languages"},
    {"name": "project", "description": "Project names and products"},
    {"name": "person", "description": "People's names"},
    {"name": "organization", "description": "Companies, teams, departments"},
    {"name": "concept", "description": "Domain concepts and other entities"},
]


class MemoryEntity(Base):
    __tablename__ = "memory_entity"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    memory_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    org_id = Column(String, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "name", "entity_type", "user_id", name="uq_entity_name_type_user"
        ),
        Index("ix_memory_entity_user_id", "user_id"),
        Index("ix_memory_entity_type", "entity_type"),
    )


class MemoryEntityModel(BaseModel):
    id: str
    name: str
    entity_type: str
    memory_id: str
    user_id: str
    org_id: Optional[str] = None
    created_at: int

    model_config = ConfigDict(from_attributes=True)


class MemoryEntityType(Base):
    __tablename__ = "memory_entity_type"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    org_id = Column(String, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "org_id", name="uq_entity_type_name_org"),
    )


class MemoryEntityTypeModel(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    org_id: Optional[str] = None
    created_at: int

    model_config = ConfigDict(from_attributes=True)


class MemoryEntityTable:
    def upsert_entity(
        self,
        name: str,
        entity_type: str,
        memory_id: str,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> Optional[MemoryEntityModel]:
        with get_db() as db:
            try:
                existing = (
                    db.query(MemoryEntity)
                    .filter_by(
                        name=name.lower(), entity_type=entity_type, user_id=user_id
                    )
                    .first()
                )
                if existing:
                    existing.memory_id = memory_id
                    existing.created_at = int(time.time())
                    db.commit()
                    db.refresh(existing)
                    return MemoryEntityModel.model_validate(existing)
                else:
                    entity = MemoryEntity(
                        id=str(uuid.uuid4()),
                        name=name.lower(),
                        entity_type=entity_type,
                        memory_id=memory_id,
                        user_id=user_id,
                        org_id=org_id,
                        created_at=int(time.time()),
                    )
                    db.add(entity)
                    db.commit()
                    db.refresh(entity)
                    return MemoryEntityModel.model_validate(entity)
            except Exception as e:
                log.warning(f"[MemoryEntity] Upsert failed: {e}")
                return None

    def get_entities_by_user_id(self, user_id: str) -> list[MemoryEntityModel]:
        with get_db() as db:
            try:
                entities = db.query(MemoryEntity).filter_by(user_id=user_id).all()
                return [MemoryEntityModel.model_validate(e) for e in entities]
            except Exception:
                return []

    def get_entities_grouped_by_type(
        self, entity_type: Optional[str] = None
    ) -> list[dict]:
        """Get entity counts and examples grouped by type."""
        with get_db() as db:
            try:
                from sqlalchemy import func

                query = db.query(
                    MemoryEntity.entity_type,
                    func.count(MemoryEntity.id).label("count"),
                )
                if entity_type:
                    query = query.filter(MemoryEntity.entity_type == entity_type)
                results = query.group_by(MemoryEntity.entity_type).all()

                grouped = []
                for etype, count in results:
                    examples = (
                        db.query(MemoryEntity.name)
                        .filter_by(entity_type=etype)
                        .distinct()
                        .limit(5)
                        .all()
                    )
                    grouped.append(
                        {
                            "entity_type": etype,
                            "count": count,
                            "examples": [e.name for e in examples],
                        }
                    )
                return grouped
            except Exception:
                return []

    def find_matching_entities(
        self, user_id: str, query_text: str
    ) -> list[MemoryEntityModel]:
        """Find entities whose names appear in the query text."""
        entities = self.get_entities_by_user_id(user_id)
        query_lower = query_text.lower()
        return [e for e in entities if e.name in query_lower]


class MemoryEntityTypeTable:
    def get_all_types(
        self, org_id: Optional[str] = None
    ) -> list[MemoryEntityTypeModel]:
        with get_db() as db:
            try:
                types = (
                    db.query(MemoryEntityType)
                    .filter_by(org_id=org_id)
                    .order_by(MemoryEntityType.name)
                    .all()
                )
                return [MemoryEntityTypeModel.model_validate(t) for t in types]
            except Exception:
                return []

    def add_type(
        self, name: str, description: Optional[str] = None, org_id: Optional[str] = None
    ) -> Optional[MemoryEntityTypeModel]:
        with get_db() as db:
            try:
                entity_type = MemoryEntityType(
                    id=str(uuid.uuid4()),
                    name=name.lower(),
                    description=description,
                    org_id=org_id,
                    created_at=int(time.time()),
                )
                db.add(entity_type)
                db.commit()
                db.refresh(entity_type)
                return MemoryEntityTypeModel.model_validate(entity_type)
            except Exception:
                return None

    def delete_type(self, id: str) -> bool:
        with get_db() as db:
            try:
                db.query(MemoryEntityType).filter_by(id=id).delete()
                db.commit()
                return True
            except Exception:
                return False

    def seed_defaults(self) -> None:
        with get_db() as db:
            try:
                existing = db.query(MemoryEntityType).filter_by(org_id=None).count()
                if existing > 0:
                    return
                now = int(time.time())
                for et in DEFAULT_ENTITY_TYPES:
                    db.add(
                        MemoryEntityType(
                            id=str(uuid.uuid4()),
                            name=et["name"],
                            description=et["description"],
                            org_id=None,
                            created_at=now,
                        )
                    )
                db.commit()
                log.info("[MemoryEntityType] Seeded default entity types")
            except Exception as e:
                log.warning(f"[MemoryEntityType] Seed failed: {e}")


MemoryEntities = MemoryEntityTable()
EntityTypes = MemoryEntityTypeTable()
