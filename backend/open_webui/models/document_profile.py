import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Boolean, Column, Integer, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# DocumentProfile DB Schema
####################


class DocumentProfile(Base):
    __tablename__ = "document_profile"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    is_default = Column(Boolean, default=False)

    # NOTE: 아래 3개 컬럼은 legacy. extension_engine_map 이 채워지면 무시된다.
    # 다중 고객사 무중단 호환을 위해 즉시 drop 하지 않고 nullable 로 유지.
    content_extraction_engine = Column(Text, default="")
    pdf_extract_images = Column(Boolean, default=False)
    config = Column(JSON, nullable=True)

    text_splitter = Column(Text, default="")
    chunk_size = Column(Integer, default=1000)
    chunk_overlap = Column(Integer, default=100)

    # 확장자(소문자, leading dot 포함) -> ExtractionEngineProfile.id 매핑.
    # 비어 있거나 null 이면 legacy 경로(content_extraction_engine + config) 사용.
    extension_engine_map = Column(JSON, nullable=True)

    # 매핑에 없는 확장자의 기본 엔진. null 이면 기본 내장 엔진(engine_type="") 사용.
    default_engine_id = Column(Text, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class DocumentProfileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    is_default: bool = False

    content_extraction_engine: str = ""
    pdf_extract_images: bool = False

    text_splitter: str = ""
    chunk_size: int = 1000
    chunk_overlap: int = 100

    config: Optional[dict] = None
    extension_engine_map: Optional[dict] = None
    default_engine_id: Optional[str] = None

    created_at: int
    updated_at: int


####################
# Forms
####################


class DocumentProfileForm(BaseModel):
    name: str
    is_default: Optional[bool] = None
    content_extraction_engine: Optional[str] = None
    pdf_extract_images: Optional[bool] = None
    text_splitter: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    config: Optional[dict] = None
    extension_engine_map: Optional[dict] = None
    default_engine_id: Optional[str] = None


class DocumentProfileTable:
    def insert_new_profile(
        self, user_id: str, form_data: DocumentProfileForm
    ) -> Optional[DocumentProfileModel]:
        with get_db() as db:
            # Form 필드는 Optional=None.
            # - content_extraction_engine / pdf_extract_images / config 는 legacy
            #   컬럼 (extension_engine_map 사용 시 무시되지만 다중 고객사 무중단
            #   호환을 위해 DDL 유지 — 본 파일 상단 DocumentProfile NOTE 참조).
            #   exclude_none 으로 None 을 제거하면 Model strict 타입의 빈 기본값
            #   ("", False, None)이 자동 적용되어 DB 에 default 로 저장된다.
            # - 나머지 필드(text_splitter / chunk_size / chunk_overlap) 는 active
            #   컬럼이며 신 UI 가 명시적으로 채워 보낸다; 빠지면 Model 기본값.
            profile = DocumentProfileModel(
                **{
                    **form_data.model_dump(exclude_none=True),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = DocumentProfile(**profile.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return DocumentProfileModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(e)
                return None

    def get_profiles(self) -> list[DocumentProfileModel]:
        with get_db() as db:
            return [
                DocumentProfileModel.model_validate(p)
                for p in db.query(DocumentProfile)
                .order_by(
                    DocumentProfile.is_default.desc(),
                    DocumentProfile.updated_at.desc(),
                )
                .all()
            ]

    def get_profile_by_id(self, id: str) -> Optional[DocumentProfileModel]:
        try:
            with get_db() as db:
                profile = db.query(DocumentProfile).filter_by(id=id).first()
                return DocumentProfileModel.model_validate(profile) if profile else None
        except Exception:
            return None

    def get_default_profile(self) -> Optional[DocumentProfileModel]:
        try:
            with get_db() as db:
                profile = db.query(DocumentProfile).filter_by(is_default=True).first()
                return DocumentProfileModel.model_validate(profile) if profile else None
        except Exception:
            return None

    def update_profile_by_id(
        self, id: str, form_data: DocumentProfileForm
    ) -> Optional[DocumentProfileModel]:
        try:
            with get_db() as db:
                profile = db.query(DocumentProfile).filter_by(id=id).first()
                if profile:
                    # 일반 필드: None 은 "변경 없음" 으로 해석.
                    for key, value in form_data.model_dump(
                        exclude_none=True,
                        exclude={
                            "is_default",
                            "extension_engine_map",
                            "default_engine_id",
                        },
                    ).items():
                        setattr(profile, key, value)
                    # 매핑/기본 엔진: None 도 "지움" 으로 의미 있음. 클라이언트가
                    # 명시적으로 필드를 보냈으면 (model_fields_set) 그대로 반영.
                    fields_set = form_data.model_fields_set
                    if "extension_engine_map" in fields_set:
                        profile.extension_engine_map = form_data.extension_engine_map
                    if "default_engine_id" in fields_set:
                        profile.default_engine_id = form_data.default_engine_id
                    profile.updated_at = int(time.time())
                    db.commit()
                    db.refresh(profile)
                    return DocumentProfileModel.model_validate(profile)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def set_default_profile(self, id: str) -> Optional[DocumentProfileModel]:
        try:
            with get_db() as db:
                # Clear all defaults
                db.query(DocumentProfile).filter(
                    DocumentProfile.is_default == True  # noqa: E712
                ).update({"is_default": False})
                # Set the new default
                profile = db.query(DocumentProfile).filter_by(id=id).first()
                if profile:
                    profile.is_default = True
                    profile.updated_at = int(time.time())
                    db.commit()
                    db.refresh(profile)
                    return DocumentProfileModel.model_validate(profile)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def delete_profile_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                profile = db.query(DocumentProfile).filter_by(id=id).first()
                if profile:
                    if profile.is_default:
                        return False
                    db.delete(profile)
                    db.commit()
                    return True
                return False
        except Exception:
            return False


DocumentProfiles = DocumentProfileTable()


####################
# ExtractionEngineProfile DB Schema
####################


class ExtractionEngineProfile(Base):
    __tablename__ = "extraction_engine_profile"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    # "native" / "tika" / "docling" / "document_intelligence" / "mistral_ocr"
    # / "document_ai" / "llm_vision"
    engine_type = Column(Text, default="")

    # engine_type 별 자격증명/옵션:
    #  - tika:                  TIKA_SERVER_URL
    #  - docling:               DOCLING_SERVER_URL
    #  - document_intelligence: DOCUMENT_INTELLIGENCE_ENDPOINT,
    #                           DOCUMENT_INTELLIGENCE_KEY
    #  - mistral_ocr:           MISTRAL_OCR_API_KEY
    #  - document_ai:           DOCUMENT_AI_PROJECT_ID, DOCUMENT_AI_LOCATION,
    #                           DOCUMENT_AI_PROCESSOR_ID,
    #                           DOCUMENT_AI_PROCESSOR_VERSION,
    #                           DOCUMENT_AI_SERVICE_ACCOUNT_KEY
    #  - llm_vision:            LLM_VISION_MODEL, LLM_VISION_PROMPT
    config = Column(JSON, nullable=True)

    # engine_type == "native" 일 때만 의미. UnstructuredPDFLoader 의 ocr 옵션 등.
    pdf_extract_images = Column(Boolean, default=False)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class ExtractionEngineProfileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    engine_type: str = ""
    config: Optional[dict] = None
    pdf_extract_images: bool = False

    created_at: int
    updated_at: int


class ExtractionEngineProfileForm(BaseModel):
    name: str
    engine_type: Optional[str] = None
    config: Optional[dict] = None
    pdf_extract_images: Optional[bool] = None


class ExtractionEngineProfileTable:
    def insert_new_engine(
        self, user_id: str, form_data: ExtractionEngineProfileForm
    ) -> Optional[ExtractionEngineProfileModel]:
        with get_db() as db:
            engine = ExtractionEngineProfileModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "engine_type": form_data.engine_type or "",
                    "pdf_extract_images": form_data.pdf_extract_images or False,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = ExtractionEngineProfile(**engine.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                return ExtractionEngineProfileModel.model_validate(result)
            except Exception as e:
                log.exception(e)
                return None

    def get_engines(self) -> list[ExtractionEngineProfileModel]:
        with get_db() as db:
            return [
                ExtractionEngineProfileModel.model_validate(e)
                for e in db.query(ExtractionEngineProfile)
                .order_by(ExtractionEngineProfile.updated_at.desc())
                .all()
            ]

    def get_engine_by_id(self, id: str) -> Optional[ExtractionEngineProfileModel]:
        try:
            with get_db() as db:
                engine = db.query(ExtractionEngineProfile).filter_by(id=id).first()
                return (
                    ExtractionEngineProfileModel.model_validate(engine)
                    if engine
                    else None
                )
        except Exception:
            return None

    def update_engine_by_id(
        self, id: str, form_data: ExtractionEngineProfileForm
    ) -> Optional[ExtractionEngineProfileModel]:
        try:
            with get_db() as db:
                engine = db.query(ExtractionEngineProfile).filter_by(id=id).first()
                if not engine:
                    return None
                for key, value in form_data.model_dump(exclude_none=True).items():
                    setattr(engine, key, value)
                engine.updated_at = int(time.time())
                db.commit()
                db.refresh(engine)
                return ExtractionEngineProfileModel.model_validate(engine)
        except Exception as e:
            log.exception(e)
            return None

    def delete_engine_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                engine = db.query(ExtractionEngineProfile).filter_by(id=id).first()
                if not engine:
                    return False
                db.delete(engine)
                db.commit()
                return True
        except Exception:
            return False

    def get_referencing_profile_ids(self, engine_id: str) -> list[str]:
        """이 engine_id 를 참조하는 모든 document_profile.id 목록.
        extension_engine_map 의 value 또는 default_engine_id 어느 쪽이든.
        삭제 가드용."""
        try:
            with get_db() as db:
                rows = db.query(DocumentProfile).all()
                referencing: list[str] = []
                for r in rows:
                    mapping = r.extension_engine_map or {}
                    if isinstance(mapping, dict) and engine_id in mapping.values():
                        referencing.append(r.id)
                        continue
                    if r.default_engine_id == engine_id:
                        referencing.append(r.id)
                return referencing
        except Exception as e:
            log.exception(e)
            return []


ExtractionEngineProfiles = ExtractionEngineProfileTable()
