"""바이너리(PDF/Office) 본문 추출 헬퍼 — 기존 RAG ``Loader`` 재사용.

설계 (critique 반영):
- drive_get_content / gmail_get 의 바이너리 분기가 PDF/.docx/.xlsx/.pptx/ODF
  본문을 추출하기 위한 공통 헬퍼.  채팅 첨부가 이미 쓰는 ``Loader``
  (PyPDF/Docx2txt/UnstructuredExcel/PowerPoint + Tika/Docling/Document
  Intelligence/Mistral OCR) 를 그대로 재사용 — 신규 파서 없음.
- **[H3]** Loader 는 동기 + CPU/IO heavy → 전용 bounded ThreadPoolExecutor +
  semaphore 로 오프로드.  ``asyncio.to_thread`` (글로벌 default executor 공유) 금지.
- **[H2]** size 가드는 caller(tool) 가 메타 size 로 사전 차단 — 여기는 추출 후
  텍스트 cap(``MAX_EXTRACT_CHARS``) 만.  ``MAX_EXTRACT_BYTES`` 상수는 caller 용.
- **[P2]** ``extraction_config`` 는 unified_agent 가 ``request.app.state.config``
  에서 resolve 한 평문 dict — 이 모듈은 request 객체를 모른다.
- **[P6]** ``Loader`` 는 함수 내부 lazy import (top-level 이면 langchain_community
  전체를 도구 빌드 시점에 끌어옴).
- 이미지/스캔 OCR 은 범위 외 — ``is_extractable`` 화이트리스트에서 제외.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

log = logging.getLogger(__name__)

# LLM 컨텍스트 보호 — 추출 텍스트 출력 캡 (drive.py 의 _MAX_CONTENT_CHARS 와 동일).
MAX_EXTRACT_CHARS = 50000

# [H2] 다운로드/추출 대상 최대 크기.  caller(tool) 가 Drive 메타 ``size`` /
# Gmail attachment ``size`` 로 사전 차단하는 임계값.  초과 시 다운로드 자체를 skip.
MAX_EXTRACT_BYTES = int(
    os.environ.get("GOOGLE_EXTRACT_MAX_BYTES", str(20 * 1024 * 1024))
)

# [H3] Google 추출 전용 bounded executor + 동시성 상한 (글로벌 executor starvation 회피).
_EXTRACT_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("GOOGLE_EXTRACT_WORKERS", "4")),
    thread_name_prefix="gws_extract",
)
_EXTRACT_CONCURRENCY = int(os.environ.get("GOOGLE_EXTRACT_CONCURRENCY", "4"))
_EXTRACT_SEMAPHORE = asyncio.Semaphore(_EXTRACT_CONCURRENCY)

# 추출 가능한 비-native(=바이너리) MIME 화이트리스트.  Google native
# (vnd.google-apps.*) 는 drive.py 의 export 분기가 처리하므로 제외.
# 이미지(png/jpeg)·스캔은 OCR 범위 외라 제외.
_EXTRACTABLE_MIMES: frozenset[str] = frozenset(
    {
        "application/pdf",
        # MS Office (OpenXML)
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        # MS Office (legacy)
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        # OpenDocument
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
    }
)

# MIME → temp 파일 확장자 (unstructured/loader 가 확장자로 형식 판정할 수 있어 부여).
_MIME_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
}

# unified_agent 가 request.app.state.config 에서 떼어올 Loader kwargs 키
# (retrieval.py 의 Loader 생성부와 동일 집합).
_LOADER_KWARG_KEYS: tuple[str, ...] = (
    "TIKA_SERVER_URL",
    "DOCLING_SERVER_URL",
    "PDF_EXTRACT_IMAGES",
    "DOCUMENT_INTELLIGENCE_ENDPOINT",
    "DOCUMENT_INTELLIGENCE_KEY",
    "MISTRAL_OCR_API_KEY",
    "DOCUMENT_AI_PROJECT_ID",
    "DOCUMENT_AI_LOCATION",
    "DOCUMENT_AI_PROCESSOR_ID",
    "DOCUMENT_AI_PROCESSOR_VERSION",
    "DOCUMENT_AI_SERVICE_ACCOUNT_KEY",
    "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY",
)


def is_extractable(mime: Optional[str]) -> bool:
    """비-native 바이너리 MIME 이 본문 추출 화이트리스트에 있는지."""
    return bool(mime) and mime in _EXTRACTABLE_MIMES


def resolve_extraction_config(app_config: Any) -> Optional[dict]:
    """``request.app.state.config`` 에서 Loader 엔진/kwargs 를 평문 dict 로 resolve.

    [P2] builder 에 request 객체를 넘기지 않기 위해 unified_agent 가 이 함수로
    평문 값만 떼어 ``extraction_config`` 로 전달한다.  ``None`` 이면 추출 비활성
    (호출부가 metadata fallback).
    """
    if app_config is None:
        return None
    engine = getattr(app_config, "CONTENT_EXTRACTION_ENGINE", "") or ""
    loader_kwargs: dict[str, Any] = {}
    for key in _LOADER_KWARG_KEYS:
        default = False if key == "PDF_EXTRACT_IMAGES" else ""
        loader_kwargs[key] = getattr(app_config, key, default)
    return {"engine": engine, "loader_kwargs": loader_kwargs}


def _suffix_for(filename: Optional[str], mime: str) -> str:
    """temp 파일 확장자 — filename ext 우선, 없으면 MIME 매핑."""
    if filename:
        ext = os.path.splitext(filename)[1]
        if ext:
            return ext
    return _MIME_EXT.get(mime, "")


def _load_text_sync(
    filename: str, mime: str, path: str, extraction_config: dict
) -> str:
    """동기 Loader 호출 (executor 스레드에서 실행).  [P6] Loader lazy import."""
    from open_webui.retrieval.loaders.main import Loader

    loader = Loader(
        engine=extraction_config.get("engine", "") or "",
        **(extraction_config.get("loader_kwargs") or {}),
    )
    docs = loader.load(filename, mime, path)
    parts = [d.page_content for d in (docs or []) if getattr(d, "page_content", "")]
    return "\n\n".join(parts).strip()


async def extract_text_from_bytes(
    file_bytes: bytes,
    filename: str,
    mime: str,
    *,
    extraction_config: Optional[dict],
) -> dict:
    """바이너리 bytes → 텍스트 추출.  실패는 graceful(예외 전파 X).

    Returns:
        ``{"content": str, "truncated": bool}`` (성공) 또는
        ``{"content": "", "truncated": False, "error": "..."}`` (비활성/실패).
    """
    if not file_bytes:
        return {"content": "", "truncated": False}
    if not extraction_config:
        return {"content": "", "truncated": False, "error": "extraction_disabled"}

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=_suffix_for(filename, mime)
        ) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        loop = asyncio.get_running_loop()
        async with _EXTRACT_SEMAPHORE:
            text = await loop.run_in_executor(
                _EXTRACT_EXECUTOR,
                _load_text_sync,
                filename,
                mime,
                tmp_path,
                extraction_config,
            )
    except Exception as exc:  # 추출 실패는 LLM 친화 노트로 — 비즈니스 흐름 막지 않음.
        log.warning(
            "extract_text_from_bytes failed: file=%s mime=%s err=%s",
            filename,
            mime,
            exc,
        )
        return {"content": "", "truncated": False, "error": str(exc)[:200]}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    text = text or ""
    truncated = len(text) > MAX_EXTRACT_CHARS
    return {
        "content": text[:MAX_EXTRACT_CHARS] if truncated else text,
        "truncated": truncated,
    }


__all__ = [
    "MAX_EXTRACT_CHARS",
    "MAX_EXTRACT_BYTES",
    "is_extractable",
    "resolve_extraction_config",
    "extract_text_from_bytes",
]
