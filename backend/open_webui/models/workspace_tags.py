import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Index, Text

log = logging.getLogger(__name__)


####################
# WorkspaceTag DB Schema
####################


class WorkspaceTag(Base):
    __tablename__ = "workspace_tag"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    user_id = Column(Text, nullable=False)
    created_at = Column(BigInteger)


class WorkspaceTagAssignment(Base):
    __tablename__ = "workspace_tag_assignment"

    id = Column(Text, primary_key=True)
    tag_id = Column(Text, nullable=False)
    resource_type = Column(Text, nullable=False)
    resource_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    created_at = Column(BigInteger)

    __table_args__ = (
        Index("ix_wta_resource", "resource_type", "resource_id"),
        Index("ix_wta_tag_id", "tag_id"),
    )


####################
# Pydantic Models
####################


class WorkspaceTagModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    user_id: str
    created_at: int


class WorkspaceTagForm(BaseModel):
    name: str


class WorkspaceTagAssignForm(BaseModel):
    tag_id: str


class WorkspaceTagAssignmentModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tag_id: str
    resource_type: str
    resource_id: str
    user_id: str
    created_at: int


####################
# Table Operations
####################


class WorkspaceTagTable:
    # ---- Tag CRUD ----

    def get_all_tags(self) -> list[WorkspaceTagModel]:
        with get_db() as db:
            tags = db.query(WorkspaceTag).order_by(WorkspaceTag.name).all()
            return [WorkspaceTagModel.model_validate(t) for t in tags]

    def get_tag_by_id(self, id: str) -> Optional[WorkspaceTagModel]:
        with get_db() as db:
            tag = db.query(WorkspaceTag).filter_by(id=id).first()
            return WorkspaceTagModel.model_validate(tag) if tag else None

    def create_tag(
        self, user_id: str, form_data: WorkspaceTagForm
    ) -> Optional[WorkspaceTagModel]:
        with get_db() as db:
            # Check duplicate name
            existing = (
                db.query(WorkspaceTag).filter_by(name=form_data.name.strip()).first()
            )
            if existing:
                return WorkspaceTagModel.model_validate(existing)

            tag = WorkspaceTag(
                id=str(uuid.uuid4()),
                name=form_data.name.strip(),
                user_id=user_id,
                created_at=int(time.time()),
            )
            db.add(tag)
            db.commit()
            db.refresh(tag)
            return WorkspaceTagModel.model_validate(tag)

    def update_tag(
        self, id: str, form_data: WorkspaceTagForm
    ) -> Optional[WorkspaceTagModel]:
        with get_db() as db:
            new_name = form_data.name.strip()
            # Check duplicate name (different tag)
            existing = (
                db.query(WorkspaceTag)
                .filter(WorkspaceTag.name == new_name, WorkspaceTag.id != id)
                .first()
            )
            if existing:
                return None  # Duplicate name

            tag = db.query(WorkspaceTag).filter_by(id=id).first()
            if not tag:
                return None
            tag.name = new_name
            db.commit()
            db.refresh(tag)
            return WorkspaceTagModel.model_validate(tag)

    def get_tag_usage_count(self, id: str) -> int:
        with get_db() as db:
            return db.query(WorkspaceTagAssignment).filter_by(tag_id=id).count()

    def delete_tag(self, id: str) -> bool:
        with get_db() as db:
            # Delete assignments first
            db.query(WorkspaceTagAssignment).filter_by(tag_id=id).delete()
            result = db.query(WorkspaceTag).filter_by(id=id).delete()
            db.commit()
            return result > 0

    # ---- Assignment CRUD ----

    def get_tags_by_resource(
        self, resource_type: str, resource_id: str
    ) -> list[WorkspaceTagModel]:
        with get_db() as db:
            assignments = (
                db.query(WorkspaceTagAssignment)
                .filter_by(resource_type=resource_type, resource_id=resource_id)
                .all()
            )
            tag_ids = [a.tag_id for a in assignments]
            if not tag_ids:
                return []
            tags = (
                db.query(WorkspaceTag)
                .filter(WorkspaceTag.id.in_(tag_ids))
                .order_by(WorkspaceTag.name)
                .all()
            )
            return [WorkspaceTagModel.model_validate(t) for t in tags]

    def get_resource_ids_by_tag(self, tag_id: str, resource_type: str) -> list[str]:
        with get_db() as db:
            assignments = (
                db.query(WorkspaceTagAssignment)
                .filter_by(tag_id=tag_id, resource_type=resource_type)
                .all()
            )
            return [a.resource_id for a in assignments]

    def get_all_assignments_by_type(self, resource_type: str) -> dict[str, list[str]]:
        """Get all tag assignments for a resource type.
        Returns {resource_id: [tag_name, ...]}"""
        with get_db() as db:
            assignments = (
                db.query(WorkspaceTagAssignment)
                .filter_by(resource_type=resource_type)
                .all()
            )
            if not assignments:
                return {}

            tag_ids = list({a.tag_id for a in assignments})
            tags = db.query(WorkspaceTag).filter(WorkspaceTag.id.in_(tag_ids)).all()
            tag_map = {t.id: t.name for t in tags}

            result: dict[str, list[str]] = {}
            for a in assignments:
                tag_name = tag_map.get(a.tag_id)
                if tag_name:
                    result.setdefault(a.resource_id, []).append(tag_name)
            return result

    def assign_tag(
        self,
        tag_id: str,
        resource_type: str,
        resource_id: str,
        user_id: str,
    ) -> Optional[WorkspaceTagAssignmentModel]:
        with get_db() as db:
            # Check duplicate
            existing = (
                db.query(WorkspaceTagAssignment)
                .filter_by(
                    tag_id=tag_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
                .first()
            )
            if existing:
                return WorkspaceTagAssignmentModel.model_validate(existing)

            assignment = WorkspaceTagAssignment(
                id=str(uuid.uuid4()),
                tag_id=tag_id,
                resource_type=resource_type,
                resource_id=resource_id,
                user_id=user_id,
                created_at=int(time.time()),
            )
            db.add(assignment)
            db.commit()
            db.refresh(assignment)
            return WorkspaceTagAssignmentModel.model_validate(assignment)

    def unassign_tag(self, tag_id: str, resource_type: str, resource_id: str) -> bool:
        with get_db() as db:
            result = (
                db.query(WorkspaceTagAssignment)
                .filter_by(
                    tag_id=tag_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
                .delete()
            )
            db.commit()
            return result > 0


WorkspaceTags = WorkspaceTagTable()
