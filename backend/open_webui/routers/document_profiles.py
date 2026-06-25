import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.document_profile import (
    DocumentProfile,
    DocumentProfileForm,
    DocumentProfileModel,
    DocumentProfiles,
    ExtractionEngineProfile,
    ExtractionEngineProfiles,
)
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.crypto import mask_config_dict

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# Get all profiles (admin)
############################


@router.get("/", response_model=list[DocumentProfileModel])
async def get_document_profiles(user=Depends(get_admin_user)):
    return _mask_profiles(DocumentProfiles.get_profiles())


############################
# Get all profiles (for KB selector)
############################


@router.get("/list", response_model=list[DocumentProfileModel])
async def get_document_profile_list(user=Depends(get_verified_user)):
    return _mask_profiles(DocumentProfiles.get_profiles())


############################
# Get profile by id
############################


@router.get("/{id}", response_model=Optional[DocumentProfileModel])
async def get_document_profile_by_id(id: str, user=Depends(get_verified_user)):
    profile = DocumentProfiles.get_profile_by_id(id)
    if profile:
        return _mask_profile(profile)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# Create profile
############################


@router.post("/create", response_model=Optional[DocumentProfileModel])
async def create_document_profile(
    form_data: DocumentProfileForm, user=Depends(get_admin_user)
):
    _validate_extension_engine_map(form_data.extension_engine_map)
    _validate_default_engine_id(form_data.default_engine_id)
    _normalize_extension_engine_map(form_data)
    profile = DocumentProfiles.insert_new_profile(user.id, form_data)
    if profile:
        if form_data.is_default:
            DocumentProfiles.set_default_profile(profile.id)
            profile = DocumentProfiles.get_profile_by_id(profile.id)
        return profile
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error creating profile"),
    )


############################
# Update profile
############################


@router.post("/{id}/update", response_model=Optional[DocumentProfileModel])
async def update_document_profile_by_id(
    id: str,
    form_data: DocumentProfileForm,
    user=Depends(get_admin_user),
):
    profile = DocumentProfiles.get_profile_by_id(id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Resolve masked sensitive values
    if form_data.config and profile.config:
        from open_webui.utils.crypto import resolve_sensitive_value

        for key in form_data.config:
            form_data.config[key] = resolve_sensitive_value(
                form_data.config[key], profile.config.get(key, "")
            )

    _validate_extension_engine_map(form_data.extension_engine_map)
    _validate_default_engine_id(form_data.default_engine_id)
    _normalize_extension_engine_map(form_data)

    updated = DocumentProfiles.update_profile_by_id(id, form_data)
    if updated:
        return updated
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error updating profile"),
    )


############################
# Set default profile
############################


@router.post("/{id}/set-default", response_model=Optional[DocumentProfileModel])
async def set_default_document_profile(
    id: str,
    request: Request,
    user=Depends(get_admin_user),
):
    profile = DocumentProfiles.set_default_profile(id)
    if profile:
        # Sync global config with new default
        cfg = request.app.state.config
        cfg.CONTENT_EXTRACTION_ENGINE = profile.content_extraction_engine
        cfg.PDF_EXTRACT_IMAGES = profile.pdf_extract_images
        cfg.TEXT_SPLITTER = profile.text_splitter
        cfg.CHUNK_SIZE = profile.chunk_size
        cfg.CHUNK_OVERLAP = profile.chunk_overlap

        pc = profile.config or {}
        cfg.TIKA_SERVER_URL = pc.get("tika_server_url", cfg.TIKA_SERVER_URL)
        cfg.DOCLING_SERVER_URL = pc.get("docling_server_url", cfg.DOCLING_SERVER_URL)
        cfg.DOCUMENT_INTELLIGENCE_ENDPOINT = pc.get(
            "document_intelligence_endpoint",
            cfg.DOCUMENT_INTELLIGENCE_ENDPOINT,
        )
        cfg.DOCUMENT_INTELLIGENCE_KEY = pc.get(
            "document_intelligence_key", cfg.DOCUMENT_INTELLIGENCE_KEY
        )
        cfg.MISTRAL_OCR_API_KEY = pc.get("mistral_ocr_api_key", cfg.MISTRAL_OCR_API_KEY)
        cfg.DOCUMENT_AI_PROJECT_ID = pc.get(
            "document_ai_project_id", cfg.DOCUMENT_AI_PROJECT_ID
        )
        cfg.DOCUMENT_AI_LOCATION = pc.get(
            "document_ai_location", cfg.DOCUMENT_AI_LOCATION
        )
        cfg.DOCUMENT_AI_PROCESSOR_ID = pc.get(
            "document_ai_processor_id", cfg.DOCUMENT_AI_PROCESSOR_ID
        )
        cfg.DOCUMENT_AI_PROCESSOR_VERSION = pc.get(
            "document_ai_processor_version",
            cfg.DOCUMENT_AI_PROCESSOR_VERSION,
        )
        cfg.DOCUMENT_AI_SERVICE_ACCOUNT_KEY = pc.get(
            "document_ai_service_account_key",
            cfg.DOCUMENT_AI_SERVICE_ACCOUNT_KEY,
        )

        return profile
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error setting default profile"),
    )


############################
# Migrate legacy profile to extension_engine_map
############################


# 각 engine_type 이 지원하는 확장자 — extraction_engines 라우터의 동일 카탈로그와
# 일치해야 한다. 단일 source 로 가져오기보다 여기 명시한 이유: migrate-to-mapping
# 은 백엔드 내부 변환이라 외부 호출 없이 즉시 실행하기 위함.
_ENGINE_NATIVE_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
    ".html",
    ".htm",
    ".xml",
    ".md",
    ".txt",
    ".rst",
    ".epub",
    ".msg",
}
_ENGINE_PRIMARY_EXTENSIONS: dict[str, set[str]] = {
    "tika": _ENGINE_NATIVE_EXTENSIONS,
    "docling": {".pdf", ".docx", ".pptx", ".html", ".htm", ".md"},
    "document_intelligence": {
        ".pdf",
        ".xls",
        ".xlsx",
        ".docx",
        ".ppt",
        ".pptx",
    },
    "mistral_ocr": {".pdf"},
    "document_ai": {
        ".pdf",
        ".tiff",
        ".tif",
        ".gif",
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".webp",
        ".docx",
        ".xlsx",
        ".pptx",
    },
    "llm_vision": {".pdf", ".png", ".jpg", ".jpeg"},
    "native": _ENGINE_NATIVE_EXTENSIONS,
}


@router.post("/{id}/migrate-to-mapping", response_model=Optional[DocumentProfileModel])
async def migrate_profile_to_mapping(id: str, user=Depends(get_admin_user)):
    """Legacy 단일 엔진 프로파일을 확장자별 매핑으로 변환.

    동작:
      1. 현재 profile.content_extraction_engine + config 를 그대로 들고 있는
         ExtractionEngineProfile 1개 자동 생성 ("{name} - Primary").
         단 legacy engine 이 native/"" 였다면 생성하지 않음 (매핑은 빈 상태로
         두면 모두 기본 내장 엔진으로 동작).
      2. 해당 엔진이 지원하는 확장자만 그 엔진으로 매핑.
         매핑에 없는 확장자는 자동으로 기본 내장 엔진 사용 — 별도 sentinel 불필요.

    Legacy 컬럼(content_extraction_engine/config/pdf_extract_images) 은 비우지
    않음 — 코드 롤백 시 즉시 복구 가능하도록 보존.

    결과: 변환 후 동일 파일 셋이 동일 엔진으로 처리되어 회귀 0. 이후 관리자가
    UI 에서 매핑을 자유롭게 편집 가능.
    """
    profile = DocumentProfiles.get_profile_by_id(id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if profile.extension_engine_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile is already migrated.",
        )

    primary_engine_type = (profile.content_extraction_engine or "").strip()
    primary_config = profile.config or {}
    primary_exts = (
        _ENGINE_PRIMARY_EXTENSIONS.get(primary_engine_type, set())
        if primary_engine_type
        else set()
    )

    now = int(time.time())
    mapping: dict[str, str] = {}

    with get_db() as db:
        try:
            # 1. primary engine row (legacy engine 이 native/"" 가 아닐 때만)
            primary_id: Optional[str] = None
            if primary_engine_type and primary_engine_type != "native":
                primary_id = str(uuid.uuid4())
                db.add(
                    ExtractionEngineProfile(
                        id=primary_id,
                        user_id=user.id,
                        name=f"{profile.name} - Primary",
                        engine_type=primary_engine_type,
                        config=dict(primary_config),
                        pdf_extract_images=False,
                        created_at=now,
                        updated_at=now,
                    )
                )
                # 2. 매핑 구성: primary 가 지원하는 확장자만. 나머지는 default_engine_id
                #    (= primary) 로 fallback 되도록 default 도 primary 로 설정 —
                #    legacy 단일 엔진 프로파일의 "모든 파일이 이 엔진을 통과한다"
                #    의미를 보존.
                for ext in primary_exts:
                    mapping[ext] = primary_id

            # legacy 가 native 였다면 mapping/default 둘 다 비어있음 — 변환할 게
            # 없으므로 noop.
            if not mapping and not primary_id:
                return profile

            # 3. profile 업데이트
            row = db.query(DocumentProfile).filter_by(id=id).first()
            row.extension_engine_map = mapping or None
            row.default_engine_id = primary_id  # None 이면 기본 내장 엔진
            row.updated_at = now
            db.commit()
            db.refresh(row)
            return DocumentProfileModel.model_validate(row)
        except Exception as e:
            db.rollback()
            log.exception(e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT("Migration failed"),
            )


############################
# Delete profile
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_document_profile_by_id(id: str, user=Depends(get_admin_user)):
    profile = DocumentProfiles.get_profile_by_id(id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if profile.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                "Cannot delete the default profile. Set another profile as default first."
            ),
        )

    result = DocumentProfiles.delete_profile_by_id(id)
    if result:
        return True
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error deleting profile"),
    )


############################
# Helpers
############################


def _mask_profile(profile: DocumentProfileModel) -> DocumentProfileModel:
    if profile.config:
        masked = mask_config_dict(profile.config)
        return profile.model_copy(update={"config": masked})
    return profile


def _mask_profiles(
    profiles: list[DocumentProfileModel],
) -> list[DocumentProfileModel]:
    return [_mask_profile(p) for p in profiles]


def _normalize_extension_engine_map(form_data: DocumentProfileForm) -> None:
    """확장자 키를 소문자 + leading dot 으로 정규화. 빈 매핑은 None 으로 통일."""
    m = form_data.extension_engine_map
    if not m:
        form_data.extension_engine_map = None
        return
    normalized: dict[str, str] = {}
    for ext, engine_id in m.items():
        if not ext or not engine_id:
            continue
        key = ext.strip().lower()
        if not key.startswith("."):
            key = "." + key
        normalized[key] = engine_id
    form_data.extension_engine_map = normalized or None


NATIVE_ENGINE_SENTINEL = "native"


def _validate_extension_engine_map(mapping: Optional[dict]) -> None:
    """매핑 value 가 실제 ExtractionEngineProfile.id 또는 'native' sentinel
    인지 검증. 'native' 는 default_engine_id 와 무관하게 해당 확장자만 명시적
    으로 기본 내장 엔진으로 처리하라는 의미.
    빈 매핑은 허용 (관리자 점진 구성)."""
    if not mapping:
        return
    if not isinstance(mapping, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="extension_engine_map must be an object.",
        )
    engine_ids = {e.id for e in ExtractionEngineProfiles.get_engines()}
    missing = [
        eid
        for eid in mapping.values()
        if eid != NATIVE_ENGINE_SENTINEL and eid not in engine_ids
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown engine profile id(s) in mapping: {sorted(set(missing))}",
        )


def _validate_default_engine_id(default_engine_id: Optional[str]) -> None:
    """default_engine_id 가 실제 ExtractionEngineProfile.id 인지 검증.
    None/빈 값이면 기본 내장 엔진을 의미하므로 허용."""
    if not default_engine_id:
        return
    engine_ids = {e.id for e in ExtractionEngineProfiles.get_engines()}
    if default_engine_id not in engine_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown default_engine_id: {default_engine_id}",
        )
