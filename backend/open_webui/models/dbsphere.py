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
# DbSphere DB Schema
####################


class DbSphere(Base):
    __tablename__ = "dbsphere"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)  # Controls data access levels.
    # Defines access control rules for this entry.
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing;
    #   Can specify group or user-level restrictions:
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      }
    #   }

    # Schema extraction settings for Vanna-style learning
    auto_extract_model = Column(
        Text, nullable=True
    )  # Model ID for auto schema extraction
    sample_row_count = Column(
        BigInteger, nullable=True, default=5
    )  # Number of sample rows
    last_extracted_at = Column(BigInteger, nullable=True)  # Last extraction timestamp

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class DbSphereModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    # Schema extraction settings
    auto_extract_model: Optional[str] = None
    sample_row_count: Optional[int] = 5
    last_extracted_at: Optional[int] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class DbSphereUserModel(DbSphereModel):
    user: Optional[UserResponse] = None


class DbSphereResponse(DbSphereModel):
    pass


class DbSphereUserResponse(DbSphereUserModel):
    pass


class DbSphereForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    auto_extract_model: Optional[str] = None
    sample_row_count: Optional[int] = 5


class DbSphereTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(DbSphere).filter(DbSphere.name == name.strip())
            if exclude_id:
                query = query.filter(DbSphere.id != exclude_id)
            return query.first() is not None

    def insert_new_dbsphere(
        self, user_id: str, form_data: DbSphereForm
    ) -> Optional[DbSphereModel]:
        with get_db() as db:
            dbsphere = DbSphereModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = DbSphere(**dbsphere.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return DbSphereModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    def get_dbspheres(self) -> list[DbSphereUserModel]:
        with get_db() as db:
            dbspheres = []
            for dbsphere in (
                db.query(DbSphere).order_by(DbSphere.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(dbsphere.user_id)
                dbspheres.append(
                    DbSphereUserModel.model_validate(
                        {
                            **DbSphereModel.model_validate(dbsphere).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return dbspheres

    def get_dbspheres_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[DbSphereUserModel]:
        dbspheres = self.get_dbspheres()
        return [
            dbsphere
            for dbsphere in dbspheres
            if dbsphere.user_id == user_id
            or has_access(user_id, permission, dbsphere.access_control)
        ]

    def get_dbsphere_by_id(self, id: str) -> Optional[DbSphereModel]:
        try:
            with get_db() as db:
                dbsphere = db.query(DbSphere).filter_by(id=id).first()
                return DbSphereModel.model_validate(dbsphere) if dbsphere else None
        except Exception:
            return None

    def update_dbsphere_by_id(
        self, id: str, form_data: DbSphereForm, overwrite: bool = False
    ) -> Optional[DbSphereModel]:
        try:
            with get_db() as db:
                dbsphere = db.query(DbSphere).filter_by(id=id).first()
                if dbsphere:
                    update_data = form_data.model_dump()
                    for key, value in update_data.items():
                        setattr(dbsphere, key, value)
                    dbsphere.updated_at = int(time.time())
                    db.commit()
                    db.refresh(dbsphere)
                    return DbSphereModel.model_validate(dbsphere)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def update_dbsphere_data_by_id(
        self, id: str, data: dict
    ) -> Optional[DbSphereModel]:
        try:
            with get_db() as db:
                dbsphere = db.query(DbSphere).filter_by(id=id).first()
                if dbsphere:
                    dbsphere.data = data
                    dbsphere.updated_at = int(time.time())
                    db.commit()
                    db.refresh(dbsphere)
                    return DbSphereModel.model_validate(dbsphere)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def update_extraction_job_atomic(
        self, id: str, status_update: dict
    ) -> Optional[DbSphereModel]:
        """Atomically update extraction_job status in dbsphere.data"""
        try:
            with get_db() as db:
                # Use with_for_update() for row-level locking
                dbsphere = db.query(DbSphere).filter_by(id=id).with_for_update().first()
                if dbsphere:
                    # Create new dicts to ensure SQLAlchemy detects the change
                    current_data = dict(dbsphere.data) if dbsphere.data else {}
                    current_job = dict(current_data.get("extraction_job", {}))
                    current_job.update(status_update)
                    current_data["extraction_job"] = current_job
                    dbsphere.data = current_data
                    dbsphere.updated_at = int(time.time())
                    db.commit()
                    db.refresh(dbsphere)
                    return DbSphereModel.model_validate(dbsphere)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def update_dbsphere_data_atomic(
        self, id: str, partial: dict
    ) -> Optional[DbSphereModel]:
        """`dbsphere.data` 의 top-level 키들을 부분 갱신 (deep-merge 아님).

        `update_extraction_job_atomic` 과 동일한 row-lock + dict copy patch 패턴.
        whole-replace (`update_dbsphere_data_by_id`) 와 달리 다른 키 (예: extraction_job
        진행 상태, connection) 를 보존한다.

        주 용도:
        - `allow_data_modifications` 토글 PATCH (P-H5 race 방지)
        - `sql_editor` 같은 신규 키 부분 갱신
        - SQL Editor 관련 사용자 설정 부분 변경

        deep-merge 가 필요한 케이스 (예: data.connection.host 만 변경) 는 호출 측
        에서 dict 를 합쳐 partial 로 전달해야 한다 — 이 메서드는 dbsphere.data 의
        top-level 만 본다.
        """
        try:
            with get_db() as db:
                dbsphere = db.query(DbSphere).filter_by(id=id).with_for_update().first()
                if not dbsphere:
                    return None
                current_data = dict(dbsphere.data) if dbsphere.data else {}
                current_data.update(partial)
                dbsphere.data = current_data
                dbsphere.updated_at = int(time.time())
                db.commit()
                db.refresh(dbsphere)
                return DbSphereModel.model_validate(dbsphere)
        except Exception as e:
            log.exception(e)
            return None

    def delete_dbsphere_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                dbsphere = db.query(DbSphere).filter_by(id=id).first()
                if dbsphere:
                    db.delete(dbsphere)
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def delete_all_dbspheres(self) -> bool:
        with get_db() as db:
            try:
                db.query(DbSphere).delete()
                db.commit()

                return True
            except Exception:
                return False


DbSpheres = DbSphereTable()
