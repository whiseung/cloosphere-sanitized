"""DbSphere SQL Editor — 사용자별 .sql 파일 영속 모델.

한 DbSphere 에 종속된 .sql 파일이며, 사용자(user_id) 소유. 1차 릴리스에서는
공유 기능이 없지만 `access_control` 컬럼을 nullable 로 두어 후방 호환을 확보.

라우터에서의 핵심 쿼리:
- list by (dbsphere_id, user_id) → 사이드 패널의 탭 목록
- get by id → 특정 .sql 편집
- update by id with optimistic concurrency (expected_updated_at) → 다른 브라우저 탭/디바이스에서 동시 편집 시 충돌 감지 (409)
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, BigInteger, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# 사용자가 한 파일에 저장할 수 있는 최대 SQL 본문 크기.
# 라우터 / 모델 양쪽에서 강제하여 거대 페이로드로 인한 DB row bloat 와
# PATCH 요청 바디 폭주를 방지한다.
SQL_FILE_CONTENT_MAX_BYTES = 256 * 1024  # 256KB


####################
# ORM
####################


class DbSphereSqlFile(Base):
    __tablename__ = "dbsphere_sql_file"

    id = Column(Text, unique=True, primary_key=True)
    dbsphere_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)

    name = Column(Text, nullable=False)
    content = Column(Text, nullable=False, server_default="")

    # 후방 호환: 1차 릴리스에서 미사용. 공유 기능 도입 시 그룹/사용자 권한 저장.
    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


####################
# Pydantic
####################


class DbSphereSqlFileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dbsphere_id: str
    user_id: str

    name: str
    content: str

    access_control: Optional[dict] = None

    created_at: int
    updated_at: int


class DbSphereSqlFileForm(BaseModel):
    """POST /sql/files 입력. id/user_id/timestamps 제외."""

    name: str = Field(min_length=1, max_length=255)
    content: str = ""

    @field_validator("content")
    @classmethod
    def _content_size_cap(cls, v: str) -> str:
        if len(v.encode("utf-8")) > SQL_FILE_CONTENT_MAX_BYTES:
            raise ValueError(
                f"SQL content exceeds {SQL_FILE_CONTENT_MAX_BYTES // 1024}KB limit"
            )
        return v


class DbSphereSqlFileUpdateForm(BaseModel):
    """PATCH /sql/files/{id} 입력. 부분 갱신 + 낙관적 동시성."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = None
    expected_updated_at: Optional[int] = None  # If-Match 의미. None 이면 검사 생략.

    @field_validator("content")
    @classmethod
    def _content_size_cap(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.encode("utf-8")) > SQL_FILE_CONTENT_MAX_BYTES:
            raise ValueError(
                f"SQL content exceeds {SQL_FILE_CONTENT_MAX_BYTES // 1024}KB limit"
            )
        return v


class DbSphereSqlFileResponse(DbSphereSqlFileModel):
    pass


####################
# Table (CRUD)
####################


# update_sql_file_by_id 의 두 번째 반환 값 — 오류 코드.
# 라우터는 이 값을 HTTP status 로 매핑한다 (not_found→404, forbidden→403, conflict→409).
SqlFileError = Optional[str]  # 'not_found' | 'forbidden' | 'conflict' | None


class DbSphereSqlFileTable:
    def insert_new_sql_file(
        self,
        dbsphere_id: str,
        user_id: str,
        form_data: DbSphereSqlFileForm,
    ) -> Optional[DbSphereSqlFileModel]:
        try:
            with get_db() as db:
                now = int(time.time())
                resource = DbSphereSqlFileModel(
                    **form_data.model_dump(),
                    id=str(uuid.uuid4()),
                    dbsphere_id=dbsphere_id,
                    user_id=user_id,
                    access_control=None,
                    created_at=now,
                    updated_at=now,
                )
                row = DbSphereSqlFile(**resource.model_dump())
                db.add(row)
                db.commit()
                db.refresh(row)
                return DbSphereSqlFileModel.model_validate(row)
        except Exception as e:
            log.error("insert_new_sql_file failed: %s", e)
            return None

    def get_sql_files_by_dbsphere_and_user(
        self, dbsphere_id: str, user_id: str
    ) -> list[DbSphereSqlFileModel]:
        with get_db() as db:
            rows = (
                db.query(DbSphereSqlFile)
                .filter_by(dbsphere_id=dbsphere_id, user_id=user_id)
                .order_by(DbSphereSqlFile.updated_at.desc())
                .all()
            )
            return [DbSphereSqlFileModel.model_validate(r) for r in rows]

    def get_sql_file_by_id(self, file_id: str) -> Optional[DbSphereSqlFileModel]:
        with get_db() as db:
            row = db.query(DbSphereSqlFile).filter_by(id=file_id).first()
            if not row:
                return None
            return DbSphereSqlFileModel.model_validate(row)

    def update_sql_file_by_id(
        self,
        file_id: str,
        user_id: str,
        form_data: DbSphereSqlFileUpdateForm,
    ) -> tuple[Optional[DbSphereSqlFileModel], SqlFileError]:
        """Optimistic-concurrency PATCH.

        Returns (model, error_code):
        - ('not_found', None): row 가 없음
        - (None, 'forbidden'): 소유자 아님
        - (server_copy, 'conflict'): expected_updated_at mismatch — UI 가 서버 copy 로 표시
        - (updated, None): 정상 갱신
        """
        with get_db() as db:
            row = db.query(DbSphereSqlFile).filter_by(id=file_id).first()
            if not row:
                return None, "not_found"
            if row.user_id != user_id:
                return None, "forbidden"
            if (
                form_data.expected_updated_at is not None
                and row.updated_at != form_data.expected_updated_at
            ):
                # 충돌 — 서버 copy 를 반환해 UI 에서 비교/머지 결정에 사용.
                return DbSphereSqlFileModel.model_validate(row), "conflict"

            if form_data.name is not None:
                row.name = form_data.name
            if form_data.content is not None:
                row.content = form_data.content
            row.updated_at = int(time.time())

            db.commit()
            db.refresh(row)
            return DbSphereSqlFileModel.model_validate(row), None

    def delete_sql_file_by_id(
        self, file_id: str, user_id: str
    ) -> tuple[bool, SqlFileError]:
        """Returns (deleted, error_code). forbidden 일 때 deleted=False."""
        with get_db() as db:
            row = db.query(DbSphereSqlFile).filter_by(id=file_id).first()
            if not row:
                return False, "not_found"
            if row.user_id != user_id:
                return False, "forbidden"
            db.delete(row)
            db.commit()
            return True, None

    def delete_sql_files_by_dbsphere_id(self, dbsphere_id: str) -> int:
        """DbSphere 삭제 시 cascade. 반환: 삭제된 row 수."""
        with get_db() as db:
            count = (
                db.query(DbSphereSqlFile).filter_by(dbsphere_id=dbsphere_id).delete()
            )
            db.commit()
            return count


DbSphereSqlFiles = DbSphereSqlFileTable()
