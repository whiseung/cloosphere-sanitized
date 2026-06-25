"""Extraction Engine Profile 라우터.

문서 처리 프로파일의 "확장자 -> 엔진 매핑" 에서 value 로 참조되는 엔진 자격증명
단위. 같은 engine_type (예: document_intelligence) 의 여러 자격증명을 동시에
보유 가능 — DI Prod / DI Dev 같이 환경별 분리 시나리오 지원.

권한: 전부 admin-only. workspace 권한 분기 없음 (자격증명은 시스템 관리 자원).

엔진 타입 별 config 키 (Engine -> ExtractionEngineProfile.config):
  - native:                (옵션 없음. pdf_extract_images 는 별도 컬럼)
  - tika:                  tika_server_url
  - docling:               docling_server_url
  - document_intelligence: document_intelligence_endpoint,
                           document_intelligence_key
  - mistral_ocr:           mistral_ocr_api_key
  - document_ai:           document_ai_project_id, document_ai_location,
                           document_ai_processor_id,
                           document_ai_processor_version,
                           document_ai_service_account_key
  - llm_vision:            llm_vision_model, llm_vision_prompt
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.document_profile import (
    ExtractionEngineProfileForm,
    ExtractionEngineProfileModel,
    ExtractionEngineProfiles,
)
from open_webui.utils.auth import get_admin_user
from open_webui.utils.crypto import mask_config_dict, resolve_sensitive_value
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


# 등록 가능한 engine_type — Native 는 자격증명이 없어 row 로 저장할 필요가 없으며,
# 프로파일 매핑에서 "native" 리터럴 값으로 표현된다 (별도 행 불필요).
SUPPORTED_ENGINE_TYPES = {
    "tika",
    "docling",
    "document_intelligence",
    "mistral_ocr",
    "document_ai",
    "llm_vision",
}


############################
# Engine type metadata
############################


class EngineTypeMeta(BaseModel):
    type: str
    label: str
    supported_extensions: list[str]
    required_config_fields: list[str]
    optional_config_fields: list[str] = []
    # 엔진 타입별 기본 config 값 — UI 가 placeholder/초기값으로 노출.
    # 예: llm_vision 의 기본 추출 프롬프트 (빈 값이면 백엔드가 이 값으로 폴백).
    default_config: dict[str, str] = {}


_ENGINE_TYPES: list[EngineTypeMeta] = [
    EngineTypeMeta(
        type="tika",
        label="Apache Tika",
        supported_extensions=[],  # 거의 모든 포맷 — 빈 배열은 "all" 의미로 UI 가 해석
        required_config_fields=["tika_server_url"],
    ),
    EngineTypeMeta(
        type="docling",
        label="IBM Docling",
        supported_extensions=[".pdf", ".docx", ".pptx", ".html", ".htm", ".md"],
        required_config_fields=["docling_server_url"],
    ),
    EngineTypeMeta(
        type="document_intelligence",
        label="Azure AI Document Intelligence",
        supported_extensions=[".pdf", ".xls", ".xlsx", ".docx", ".ppt", ".pptx"],
        required_config_fields=[
            "document_intelligence_endpoint",
            "document_intelligence_key",
        ],
    ),
    EngineTypeMeta(
        type="mistral_ocr",
        label="Mistral OCR",
        supported_extensions=[".pdf"],
        required_config_fields=["mistral_ocr_api_key"],
    ),
    EngineTypeMeta(
        type="document_ai",
        label="Google Cloud Document AI",
        supported_extensions=[
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
        ],
        required_config_fields=["document_ai_processor_id"],
        optional_config_fields=[
            "document_ai_project_id",
            "document_ai_location",
            "document_ai_processor_version",
            "document_ai_service_account_key",
        ],
    ),
    EngineTypeMeta(
        type="llm_vision",
        label="LLM Vision",
        supported_extensions=[".pdf", ".png", ".jpg", ".jpeg"],
        required_config_fields=["llm_vision_model"],
        optional_config_fields=["llm_vision_prompt"],
    ),
]


@router.get("/engine-types", response_model=list[EngineTypeMeta])
async def get_engine_types(user=Depends(get_admin_user)):
    """UI 가 엔진 타입 별 자격증명 폼/확장자 카탈로그를 동적으로 그릴 수 있도록
    정적 메타 반환.

    llm_vision 은 기본 추출 프롬프트를 default_config 로 함께 노출한다 — UI 에서
    프롬프트를 '확인/수정' 할 수 있도록 (빈 값으로 저장하면 백엔드 로더가 이 기본값으로
    폴백). 기본 프롬프트 상수는 로더에 있으며, fitz 등 무거운 의존성은 로더 함수 내부에서만
    로드되므로 모듈 임포트 비용 없이 lazy import 한다."""
    from open_webui.retrieval.loaders.llm_vision import DEFAULT_EXTRACTION_PROMPT

    result: list[EngineTypeMeta] = []
    for meta in _ENGINE_TYPES:
        if meta.type == "llm_vision":
            result.append(
                meta.model_copy(
                    update={
                        "default_config": {
                            "llm_vision_prompt": DEFAULT_EXTRACTION_PROMPT
                        }
                    }
                )
            )
        else:
            result.append(meta)
    return result


############################
# CRUD
############################


@router.get("/", response_model=list[ExtractionEngineProfileModel])
async def list_extraction_engines(user=Depends(get_admin_user)):
    engines = ExtractionEngineProfiles.get_engines()
    return [_mask_engine(e) for e in engines]


@router.get("/{id}", response_model=Optional[ExtractionEngineProfileModel])
async def get_extraction_engine_by_id(id: str, user=Depends(get_admin_user)):
    engine = ExtractionEngineProfiles.get_engine_by_id(id)
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return _mask_engine(engine)


@router.post("/create", response_model=Optional[ExtractionEngineProfileModel])
async def create_extraction_engine(
    form_data: ExtractionEngineProfileForm,
    user=Depends(get_admin_user),
):
    _validate_engine_type(form_data.engine_type)
    engine = ExtractionEngineProfiles.insert_new_engine(user.id, form_data)
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating extraction engine"),
        )
    return _mask_engine(engine)


@router.post("/{id}/update", response_model=Optional[ExtractionEngineProfileModel])
async def update_extraction_engine(
    id: str,
    form_data: ExtractionEngineProfileForm,
    user=Depends(get_admin_user),
):
    existing = ExtractionEngineProfiles.get_engine_by_id(id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if form_data.engine_type is not None:
        _validate_engine_type(form_data.engine_type)

    # 클라이언트가 마스킹된 placeholder 를 그대로 보내면 기존 값 보존.
    if form_data.config and existing.config:
        for key in form_data.config:
            form_data.config[key] = resolve_sensitive_value(
                form_data.config[key], existing.config.get(key, "")
            )

    updated = ExtractionEngineProfiles.update_engine_by_id(id, form_data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating extraction engine"),
        )
    return _mask_engine(updated)


@router.delete("/{id}/delete", response_model=bool)
async def delete_extraction_engine(id: str, user=Depends(get_admin_user)):
    existing = ExtractionEngineProfiles.get_engine_by_id(id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )

    referencing = ExtractionEngineProfiles.get_referencing_profile_ids(id)
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Engine is referenced by {len(referencing)} profile(s). "
                "Remove the extension mappings first."
            ),
        )

    if ExtractionEngineProfiles.delete_engine_by_id(id):
        return True
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error deleting extraction engine"),
    )


############################
# Helpers
############################


def _validate_engine_type(engine_type: Optional[str]) -> None:
    if engine_type is None:
        return
    if engine_type not in SUPPORTED_ENGINE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported engine_type '{engine_type}'.",
        )


def _mask_engine(
    engine: ExtractionEngineProfileModel,
) -> ExtractionEngineProfileModel:
    if engine.config:
        masked = mask_config_dict(engine.config)
        return engine.model_copy(update={"config": masked})
    return engine
