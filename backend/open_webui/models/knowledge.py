import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.files import FileMetadataResponse
from open_webui.models.users import UserResponse, Users
from open_webui.utils.access_control import has_access
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Knowledge DB Schema
####################


class Knowledge(Base):
    __tablename__ = "knowledge"

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

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class KnowledgeUserModel(KnowledgeModel):
    user: Optional[UserResponse] = None


class KnowledgeResponse(KnowledgeModel):
    files: Optional[list[FileMetadataResponse | dict]] = None
    file_count: Optional[int] = None


class KnowledgeUserResponse(KnowledgeUserModel):
    files: Optional[list[FileMetadataResponse | dict]] = None
    file_count: Optional[int] = None


class KnowledgeUpdateForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class KnowledgeForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class KnowledgeTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(Knowledge).filter(Knowledge.name == name.strip())
            if exclude_id:
                query = query.filter(Knowledge.id != exclude_id)
            return query.first() is not None

    def next_clone_name(self, base: str, locale: str = "en") -> str:
        # Locale-aware suffix. Korean caller → "(복제본)", others → "(Clone)".
        suffix = "복제본" if (locale or "").lower().startswith("ko") else "Clone"
        candidate = f"{base} ({suffix})"
        if not self.name_exists(candidate):
            return candidate
        for n in range(2, 1001):
            candidate = f"{base} ({suffix} {n})"
            if not self.name_exists(candidate):
                return candidate
        # 1000 collisions — fall back to short uuid suffix to guarantee uniqueness.
        return f"{base} ({suffix} {uuid.uuid4().hex[:6]})"

    def insert_new_knowledge(
        self, user_id: str, form_data: KnowledgeForm
    ) -> Optional[KnowledgeModel]:
        with get_db() as db:
            knowledge = KnowledgeModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Knowledge(**knowledge.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return KnowledgeModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    def get_knowledge_bases(self) -> list[KnowledgeUserModel]:
        with get_db() as db:
            knowledge_bases = []
            for knowledge in (
                db.query(Knowledge).order_by(Knowledge.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(knowledge.user_id)
                knowledge_bases.append(
                    KnowledgeUserModel.model_validate(
                        {
                            **KnowledgeModel.model_validate(knowledge).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return knowledge_bases

    def get_knowledge_bases_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[KnowledgeUserModel]:
        knowledge_bases = self.get_knowledge_bases()
        return [
            knowledge_base
            for knowledge_base in knowledge_bases
            if knowledge_base.user_id == user_id
            or has_access(user_id, permission, knowledge_base.access_control)
        ]

    def get_knowledge_by_id(self, id: str) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = db.query(Knowledge).filter_by(id=id).first()
                return KnowledgeModel.model_validate(knowledge) if knowledge else None
        except Exception:
            return None

    def update_knowledge_by_id(
        self, id: str, form_data: KnowledgeForm, overwrite: bool = False
    ) -> Optional[KnowledgeModel]:
        try:
            with get_db() as db:
                knowledge = db.query(Knowledge).filter_by(id=id).first()
                if knowledge:
                    data = form_data.model_dump(exclude={"meta"}, exclude_none=True)
                    # access_control=None means "public" — exclude_none drops
                    # this, so re-add it whenever the client explicitly sent it.
                    if "access_control" in form_data.model_fields_set:
                        data["access_control"] = form_data.access_control
                    for key, value in data.items():
                        setattr(knowledge, key, value)
                    # Merge meta fields rather than overwriting
                    if form_data.meta is not None:
                        current_meta = dict(knowledge.meta) if knowledge.meta else {}
                        current_meta.update(form_data.meta)
                        knowledge.meta = current_meta
                    knowledge.updated_at = int(time.time())
                    db.commit()
                    db.refresh(knowledge)
                    return KnowledgeModel.model_validate(knowledge)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def update_knowledge_meta_by_id(
        self, id: str, meta_patch: dict
    ) -> Optional[KnowledgeModel]:
        # Merge meta_patch into existing meta. Used by clone worker to flip
        # clone_state without touching name/description/access_control.
        # ``with_for_update()`` row-lock 으로 read-modify-write 중첩 시
        # lost update 방지 — clone worker (백그라운드) 와 사용자 편집 (라우터)
        # 가 같은 KB 의 meta 를 동시에 갱신할 수 있으므로 필요.
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if knowledge:
                    current_meta = dict(knowledge.meta) if knowledge.meta else {}
                    current_meta.update(meta_patch)
                    knowledge.meta = current_meta
                    knowledge.updated_at = int(time.time())
                    db.commit()
                    db.refresh(knowledge)
                    return KnowledgeModel.model_validate(knowledge)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def update_knowledge_data_by_id(
        self, id: str, data: dict
    ) -> Optional[KnowledgeModel]:
        # data 컬럼 (file_ids, file_metadata) 도 라우터/워커 동시 갱신
        # 가능 영역이라 row-lock 적용.
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if knowledge:
                    knowledge.data = data
                    knowledge.updated_at = int(time.time())
                    db.commit()
                    db.refresh(knowledge)
                    return KnowledgeModel.model_validate(knowledge)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def add_file_id_to_knowledge(
        self, id: str, file_id: str
    ) -> Optional[KnowledgeModel]:
        """Atomically add a file_id to knowledge's file_ids list"""
        try:
            with get_db() as db:
                # Use with_for_update() for row-level locking
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if knowledge:
                    # Create a new dict to ensure SQLAlchemy detects the change
                    data = dict(knowledge.data) if knowledge.data else {}
                    file_ids = list(data.get("file_ids", []))
                    if file_id not in file_ids:
                        file_ids.append(file_id)
                        data["file_ids"] = file_ids
                        knowledge.data = data
                        knowledge.updated_at = int(time.time())
                    db.commit()
                    db.refresh(knowledge)
                    return KnowledgeModel.model_validate(knowledge)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def compact_file_ids(
        self, id: str, valid_ids: Optional[set[str]] = None
    ) -> Optional[tuple[KnowledgeModel, int, int]]:
        """knowledge.data.file_ids 를 치료 — 중복 제거 + (선택) orphan 제거.

        ``valid_ids`` 가 주어지면 그 set 에 속한 ID 만 유지. (일반적으로
        ``Files.get_files_by_ids(file_ids)`` 결과의 ID set 을 전달한다.)

        Returns ``(knowledge, before_len, after_len)``. 변경이 없으면 before==after.
        파일 삭제 경로가 놓친 상황이나 과거 중복 append 흔적을 한 번의 read
        작업 틈에 조용히 정리하기 위한 헬퍼.
        """
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if not knowledge:
                    return None
                data = dict(knowledge.data) if knowledge.data else {}
                original = list(data.get("file_ids", []))
                seen: set[str] = set()
                cleaned: list[str] = []
                for fid in original:
                    if not isinstance(fid, str) or not fid:
                        continue
                    if valid_ids is not None and fid not in valid_ids:
                        continue
                    if fid in seen:
                        continue
                    seen.add(fid)
                    cleaned.append(fid)
                before_len = len(original)
                after_len = len(cleaned)
                if before_len != after_len:
                    data["file_ids"] = cleaned
                    knowledge.data = data
                    knowledge.updated_at = int(time.time())
                    db.commit()
                    db.refresh(knowledge)
                return KnowledgeModel.model_validate(knowledge), before_len, after_len
        except Exception as e:
            log.exception(e)
            return None

    def update_knowledge_file_metadata(
        self, id: str, file_id: str, metadata: dict
    ) -> Optional[KnowledgeModel]:
        """파일별 필터 메타데이터를 knowledge.data.file_metadata에 저장"""
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if knowledge:
                    data = dict(knowledge.data) if knowledge.data else {}
                    file_metadata = dict(data.get("file_metadata", {}))
                    file_metadata[file_id] = metadata
                    data["file_metadata"] = file_metadata
                    knowledge.data = data
                    knowledge.updated_at = int(time.time())
                    db.commit()
                    db.refresh(knowledge)
                    return KnowledgeModel.model_validate(knowledge)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def patch_knowledge_file_metadata(
        self, id: str, file_id: str, delta: dict
    ) -> Optional[tuple]:
        """파일별 메타데이터를 원자적으로 merge. ``delta`` 의 키만 덮어쓰고
        나머지는 보존.

        slot 키 (``f_str_*`` / ``f_int_*`` / ``f_date_*`` / ``f_col_*``) 에 대해
        값이 ``None`` 이면 해당 slot 을 metadata 에서 제거한다 (clear).

        read-modify-write 를 단일 row-lock 트랜잭션 안에서 수행하므로
        여러 워커가 동시에 다른 file_id 를 업데이트할 때 lost update 가 없다.

        Returns:
            (KnowledgeModel, merged_metadata) — merged_metadata 는 저장된 dict
            사본. 이후 벡터 인덱스 갱신에 그대로 재사용 가능.
        """
        try:
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if not knowledge:
                    return None

                data = dict(knowledge.data) if knowledge.data else {}
                file_metadata = dict(data.get("file_metadata", {}))
                current = dict(file_metadata.get(file_id, {}))

                for k, v in (delta or {}).items():
                    if v is None and k.startswith(
                        ("f_str_", "f_int_", "f_date_", "f_col_")
                    ):
                        current.pop(k, None)
                    else:
                        current[k] = v

                file_metadata[file_id] = current
                data["file_metadata"] = file_metadata
                knowledge.data = data
                knowledge.updated_at = int(time.time())
                db.commit()
                db.refresh(knowledge)
                return (KnowledgeModel.model_validate(knowledge), current)
        except Exception as e:
            log.exception(e)
            return None

    def clear_knowledge_file_metadata_slots(
        self, id: str, file_ids: list[str]
    ) -> Optional[tuple]:
        """주어진 파일들의 filter slot (``f_str_*``/``f_int_*``/``f_date_*``/
        ``f_col_*``) 만 일괄 제거. 비-slot 메타 (예: ``last_extracted_at``) 와
        chunk / embedding 은 보존.

        Returns:
            (KnowledgeModel, cleared_slot_keys_per_file) — 각 file_id 별 실제
            제거된 slot 키 dict. 호출자는 이 정보로 벡터 인덱스 slot 을 None
            으로 동기화한다.
        """
        try:
            cleared_per_file: dict[str, list[str]] = {}
            with get_db() as db:
                knowledge = (
                    db.query(Knowledge).filter_by(id=id).with_for_update().first()
                )
                if not knowledge:
                    return None

                data = dict(knowledge.data) if knowledge.data else {}
                file_metadata = dict(data.get("file_metadata", {}))
                slot_prefixes = ("f_str_", "f_int_", "f_date_", "f_col_")

                for file_id in file_ids:
                    current = dict(file_metadata.get(file_id, {}))
                    cleared = [k for k in current if k.startswith(slot_prefixes)]
                    for k in cleared:
                        current.pop(k, None)
                    file_metadata[file_id] = current
                    if cleared:
                        cleared_per_file[file_id] = cleared

                data["file_metadata"] = file_metadata
                knowledge.data = data
                knowledge.updated_at = int(time.time())
                db.commit()
                db.refresh(knowledge)
                return (KnowledgeModel.model_validate(knowledge), cleared_per_file)
        except Exception as e:
            log.exception(e)
            return None

    def delete_knowledge_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                knowledge = db.query(Knowledge).filter_by(id=id).first()
                if knowledge:
                    db.delete(knowledge)
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def delete_all_knowledge(self) -> bool:
        with get_db() as db:
            try:
                db.query(Knowledge).delete()
                db.commit()

                return True
            except Exception:
                return False


Knowledges = KnowledgeTable()
