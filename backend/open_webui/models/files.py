import logging
import math
import time
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Index, String, Text, or_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Files DB Schema
####################


class File(Base):
    __tablename__ = "file"
    __table_args__ = (
        Index("ix_file_user_id", "user_id"),
        Index("ix_file_created_at", "created_at"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String)
    hash = Column(Text, nullable=True)

    filename = Column(Text)
    path = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    path: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: Optional[int]  # timestamp in epoch
    updated_at: Optional[int]  # timestamp in epoch


####################
# Forms
####################


class FileMeta(BaseModel):
    name: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class FileModelResponse(BaseModel):
    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    data: Optional[dict] = None
    meta: FileMeta

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    model_config = ConfigDict(extra="allow")


class FileMetadataResponse(BaseModel):
    id: str
    meta: dict
    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


class FileForm(BaseModel):
    id: str
    hash: Optional[str] = None
    filename: str
    path: str
    data: dict = {}
    meta: dict = {}
    access_control: Optional[dict] = None


####################
# File Log Types
####################


class FileLogQueryParams(BaseModel):
    page: int = 1
    limit: int = 20
    source: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None  # blocked, flagged
    search: Optional[str] = None
    user_id: Optional[str] = None
    from_date: Optional[int] = None
    to_date: Optional[int] = None


class FileLogItem(BaseModel):
    id: str
    user_id: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    filename: str
    meta: Optional[dict] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class FileLogListResponse(BaseModel):
    items: list[FileLogItem]
    total: int
    page: int
    limit: int
    total_pages: int


class FilesTable:
    def insert_new_file(self, user_id: str, form_data: FileForm) -> Optional[FileModel]:
        with get_db() as db:
            file = FileModel(
                **{
                    **form_data.model_dump(),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = File(**file.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return FileModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting a new file: {e}")
                return None

    def get_file_by_id(self, id: str) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.get(File, id)
                return FileModel.model_validate(file)
            except Exception:
                return None

    def get_file_metadata_by_id(self, id: str) -> Optional[FileMetadataResponse]:
        with get_db() as db:
            try:
                file = db.get(File, id)
                return FileMetadataResponse(
                    id=file.id,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                )
            except Exception:
                return None

    def get_files(self) -> list[FileModel]:
        with get_db() as db:
            return [FileModel.model_validate(file) for file in db.query(File).all()]

    def get_files_by_ids(self, ids: list[str]) -> list[FileModel]:
        with get_db() as db:
            return [
                FileModel.model_validate(file)
                for file in db.query(File)
                .filter(File.id.in_(ids))
                .order_by(File.updated_at.desc())
                .all()
            ]

    def get_existing_file_ids(
        self, ids: list[str], search: Optional[str] = None
    ) -> list[str]:
        """``ids`` 중 실제 DB 에 존재하는 파일 ID 만 반환 (옵션: filename 검색).

        전체 파일 목록을 선택하는 UX 경로처럼 메타데이터 없이 ID 만 필요한 경우
        사용. 결과 순서는 File.id 순 (성능 우선)."""
        if not ids:
            return []
        with get_db() as db:
            q = db.query(File.id).filter(File.id.in_(ids))
            if search:
                q = q.filter(File.filename.ilike(f"%{search}%"))
            return [row[0] for row in q.all()]

    def get_files_by_ids_paginated(
        self,
        ids: list[str],
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        sort: str = "newest",
    ) -> tuple[list[FileModel], int]:
        if not ids:
            return [], 0
        with get_db() as db:
            from sqlalchemy import case, func

            q = db.query(File).filter(File.id.in_(ids))
            if search:
                q = q.filter(File.filename.ilike(f"%{search}%"))
            total = q.count()
            order_map = {
                "newest": File.created_at.desc(),
                "oldest": File.created_at.asc(),
                "name": File.filename.asc(),
            }
            order_clause = order_map.get(sort, File.created_at.desc())

            # failed 파일은 어떤 정렬 기준이든 항상 최상단에 고정 (pending/processing/queued는 그 다음)
            dialect = (
                db.get_bind().dialect.name if db.get_bind() is not None else "sqlite"
            )
            if dialect == "postgresql":
                status_expr = func.json_extract_path_text(
                    File.data, "processing_job", "status"
                )
            else:
                status_expr = func.json_extract(File.data, "$.processing_job.status")
            status_rank = case(
                (status_expr == "failed", 0),
                (status_expr == "processing", 1),
                (status_expr == "pending", 1),
                (status_expr == "queued", 1),
                else_=2,
            )

            rows = q.order_by(status_rank, order_clause).offset(skip).limit(limit).all()
            return [FileModel.model_validate(r) for r in rows], total

    def get_file_metadatas_by_ids(self, ids: list[str]) -> list[FileMetadataResponse]:
        with get_db() as db:
            return [
                FileMetadataResponse(
                    id=file.id,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                )
                for file in db.query(File)
                .filter(File.id.in_(ids))
                .order_by(File.updated_at.desc())
                .all()
            ]

    def get_files_by_user_id(self, user_id: str) -> list[FileModel]:
        with get_db() as db:
            return [
                FileModel.model_validate(file)
                for file in db.query(File).filter_by(user_id=user_id).all()
            ]

    def get_files_by_pending_knowledge_id(self, knowledge_id: str) -> list[FileModel]:
        """Get files that are pending processing for a specific knowledge base."""
        with get_db() as db:
            # Filter in Python since JSON field filtering varies by DB
            files = db.query(File).all()
            return [
                FileModel.model_validate(file)
                for file in files
                if file.meta and file.meta.get("pending_knowledge_id") == knowledge_id
            ]

    def update_file_hash_by_id(self, id: str, hash: str) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                file.hash = hash
                db.commit()

                return FileModel.model_validate(file)
            except Exception:
                return None

    def update_file_data_by_id(self, id: str, data: dict) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                file.data = {**(file.data if file.data else {}), **data}
                db.commit()
                return FileModel.model_validate(file)
            except Exception as e:
                return None

    def update_file_path_by_id(self, id: str, path: str) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                file.path = path
                file.updated_at = int(time.time())
                db.commit()
                return FileModel.model_validate(file)
            except Exception:
                return None

    def update_file_metadata_by_id(self, id: str, meta: dict) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                file.meta = {**(file.meta if file.meta else {}), **meta}
                db.commit()
                return FileModel.model_validate(file)
            except Exception:
                return None

    def get_file_logs(
        self, params: FileLogQueryParams
    ) -> tuple[list[FileLogItem], int]:
        """가드레일 결과가 있는 파일 목록 (서버사이드 페이징)"""
        from open_webui.models.users import User

        with get_db() as db:
            query = db.query(
                File.id,
                File.user_id,
                File.filename,
                File.meta,
                File.created_at,
                File.updated_at,
                User.name.label("user_name"),
                User.email.label("user_email"),
            ).outerjoin(User, File.user_id == User.id)

            # 가드레일 결과가 있는 파일만
            query = query.filter(
                or_(
                    File.meta["classification"].isnot(None),
                    File.meta["guardrail_blocked"].isnot(None),
                )
            )

            # Filters
            if params.user_id:
                query = query.filter(File.user_id == params.user_id)
            if params.from_date:
                query = query.filter(File.created_at >= params.from_date)
            if params.to_date:
                query = query.filter(File.created_at <= params.to_date)
            if params.search:
                q = f"%{params.search}%"
                query = query.filter(
                    or_(
                        File.filename.ilike(q),
                        User.name.ilike(q),
                        User.email.ilike(q),
                    )
                )

            # JSON field filters — fetch all matching rows and filter in Python
            # because JSON subscript behavior can differ across SQLite/PostgreSQL
            rows = query.order_by(File.created_at.desc()).all()

            # Apply JSON-level filters in Python
            filtered = []
            for row in rows:
                meta = row.meta or {}

                if params.source:
                    sources = [s.strip() for s in params.source.split(",")]
                    if meta.get("source") not in sources:
                        continue

                if params.category:
                    categories = [c.strip() for c in params.category.split(",")]
                    classification = meta.get("classification") or {}
                    if classification.get("category") not in categories:
                        continue

                if params.status:
                    statuses = [s.strip() for s in params.status.split(",")]
                    matched = False
                    if "blocked" in statuses and meta.get("guardrail_blocked"):
                        matched = True
                    if "flagged" in statuses:
                        classification = meta.get("classification") or {}
                        if classification.get("category") == "CONFIDENTIAL":
                            matched = True
                    if not matched:
                        continue

                filtered.append(row)

            total = len(filtered)
            total_pages = math.ceil(total / params.limit) if params.limit else 1

            # Apply pagination
            offset = (params.page - 1) * params.limit
            page_rows = filtered[offset : offset + params.limit]

            items = [
                FileLogItem(
                    id=row.id,
                    user_id=row.user_id,
                    user_name=row.user_name,
                    user_email=row.user_email,
                    filename=row.filename,
                    meta=row.meta,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in page_rows
            ]

            return items, total

    def delete_file_by_id(self, id: str) -> bool:
        with get_db() as db:
            try:
                db.query(File).filter_by(id=id).delete()
                db.commit()

                return True
            except Exception:
                return False

    def delete_files_by_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        with get_db() as db:
            try:
                deleted = (
                    db.query(File)
                    .filter(File.id.in_(ids))
                    .delete(synchronize_session=False)
                )
                db.commit()
                return int(deleted or 0)
            except Exception as e:
                log.error(f"delete_files_by_ids failed: {e}")
                db.rollback()
                return 0

    def delete_all_files(self) -> bool:
        with get_db() as db:
            try:
                db.query(File).delete()
                db.commit()

                return True
            except Exception:
                return False


Files = FilesTable()
