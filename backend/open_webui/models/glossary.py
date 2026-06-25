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
from sqlalchemy.orm import load_only

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Glossary DB Schema
####################


class Glossary(Base):
    __tablename__ = "glossary"

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
    # - Custom permissions: read/write 2-level with group/user/org_unit axes.
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"],
    #          "org_unit_ids": ["org_unit_id1"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"],
    #          "org_unit_ids": ["org_unit_id1"]
    #      }
    #   }

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class GlossaryModel(BaseModel):
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


class GlossaryUserModel(GlossaryModel):
    user: Optional[UserResponse] = None


class GlossaryResponse(GlossaryModel):
    pass


class GovernanceMeta(BaseModel):
    """글로서리 운영주체 표시용 derived 메타.

    응답 hydrate 단계에서 access_control + 사용자의 그룹 멤버십을 조합해 생성.
    DB 컬럼 아님 — governance_ux Phase 1에서 도입.
    """

    scope_kind: str  # "public" | "group" | "private" | "shared"
    scope_label: str  # i18n key 또는 그룹명 직접
    steward_group_name: Optional[str] = None
    is_owner: bool = False
    can_write: bool = False
    is_my_group: bool = False


class GlossaryUserResponse(GlossaryUserModel):
    governance_meta: Optional[GovernanceMeta] = None


class GlossaryForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class GlossaryCopyForm(BaseModel):
    """글로서리 fork. target_group_id 없음 = 비공개({}) 강제."""

    name: Optional[str] = None
    target_group_id: Optional[str] = None


class GlossaryTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(Glossary).filter(Glossary.name == name.strip())
            if exclude_id:
                query = query.filter(Glossary.id != exclude_id)
            return query.first() is not None

    def insert_new_glossary(
        self, user_id: str, form_data: GlossaryForm
    ) -> Optional[GlossaryModel]:
        with get_db() as db:
            glossary = GlossaryModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Glossary(**glossary.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return GlossaryModel.model_validate(result)
                else:
                    return None
            except Exception:
                return None

    def get_glossaries(self) -> list[GlossaryUserModel]:
        with get_db() as db:
            glossaries = []
            for glossary in (
                db.query(Glossary).order_by(Glossary.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(glossary.user_id)
                glossaries.append(
                    GlossaryUserModel.model_validate(
                        {
                            **GlossaryModel.model_validate(glossary).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return glossaries

    def get_glossaries_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[GlossaryUserModel]:
        glossaries = self.get_glossaries()
        return [
            glossary
            for glossary in glossaries
            if glossary.user_id == user_id
            or has_access(user_id, permission, glossary.access_control)
        ]

    def get_glossary_by_id(self, id: str) -> Optional[GlossaryModel]:
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                return GlossaryModel.model_validate(glossary) if glossary else None
        except Exception:
            return None

    def update_glossary_by_id(
        self, id: str, form_data: GlossaryForm, overwrite: bool = False
    ) -> Optional[GlossaryModel]:
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if glossary:
                    # exclude_unset: 클라이언트가 명시적으로 보낸 필드만 갱신.
                    # access_control=None(공개 전환) 같이 None 으로 덮어써야 하는 케이스를
                    # exclude_none 으로 누락하지 않도록 한다.
                    updates = form_data.model_dump(exclude_unset=True)
                    for key, value in updates.items():
                        setattr(glossary, key, value)

                    # data.entries 가 함께 갱신됐다면 meta.categories 도 재계산해야
                    # /categories 엔드포인트가 stale 데이터를 반환하지 않는다.
                    # form_data.meta 가 같이 들어온 경우(예: tool_description 만 수정)는
                    # 위 setattr 에서 meta 통째로 덮어쓴 상태이므로 그 위에 재계산값을 얹는다.
                    if "data" in updates:
                        entries = list((updates.get("data") or {}).get("entries") or [])
                        self._set_categories_meta(glossary, entries)

                    glossary.updated_at = int(time.time())
                    db.commit()
                    db.refresh(glossary)
                    return GlossaryModel.model_validate(glossary)
                return None
        except Exception as e:
            log.exception(e)
            return None

    @staticmethod
    def _collect_categories(entries: list[dict]) -> list[str]:
        """entries 에서 고유 카테고리 정렬 목록을 추출."""
        return sorted({e.get("category") for e in entries if e.get("category")})

    def _set_categories_meta(self, glossary: Glossary, entries: list[dict]) -> None:
        """data.entries 변경 직후 meta.categories 를 재계산해서 저장.

        호출자는 같은 트랜잭션 안에서 commit 해야 한다. /categories 엔드포인트가
        이 메타만 읽어서 응답하므로 entries 전체 스캔을 피할 수 있다.
        """
        new_meta = dict(glossary.meta or {})
        new_meta["categories"] = self._collect_categories(entries)
        glossary.meta = new_meta

    def set_index_state(self, id: str, state: Optional[dict]) -> bool:
        """meta.last_index_state 를 patch (검색 인덱싱 결과 기록).

        BackgroundTask 로 호출되는 인덱싱이 silent 하게 실패하면 DB(entries)와
        search index 가 영구 불일치가 된다. 호출자가 결과(성공/부분/실패)를 이
        필드에 기록해 두면 UI 가 알림을 띄울 수 있다 (followup).

        state=None 이면 키를 제거 (정상 인덱싱 후 cleanup).
        ``updated_at`` 은 갱신하지 않는다 — optimistic version check 와 무관.

        **Concurrency note**: 동일 glossary 에 대한 동시 호출은 마지막 write 가
        승리한다. BackgroundTask 단일 흐름을 전제로 한다. 다중 흐름이 발생하면
        stale state 가 박힐 수 있어 followup 으로 ts 기반 monotonic 비교 필요.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return False
                new_meta = dict(glossary.meta or {})
                if state is None:
                    new_meta.pop("last_index_state", None)
                else:
                    new_meta["last_index_state"] = state
                glossary.meta = new_meta
                db.commit()
                return True
        except Exception as e:
            log.exception("set_index_state failed for %s: %s", id, e)
            return False

    def update_glossary_data_by_id(
        self, id: str, data: dict
    ) -> Optional[GlossaryModel]:
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if glossary:
                    glossary.data = data
                    self._set_categories_meta(glossary, list(data.get("entries") or []))
                    glossary.updated_at = int(time.time())
                    db.commit()
                    db.refresh(glossary)
                    return GlossaryModel.model_validate(glossary)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def get_categories(
        self, id: str, user_id: str, is_admin: bool
    ) -> Optional[list[str]]:
        """meta.categories 만 읽어서 카테고리 목록 반환.

        - data 컬럼(=entries 전체)을 건드리지 않아 5천 건짜리 글로서리도 즉시 응답
        - 권한 체크도 같이 수행 (id/user_id/access_control/meta 컬럼만 로드)
        - 메타에 categories 키가 없으면(레거시 데이터) 한 번만 풀스캔 + 저장 후 반환
        - 글로서리 없음/권한 없음 시 None
        """
        try:
            with get_db() as db:
                glossary = (
                    db.query(Glossary)
                    .options(
                        load_only(
                            Glossary.id,
                            Glossary.user_id,
                            Glossary.access_control,
                            Glossary.meta,
                        )
                    )
                    .filter_by(id=id)
                    .first()
                )
                if not glossary:
                    return None
                if not (
                    is_admin
                    or glossary.user_id == user_id
                    or has_access(user_id, "read", glossary.access_control)
                ):
                    return None

                meta = glossary.meta or {}
                cats = meta.get("categories")
                if cats is not None:
                    return list(cats)

                # 레거시: meta.categories 가 아직 없는 글로서리는 한 번 backfill.
                # data 컬럼이 deferred 라 여기서 lazy load 됨 — 1회성 비용.
                entries = list((glossary.data or {}).get("entries") or [])
                cats_list = self._collect_categories(entries)
                self._set_categories_meta(glossary, entries)
                db.commit()
                return cats_list
        except Exception as e:
            log.exception(e)
            return None

    def set_extract_job(self, id: str, job: Optional[dict]) -> Optional[GlossaryModel]:
        """meta.extract_job 전체 교체. None 전달 시 키 제거."""
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                meta = dict(glossary.meta or {})
                if job is None:
                    meta.pop("extract_job", None)
                else:
                    meta["extract_job"] = job
                glossary.meta = meta
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return GlossaryModel.model_validate(glossary)
        except Exception as e:
            log.exception(e)
            return None

    def patch_extract_job(self, id: str, patch: dict) -> Optional[dict]:
        """meta.extract_job 부분 갱신. 점 표기(`progress.current`)를 nested set으로 처리."""
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                meta = dict(glossary.meta or {})
                job = dict(meta.get("extract_job") or {})
                for k, v in patch.items():
                    if "." in k:
                        parts = k.split(".")
                        cur = job
                        for p in parts[:-1]:
                            if not isinstance(cur.get(p), dict):
                                cur[p] = {}
                            cur = cur[p]
                        cur[parts[-1]] = v
                    else:
                        job[k] = v
                meta["extract_job"] = job
                glossary.meta = meta
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return job
        except Exception as e:
            log.exception(e)
            return None

    def get_category_definitions(self, id: str) -> dict:
        """meta.category_definitions 를 dict 로 반환.

        KG 동기화 시 KB 문서 매칭에 사용하는 카테고리 정의 캐시. 키는 카테고리
        이름이며, 값은 `{definition, sample_terms, generated_at, model_id}` 형태.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return {}
                return dict((glossary.meta or {}).get("category_definitions") or {})
        except Exception as e:
            log.exception(e)
            return {}

    def set_category_definition(
        self, id: str, category: str, definition: dict
    ) -> Optional[GlossaryModel]:
        """meta.category_definitions[category] 에 LLM 이 생성한 카테고리 설명 저장.

        용어집 carrier 측 캐시 — 한 번 생성되면 카테고리가 rename/delete 되기
        전까지 재사용된다. 값 스키마:
            {
                "definition": str,           # LLM 이 생성한 1~2문장 설명
                "sample_terms": list[str],   # 생성에 사용한 랜덤 샘플 용어
                "generated_at": int,         # epoch seconds
                "model_id": str,             # 사용 모델 id
            }
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                meta = dict(glossary.meta or {})
                definitions = dict(meta.get("category_definitions") or {})
                definitions[category] = definition
                meta["category_definitions"] = definitions
                glossary.meta = meta
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return GlossaryModel.model_validate(glossary)
        except Exception as e:
            log.exception(e)
            return None

    def clear_category_definition(
        self, id: str, category: Optional[str] = None
    ) -> Optional[GlossaryModel]:
        """카테고리 정의 캐시 무효화.

        ``category`` 가 주어지면 해당 카테고리만, 없으면 전체 제거. 카테고리
        rename/delete 시 호출해 stale 한 정의가 남지 않도록 한다.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                meta = dict(glossary.meta or {})
                definitions = dict(meta.get("category_definitions") or {})
                if category is None:
                    definitions = {}
                else:
                    definitions.pop(category, None)
                meta["category_definitions"] = definitions
                glossary.meta = meta
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return GlossaryModel.model_validate(glossary)
        except Exception as e:
            log.exception(e)
            return None

    def set_extraction_source(
        self, id: str, category: str, source: dict
    ) -> Optional[GlossaryModel]:
        """meta.extraction_sources[category] 에 출처(dbsphere_id/table/column 등) 기록.

        같은 카테고리를 다른 컬럼으로 재추출하면 덮어쓴다 — 카테고리 = 단일 출처.
        KG 동기화 등에서 이 메타를 읽어 TERM↔COLUMN 엣지를 생성한다.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                meta = dict(glossary.meta or {})
                sources = dict(meta.get("extraction_sources") or {})
                sources[category] = source
                meta["extraction_sources"] = sources
                glossary.meta = meta
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return GlossaryModel.model_validate(glossary)
        except Exception as e:
            log.exception(e)
            return None

    def rename_category(
        self, id: str, from_name: str, to_name: str
    ) -> Optional[list[dict]]:
        """카테고리 이름을 일괄 변경. 변경된 entry 리스트 반환 (인덱싱용).

        - data.entries 에서 category == from_name 인 항목들의 category 를 to_name 으로 교체.
        - meta.extraction_sources[from_name] 도 to_name 으로 키 이동.
        - 충돌 검증(to_name 이 다른 entry 에 이미 있는지)은 호출 측에서 수행.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                data = dict(glossary.data or {})
                entries = list(data.get("entries") or [])
                changed: list[dict] = []
                now = int(time.time())
                for i, e in enumerate(entries):
                    if e.get("category") == from_name:
                        merged = dict(e)
                        merged["category"] = to_name
                        merged["updated_at"] = now
                        entries[i] = merged
                        changed.append(merged)
                data["entries"] = entries
                glossary.data = data

                meta = dict(glossary.meta or {})
                sources = dict(meta.get("extraction_sources") or {})
                if from_name in sources:
                    sources[to_name] = sources.pop(from_name)
                    meta["extraction_sources"] = sources
                # 카테고리 정의 캐시도 함께 이름 이동 (stale 정의 방지)
                definitions = dict(meta.get("category_definitions") or {})
                if from_name in definitions:
                    definitions[to_name] = definitions.pop(from_name)
                    meta["category_definitions"] = definitions
                meta["categories"] = self._collect_categories(entries)
                glossary.meta = meta

                glossary.updated_at = now
                db.commit()
                db.refresh(glossary)
                return changed
        except Exception as e:
            log.exception(e)
            return None

    def delete_category(
        self,
        id: str,
        name: Optional[str],
        keep_entries: bool = False,
    ) -> Optional[list[dict]]:
        """카테고리 삭제. 변경된 entry 리스트 반환 (검색 인덱싱 갱신용).

        - ``name`` 이 None 또는 빈 문자열이면 uncategorized entries 를 삭제
          (``keep_entries`` 무시 — uncategorized 는 보존할 의미 없음).
        - ``name`` 이 있고 ``keep_entries=False`` (기본): 해당 카테고리 entries 모두 삭제.
        - ``name`` 이 있고 ``keep_entries=True``: entries 의 ``category`` 필드만 제거
          (entries 는 uncategorized 로 이동).
        - 메타(extraction_sources / category_definitions / categories) 는 항상 일관 정리.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                data = dict(glossary.data or {})
                entries = list(data.get("entries") or [])
                target_uncategorized = not name
                # uncategorized 삭제는 항상 entries 제거 (keep_entries 의미 없음)
                effective_keep = keep_entries and not target_uncategorized

                changed: list[dict] = []
                remaining: list[dict] = []
                now = int(time.time())
                for e in entries:
                    cat = e.get("category")
                    match = (not cat) if target_uncategorized else (cat == name)
                    if not match:
                        remaining.append(e)
                        continue
                    if effective_keep:
                        merged = dict(e)
                        merged.pop("category", None)
                        merged["updated_at"] = now
                        remaining.append(merged)
                        changed.append(merged)
                    else:
                        changed.append(e)

                data["entries"] = remaining
                glossary.data = data

                meta = dict(glossary.meta or {})
                if name:
                    sources = dict(meta.get("extraction_sources") or {})
                    if name in sources:
                        sources.pop(name, None)
                        meta["extraction_sources"] = sources
                    definitions = dict(meta.get("category_definitions") or {})
                    if name in definitions:
                        definitions.pop(name, None)
                        meta["category_definitions"] = definitions
                self._set_categories_meta(glossary, remaining)

                glossary.updated_at = now
                db.commit()
                db.refresh(glossary)
                return changed
        except Exception as e:
            log.exception(e)
            return None

    def get_extract_job(self, id: str) -> Optional[dict]:
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                return (glossary.meta or {}).get("extract_job")
        except Exception as e:
            log.exception(e)
            return None

    def add_entry(
        self, id: str, entry: dict, created_via: str = "manual"
    ) -> Optional[dict]:
        """용어집에 entry 하나 추가. 반환: 추가된 entry (id/timestamps 포함).

        Args:
            created_via: 항목 출처 (Hallucination 검수 워크플로우용).
                ``manual`` | ``json_import`` | ``file_import_no_ai`` |
                ``ai_rule`` | ``extract_db``.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                now = int(time.time())
                new_entry = {
                    "id": str(uuid.uuid4()),
                    "term": entry.get("term", "").strip(),
                    "synonyms": list(entry.get("synonyms") or []),
                    "description": entry.get("description", ""),
                    "example": entry.get("example", ""),
                    "category": entry.get("category") or None,
                    "created_via": created_via,
                    "created_at": now,
                    "updated_at": now,
                }
                data = dict(glossary.data or {})
                entries = list(data.get("entries") or [])
                entries.append(new_entry)
                data["entries"] = entries
                glossary.data = data
                self._set_categories_meta(glossary, entries)
                glossary.updated_at = now
                db.commit()
                db.refresh(glossary)
                return new_entry
        except Exception as e:
            log.exception(e)
            return None

    def update_entry(self, id: str, entry_id: str, patch: dict) -> Optional[dict]:
        """용어집 내 특정 entry 필드 갱신. 반환: 갱신된 entry 또는 None."""
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                data = dict(glossary.data or {})
                entries = list(data.get("entries") or [])
                updated = None
                for i, e in enumerate(entries):
                    if e.get("id") == entry_id:
                        merged = dict(e)
                        for k in (
                            "term",
                            "synonyms",
                            "description",
                            "example",
                            "category",
                        ):
                            if k in patch:
                                merged[k] = patch[k]
                        merged["updated_at"] = int(time.time())
                        entries[i] = merged
                        updated = merged
                        break
                if updated is None:
                    return None
                data["entries"] = entries
                glossary.data = data
                self._set_categories_meta(glossary, entries)
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return updated
        except Exception as e:
            log.exception(e)
            return None

    def delete_entry(self, id: str, entry_id: str) -> Optional[dict]:
        """용어집 내 특정 entry 삭제. 반환: 삭제된 entry (색인 제거용) 또는 None."""
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                data = dict(glossary.data or {})
                entries = list(data.get("entries") or [])
                removed = None
                remaining = []
                for e in entries:
                    if e.get("id") == entry_id and removed is None:
                        removed = e
                    else:
                        remaining.append(e)
                if removed is None:
                    return None
                data["entries"] = remaining
                glossary.data = data
                self._set_categories_meta(glossary, remaining)
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return removed
        except Exception as e:
            log.exception(e)
            return None

    def delete_entries(self, id: str, entry_ids: list[str]) -> Optional[list[dict]]:
        """용어집 내 다수 entry 일괄 삭제. 단일 트랜잭션. 반환: 삭제된 entry 리스트.

        매칭되지 않은 id 는 조용히 무시. data.entries 한 번 스캔으로 처리해
        N 회 round-trip 회피.
        """
        if not entry_ids:
            return []
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                data = dict(glossary.data or {})
                entries = list(data.get("entries") or [])
                target = set(entry_ids)
                removed: list[dict] = []
                remaining: list[dict] = []
                for e in entries:
                    if e.get("id") in target:
                        removed.append(e)
                        target.discard(e.get("id"))  # 같은 id 중복 방지
                    else:
                        remaining.append(e)
                if not removed:
                    return []
                data["entries"] = remaining
                glossary.data = data
                self._set_categories_meta(glossary, remaining)
                glossary.updated_at = int(time.time())
                db.commit()
                db.refresh(glossary)
                return removed
        except Exception as e:
            log.exception(e)
            return None

    def get_entries_paginated(
        self,
        id: str,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        sort: str = "name",
        category: Optional[str] = None,
        uncategorized: bool = False,
        categories: Optional[list[str]] = None,
        include_uncategorized: bool = False,
        created_via: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """용어집 entries 를 필터/정렬/페이징한 결과 반환.

        카테고리 필터 우선순위:
        1. ``categories`` (list) — 다중 선택 (멀티 셀렉트). 동시에 ``include_uncategorized=True``
           이면 카테고리가 없는 entries 도 포함.
        2. ``uncategorized=True`` — 카테고리 없는 entries 만 (단일 선택).
        3. ``category`` — 단일 카테고리만 (legacy).
        4. 모두 비어있으면 전체.

        Returns dict with ``entries`` (list), ``total`` (int), or None if glossary missing.
        """
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if not glossary:
                    return None
                entries: list[dict] = list((glossary.data or {}).get("entries") or [])

                # created_via 필터 (Hallucination 검수 워크플로우용).
                # 빈 list 또는 None → 필터 없음. legacy entries (created_via 없음) 매칭:
                # 'legacy' 가 created_via 에 포함되어 있어야 보임.
                if created_via:
                    allowed_cv = set(created_via)
                    entries = [
                        e
                        for e in entries
                        if (e.get("created_via") in allowed_cv)
                        or ("legacy" in allowed_cv and not e.get("created_via"))
                    ]

                # 멀티 셀렉트 활성화 조건: categories 가 명시적으로 전달됐거나
                # include_uncategorized 가 True. categories=[]+uncategorized=True 케이스
                # ("uncategorized 만 보고 싶음")도 정상 처리되어야 한다.
                if categories is not None or include_uncategorized:
                    allowed = set(categories or [])
                    entries = [
                        e
                        for e in entries
                        if (e.get("category") in allowed)
                        or (include_uncategorized and not e.get("category"))
                    ]
                elif uncategorized:
                    entries = [e for e in entries if not e.get("category")]
                elif category:
                    entries = [e for e in entries if e.get("category") == category]

                if search:
                    q = search.lower().strip()
                    if q:

                        def _match(e: dict) -> bool:
                            if q in (e.get("term") or "").lower():
                                return True
                            if q in (e.get("description") or "").lower():
                                return True
                            for s in e.get("synonyms") or []:
                                if isinstance(s, str) and q in s.lower():
                                    return True
                            return False

                        entries = [e for e in entries if _match(e)]

                if sort == "newest":
                    entries.sort(key=lambda e: e.get("created_at") or 0, reverse=True)
                elif sort == "oldest":
                    entries.sort(key=lambda e: e.get("created_at") or 0)
                else:  # name (default)
                    entries.sort(key=lambda e: (e.get("term") or "").lower())

                total = len(entries)
                sliced = entries[skip : skip + limit]
                return {"entries": sliced, "total": total}
        except Exception as e:
            log.exception(e)
            return None

    def get_active_extract_jobs_by_user(self, user_id: str) -> list[dict]:
        """이 사용자가 접근 가능한 용어집들 중 활성 추출 잡을 가진 것의 요약."""
        try:
            results: list[dict] = []
            for g in self.get_glossaries_by_user_id(user_id, permission="read"):
                meta = g.meta or {}
                job = meta.get("extract_job")
                if not job:
                    continue
                results.append(
                    {
                        "glossary_id": g.id,
                        "glossary_name": g.name,
                        "status": job.get("status"),
                        "phase": job.get("phase"),
                        "progress": job.get("progress"),
                        "started_at": job.get("started_at"),
                        "completed_at": job.get("completed_at"),
                    }
                )
            return results
        except Exception as e:
            log.exception(e)
            return []

    def delete_glossary_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                glossary = db.query(Glossary).filter_by(id=id).first()
                if glossary:
                    db.delete(glossary)
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def delete_all_glossaries(self) -> bool:
        with get_db() as db:
            try:
                db.query(Glossary).delete()
                db.commit()

                return True
            except Exception:
                return False

    def copy_glossary(
        self,
        source_id: str,
        new_user_id: str,
        new_user_name: str,
        name: Optional[str] = None,
        target_group_id: Optional[str] = None,
    ) -> Optional[GlossaryModel]:
        """글로서리 fork. entry id 모두 재발급 + meta.copied_from 기록.

        - target_group_id 있음 → access_control = {"read": {"group_ids": [tgt]}, "write": ...}
        - target_group_id 없음 → access_control = {} (비공개)
        - data.entries 의 각 entry 의 id 는 uuid 로 재발급 (검색 인덱스 충돌 방지)
        """
        try:
            with get_db() as db:
                source = db.query(Glossary).filter_by(id=source_id).first()
                if not source:
                    return None

                source_data = source.data or {}
                entries = source_data.get("entries", []) or []
                # entry id 재발급 (검색 인덱스 충돌 방지)
                new_entries = []
                for entry in entries:
                    new_entry = dict(entry)
                    new_entry["id"] = str(uuid.uuid4())
                    new_entries.append(new_entry)

                new_data = dict(source_data)
                new_data["entries"] = new_entries

                # meta: 원본 meta 보존하지 않고 copied_from 만 기록
                # (원본의 extract_job 등 상태가 fork 에 따라가면 안 됨)
                now = int(time.time())
                new_meta = {
                    "copied_from": {
                        "user_id": source.user_id,
                        "user_name": new_user_name,  # caller 입장 표기 — 원본 owner 이름은 라우터에서 보강 가능
                        "glossary_id": source.id,
                        "glossary_name": source.name,
                        "copied_at": now,
                    }
                }

                # access_control: target_group_id 우선
                if target_group_id:
                    new_ac: Optional[dict] = {
                        "read": {
                            "group_ids": [target_group_id],
                            "user_ids": [],
                            "org_unit_ids": [],
                        },
                        "write": {
                            "group_ids": [target_group_id],
                            "user_ids": [],
                            "org_unit_ids": [],
                        },
                    }
                else:
                    new_ac = {}  # 비공개

                new_glossary = Glossary(
                    id=str(uuid.uuid4()),
                    user_id=new_user_id,
                    name=(name or f"{source.name} (Copy)").strip(),
                    description=source.description or "",
                    data=new_data,
                    meta=new_meta,
                    access_control=new_ac,
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_glossary)
                db.commit()
                db.refresh(new_glossary)
                return GlossaryModel.model_validate(new_glossary)
        except Exception as e:
            log.exception(f"copy_glossary failed: {e}")
            return None


Glossaries = GlossaryTable()
