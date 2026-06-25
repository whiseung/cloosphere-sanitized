import json
import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserResponse, Users
from open_webui.utils.access_control import has_access
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Project DB Schema
####################


class Project(Base):
    __tablename__ = "project"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    type = Column(Text, nullable=True, server_default="general")
    description = Column(Text, nullable=True)

    knowledge_id = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class ProjectModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    type: Optional[str] = "general"
    description: Optional[str] = None

    knowledge_id: Optional[str] = None
    instructions: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int
    updated_at: int


####################
# Forms
####################


class ProjectUserModel(ProjectModel):
    user: Optional[UserResponse] = None


class ProjectForm(BaseModel):
    name: str
    type: Optional[str] = "general"
    description: Optional[str] = None
    instructions: Optional[str] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class ProjectUpdateForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class ProjectTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(Project).filter(Project.name == name.strip())
            if exclude_id:
                query = query.filter(Project.id != exclude_id)
            return query.first() is not None

    def insert_new_project(
        self,
        user_id: str,
        form_data: ProjectForm,
        knowledge_id: Optional[str] = None,
    ) -> Optional[ProjectModel]:
        with get_db() as db:
            project = ProjectModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "knowledge_id": knowledge_id,
                    "data": {"chat_ids": []},
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Project(**project.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return ProjectModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    def get_projects(self) -> list[ProjectUserModel]:
        with get_db() as db:
            projects = []
            for project in db.query(Project).order_by(Project.updated_at.desc()).all():
                user = Users.get_user_by_id(project.user_id)
                projects.append(
                    ProjectUserModel.model_validate(
                        {
                            **ProjectModel.model_validate(project).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return projects

    def get_projects_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ProjectUserModel]:
        projects = self.get_projects()
        return [
            project
            for project in projects
            if project.user_id == user_id
            or (
                project.access_control is not None
                and has_access(user_id, permission, project.access_control)
            )
        ]

    def get_project_by_id(self, id: str) -> Optional[ProjectModel]:
        try:
            with get_db() as db:
                project = db.query(Project).filter_by(id=id).first()
                return ProjectModel.model_validate(project) if project else None
        except Exception:
            return None

    def update_project_by_id(
        self, id: str, form_data: ProjectUpdateForm
    ) -> Optional[ProjectModel]:
        try:
            with get_db() as db:
                project = db.query(Project).filter_by(id=id).first()
                if project:
                    for key, value in form_data.model_dump(
                        exclude={"meta"}, exclude_none=True
                    ).items():
                        setattr(project, key, value)
                    if form_data.meta is not None:
                        current_meta = dict(project.meta) if project.meta else {}
                        current_meta.update(form_data.meta)
                        project.meta = current_meta
                    project.updated_at = int(time.time())
                    db.commit()
                    db.refresh(project)
                    return ProjectModel.model_validate(project)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def add_chat_id_to_project(self, id: str, chat_id: str) -> Optional[ProjectModel]:
        try:
            with get_db() as db:
                project = db.query(Project).filter_by(id=id).with_for_update().first()
                if project:
                    data = dict(project.data) if project.data else {}
                    chat_ids = list(data.get("chat_ids", []))
                    if chat_id not in chat_ids:
                        chat_ids.append(chat_id)
                        data["chat_ids"] = chat_ids
                        project.data = data
                        project.updated_at = int(time.time())
                    db.commit()
                    db.refresh(project)
                    return ProjectModel.model_validate(project)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def remove_chat_id_from_project(
        self, id: str, chat_id: str
    ) -> Optional[ProjectModel]:
        try:
            with get_db() as db:
                project = db.query(Project).filter_by(id=id).with_for_update().first()
                if project:
                    data = dict(project.data) if project.data else {}
                    chat_ids = list(data.get("chat_ids", []))
                    if chat_id in chat_ids:
                        chat_ids.remove(chat_id)
                        data["chat_ids"] = chat_ids
                        project.data = data
                        project.updated_at = int(time.time())
                    db.commit()
                    db.refresh(project)
                    return ProjectModel.model_validate(project)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def get_project_chat_ids_by_user_id(self, user_id: str) -> set[str]:
        """사용자의 모든 프로젝트에 속한 chat_id 집합 반환"""
        with get_db() as db:
            projects = db.query(Project).filter(Project.user_id == user_id).all()

        chat_ids = set()
        for project in projects:
            if project.data:
                data = (
                    json.loads(project.data)
                    if isinstance(project.data, str)
                    else project.data
                )
                chat_ids.update(data.get("chat_ids", []))
        return chat_ids

    def get_all_project_knowledge_ids(self) -> set[str]:
        """모든 프로젝트에 연결된 knowledge_id 집합 반환"""
        with get_db() as db:
            rows = (
                db.query(Project.knowledge_id)
                .filter(Project.knowledge_id.isnot(None))
                .all()
            )
            return {row[0] for row in rows}

    def update_project_data(
        self, id: str, data_updates: dict
    ) -> Optional[ProjectModel]:
        """Merge updates into project.data JSON field."""
        try:
            with get_db() as db:
                project = db.query(Project).filter_by(id=id).with_for_update().first()
                if project:
                    data = dict(project.data) if project.data else {}
                    data.update(data_updates)
                    project.data = data
                    project.updated_at = int(time.time())
                    db.commit()
                    db.refresh(project)
                    return ProjectModel.model_validate(project)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def delete_project_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                project = db.query(Project).filter_by(id=id).first()
                if project:
                    db.delete(project)
                    db.commit()
                    return True
                return False
        except Exception:
            return False


Projects = ProjectTable()
