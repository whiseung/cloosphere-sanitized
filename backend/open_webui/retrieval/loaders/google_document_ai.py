"""
Google Cloud Document AI 문서 로더

프로세서 응답 형식 두 가지를 모두 지원:
  1. OCR/Form Parser: document.text + document.pages (text_anchor 기반)
  2. Layout Parser: document.document_layout.blocks (블록 기반)

인증:
- service_account_key 제공 시 → from_service_account_info() 사용
- 미제공 시 → Application Default Credentials (ADC) 사용
"""

import json
import logging
import mimetypes
import os
import sys
from collections import defaultdict

from langchain_core.documents import Document
from open_webui.env import GLOBAL_LOG_LEVEL, SRC_LOG_LEVELS

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

# 확장자 → MIME 타입 매핑 (클라우드 스토리지 UUID 경로 대응)
_EXT_MIME_MAP = {
    "pdf": "application/pdf",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "gif": "image/gif",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _resolve_mime_type(filename: str, file_path: str) -> str:
    """파일명 확장자 기반 MIME 타입 결정. 클라우드 스토리지 UUID 경로 대응."""
    if filename:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in _EXT_MIME_MAP:
            return _EXT_MIME_MAP[ext]
        mime, _ = mimetypes.guess_type(filename)
        if mime:
            return mime

    mime, _ = mimetypes.guess_type(file_path)
    return mime or "application/pdf"


class GoogleDocumentAILoader:
    """
    Google Cloud Document AI를 사용한 문서 로더.

    OCR 프로세서와 Layout Parser 프로세서 모두 지원:
    - OCR/Form Parser → document.text + document.pages
    - Layout Parser → document.document_layout.blocks
    """

    SUPPORTED_EXTENSIONS = list(_EXT_MIME_MAP.keys())

    def __init__(
        self,
        project_id: str,
        location: str,
        processor_id: str,
        service_account_key: str,
        file_path: str,
        filename: str = "",
        processor_version: str = "",
    ):
        if not processor_id:
            raise ValueError("Document AI Processor ID cannot be empty.")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found at {file_path}")

        self.file_path = file_path
        self.filename = filename or os.path.basename(file_path)

        # PersistentConfig 객체 → 문자열 변환
        _project_id = str(project_id) if project_id is not None else ""
        _service_account_key = str(service_account_key) if service_account_key else ""

        # project_id: 명시값 > 서비스 계정 키 > ADC
        if _project_id:
            self.project_id = _project_id
        elif _service_account_key:
            self.project_id = json.loads(_service_account_key).get("project_id", "")
        else:
            self.project_id = ""

        self.service_account_key = _service_account_key
        self.location = str(location) if location else "us"
        self.processor_id = str(processor_id) if processor_id else ""
        self.processor_version = str(processor_version) if processor_version else ""

        log.info(
            f"GoogleDocumentAILoader init: processor_id={self.processor_id!r}, "
            f"processor_version={self.processor_version!r}, "
            f"project_id={self.project_id!r}, location={self.location!r}"
        )

    def load(self) -> list[Document]:
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai_v1 as documentai

            # 1. 클라이언트 생성
            opts = ClientOptions(
                api_endpoint=f"{self.location}-documentai.googleapis.com"
            )

            if self.service_account_key:
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(self.service_account_key),
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                client = documentai.DocumentProcessorServiceClient(
                    credentials=credentials, client_options=opts
                )
            else:
                log.info("Using Application Default Credentials for Document AI")
                client = documentai.DocumentProcessorServiceClient(client_options=opts)

            # 2. 프로세서 리소스 이름 생성
            project_id = self._resolve_project_id()
            if self.processor_version:
                name = client.processor_version_path(
                    project_id,
                    self.location,
                    self.processor_id,
                    self.processor_version,
                )
            else:
                name = client.processor_path(
                    project_id, self.location, self.processor_id
                )

            # 3. 파일 읽기
            with open(self.file_path, "rb") as f:
                file_content = f.read()

            if not file_content:
                log.error(f"File is empty: {self.file_path}")
                return []

            mime_type = _resolve_mime_type(self.filename, self.file_path)
            log.info(
                f"Processing with Document AI: {self.filename} "
                f"(mime={mime_type}, size={len(file_content)} bytes, processor={name})"
            )

            # 4. Document AI 호출
            raw_document = documentai.RawDocument(
                content=file_content, mime_type=mime_type
            )
            request = documentai.ProcessRequest(name=name, raw_document=raw_document)
            result = client.process_document(request=request)
            document = result.document

            # 5. 응답 형식에 따라 텍스트 추출
            #    - OCR/Form Parser: document.text + document.pages
            #    - Layout Parser: document.document_layout.blocks
            if document.text:
                log.info(
                    f"Document AI response (OCR format): text_len={len(document.text)}, "
                    f"pages={len(document.pages) if document.pages else 0}"
                )
                return self._parse_ocr_response(document)

            if (
                hasattr(document, "document_layout")
                and document.document_layout
                and document.document_layout.blocks
            ):
                blocks = document.document_layout.blocks
                log.info(f"Document AI response (Layout format): blocks={len(blocks)}")
                return self._parse_layout_response(blocks)

            log.warning(
                f"No text returned for '{self.filename}'. "
                f"The processor may not support this document type."
            )
            return []

        except Exception as e:
            log.error(f"Document AI processing error: {e}")
            return [Document(page_content=f"Error during processing: {e}", metadata={})]

    def _parse_ocr_response(self, document) -> list[Document]:
        """OCR/Form Parser 응답: document.text + document.pages 기반."""
        documents = []
        if document.pages:
            for i, page in enumerate(document.pages):
                page_text = self._get_page_text(document.text, page)
                if page_text.strip():
                    documents.append(
                        Document(
                            page_content=page_text,
                            metadata={
                                "page": i,
                                "page_label": i + 1,
                                "total_pages": len(document.pages),
                            },
                        )
                    )

        if not documents:
            documents.append(
                Document(
                    page_content=document.text,
                    metadata={"page": 0, "total_pages": 1},
                )
            )

        log.info(f"Document AI: {len(documents)} page(s) extracted (OCR format).")
        return documents

    def _parse_layout_response(self, blocks) -> list[Document]:
        """Layout Parser 응답: document.document_layout.blocks 기반."""
        # 페이지별로 블록 텍스트 그룹화
        page_texts = defaultdict(list)
        for block in blocks:
            text = self._extract_block_text(block)
            if not text:
                continue
            page_start = 1
            if hasattr(block, "page_span") and block.page_span:
                page_start = block.page_span.page_start or 1
            page_texts[page_start].append(text)

        if not page_texts:
            return []

        total_pages = max(page_texts.keys())
        documents = []
        for page_num in sorted(page_texts.keys()):
            content = "\n".join(page_texts[page_num])
            if content.strip():
                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "page": page_num - 1,
                            "page_label": page_num,
                            "total_pages": total_pages,
                        },
                    )
                )

        log.info(f"Document AI: {len(documents)} page(s) extracted (Layout format).")
        return documents

    @staticmethod
    def _extract_block_text(block) -> str:
        """Layout Parser 블록에서 텍스트 추출 (textBlock, listBlock, tableBlock)."""
        # textBlock: 일반 텍스트 블록
        if hasattr(block, "text_block") and block.text_block:
            return block.text_block.text or ""

        # listBlock: 리스트 블록 → 하위 블록 재귀
        if hasattr(block, "list_block") and block.list_block:
            items = []
            if block.list_block.list_entries:
                for entry in block.list_block.list_entries:
                    if entry.blocks:
                        for sub in entry.blocks:
                            t = GoogleDocumentAILoader._extract_block_text(sub)
                            if t:
                                items.append(f"- {t}")
            return "\n".join(items)

        # tableBlock: 테이블 블록 → 행/셀 텍스트 추출
        if hasattr(block, "table_block") and block.table_block:
            rows = []
            table = block.table_block
            for section in (table.header_rows, table.body_rows):
                if not section:
                    continue
                for row in section:
                    if row.cells:
                        cells = []
                        for cell in row.cells:
                            cell_texts = []
                            if cell.blocks:
                                for sub in cell.blocks:
                                    t = GoogleDocumentAILoader._extract_block_text(sub)
                                    if t:
                                        cell_texts.append(t)
                            cells.append(" ".join(cell_texts))
                        rows.append(" | ".join(cells))
            return "\n".join(rows)

        return ""

    def _resolve_project_id(self) -> str:
        if self.project_id:
            return self.project_id
        import google.auth

        _, project = google.auth.default()
        if project:
            return project
        raise ValueError(
            "Project ID를 결정할 수 없습니다. "
            "명시적으로 지정하거나 GOOGLE_CLOUD_PROJECT 환경 변수를 설정하세요."
        )

    @staticmethod
    def _get_page_text(full_text: str, page) -> str:
        """OCR 응답의 text_anchor 기반 페이지 텍스트 추출."""

        def _layout_text(layout) -> str:
            if not layout or not layout.text_anchor:
                return ""
            parts = []
            for seg in layout.text_anchor.text_segments:
                start = int(seg.start_index) if seg.start_index else 0
                parts.append(full_text[start : int(seg.end_index)])
            return "".join(parts)

        # page.layout이 가장 신뢰할 수 있음
        text = _layout_text(page.layout)
        if text.strip():
            return text

        # fallback: paragraphs → blocks → lines
        for elements in (page.paragraphs, page.blocks, page.lines):
            if elements:
                text = "".join(_layout_text(el.layout) for el in elements)
                if text.strip():
                    return text

        return ""
