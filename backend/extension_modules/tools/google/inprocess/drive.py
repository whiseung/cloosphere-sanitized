"""Google Drive in-process tools — LangChain StructuredTool builders.

설계 (Gmail 3-tool 대칭):
- ``make_drive_search`` (read-only): Drive ``q`` 문법 검색.  결과에 ``mimeType``
  포함 — LLM 이 native/binary 판단 + ``drive_get_content`` 호출 결정.
- ``make_drive_get_content`` (read-only): 메타데이터 fetch 후 native 는 export
  화이트리스트, text 류는 ``alt=media``, 그 외 바이너리는 다운로드 없이 메타+노트.
  export/alt=media 는 비-JSON 원문이므로 ``call_google_api(response_mode="text")``.
- ``make_drive_create_doc`` (HITL): tool 자체는 외부 호출을 하지 않고
  confirmation_required preview 만 반환.  실제 생성은 frontend 확인 후
  ``POST /api/v1/google/drive/confirm/{message_id}`` 가 처리.

함정 (spec §4.3):
- export 응답은 ``{}`` 일 수 있어 ``resp.get("text", "")`` 필수 (KeyError 회피).
- 화이트리스트 밖 native (drawing/form/folder/shortcut/script) 는 export 하면
  403 → 4번 분기 (바이너리 메타+노트) 로 fall-through.
- native 파일은 ``size`` 가 없어 export 403(exportSizeLimitExceeded) 을
  GoogleApiError 로 잡아 친화적 노트로 변환.
- LLM 컨텍스트 보호 출력 캡 ~50k 자 + ``truncated`` 플래그 (10MB 네트워크 캡과 별개).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from extension_modules.tools.google.inprocess._common import (
    BatchQuotaExceeded,
    GoogleApiError,
    GoogleReauthRequired,
    call_google_api,
    emit_event,
    enforce_write_quota,
)
from extension_modules.tools.google.inprocess._extract import (
    MAX_EXTRACT_BYTES,
    extract_text_from_bytes,
    is_extractable,
)
from extension_modules.tools.google.inprocess._hitl import make_drive_confirmation
from extension_modules.tools.google.inprocess._message_id import mint_message_id
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

# Frontend 가 ToolMessage 안에서 marker 를 보면 DriveConfirmation.svelte 를 렌더한다
# (gmail.py 의 GMAIL_CONFIRM_MARKER / calendar.py 의 CALENDAR_CONFIRM_MARKER 패턴).
DRIVE_CONFIRM_MARKER = "[drive_confirmation_required]"
DRIVE_QUOTA_MARKER = "[drive_batch_quota_exceeded]"

# ---------------------------------------------------------------------------
# Constants — Drive API endpoints + export allowlist
# ---------------------------------------------------------------------------

_DRIVE_HOST = "www.googleapis.com"
_DRIVE_FILES_PATH = "/drive/v3/files"

# native(application/vnd.google-apps.*) 의 export mimeType 화이트리스트.
# 밖의 native (drawing/form/folder/shortcut/script) 는 바이너리 분기로 fall-through.
_EXPORT_MIME_BY_NATIVE: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# text 추출 가능한 비-native mimeType (alt=media 로 원문 fetch).
_TEXT_LIKE_PREFIXES = ("text/",)
_TEXT_LIKE_EXACT = frozenset(
    {
        "application/json",
        "application/xml",
        "application/x-yaml",
        "application/javascript",
    }
)

# LLM 컨텍스트 보호 출력 캡 (spec §8 OQ#2 기본 50k).  10MB 네트워크 캡과 별개.
_MAX_CONTENT_CHARS = 50000


# ---------------------------------------------------------------------------
# Pydantic args schemas
# ---------------------------------------------------------------------------


class DriveSearchArgs(BaseModel):
    """``drive_search`` 의 인자."""

    q: str = Field(
        ...,
        min_length=1,
        description=(
            "Drive 검색 쿼리 — 표준 Drive q 문법.  파일 '내용'으로 찾으려면 "
            "\"fullText contains 'MPCI'\" (본문·이름·색인 텍스트 매칭) — "
            '"name contains" 만으로는 본문에만 있는 파일을 놓친다.  그 외: '
            "\"mimeType='application/pdf'\", \"'<folderId>' in parents\", "
            "\"modifiedTime > '2026-01-01T00:00:00'\"."
        ),
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="반환할 최대 파일 수 (1-50, 기본 10).",
    )
    page_token: Optional[str] = Field(
        default=None,
        description="이전 응답의 ``next_page_token`` — 다음 페이지 fetch 시 사용.",
    )

    @field_validator("q", mode="after")
    @classmethod
    def _q_nonempty(cls, v: str) -> str:
        stripped = (v or "").strip()
        if not stripped:
            raise ValueError("'q' must be a non-empty Drive search query")
        return stripped


class DriveGetContentArgs(BaseModel):
    """``drive_get_content`` 의 인자."""

    file_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Drive 파일 ID (``drive_search`` 결과의 ``id`` 필드).  Google Docs/"
            "Sheets/Slides 는 텍스트 export, text 류는 원문, 바이너리는 메타데이터만."
        ),
    )


class DriveGetContentsArgs(BaseModel):
    """``drive_get_contents`` 인자 — 여러 파일 일괄 읽기 (배치)."""

    file_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Drive 파일 ID 목록 (``drive_search`` 결과의 ``id``).  한 번의 호출로 "
            "여러 파일 본문을 읽어 도구 호출 budget 을 절약 (최대 20개)."
        ),
    )


class DriveCreateDocArgs(BaseModel):
    """``drive_create_doc`` 의 인자.

    HITL 응답 단계에서는 검증만 — 실제 생성은 confirm endpoint 가 받은 수정본으로
    진행하므로 content 는 markdown 그대로 둔다 (평문 변환은 생성 단계 _md_to_prose).
    """

    name: str = Field(..., min_length=1, description="문서 제목.")
    content: str = Field(
        ...,
        description="문서 본문 (markdown 가능).  생성 시 평문으로 변환되어 삽입된다.",
    )
    folder_id: Optional[str] = Field(
        default=None,
        description="부모 폴더 ID (선택).  미지정 시 My Drive 루트.",
    )

    @field_validator("name", mode="after")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        stripped = (v or "").strip()
        if not stripped:
            raise ValueError("'name' must be a non-empty document title")
        return stripped


# ---------------------------------------------------------------------------
# Tool builders
# ---------------------------------------------------------------------------


_DRIVE_SEARCH_DESCRIPTION = (
    "Search the user's Google Drive using Drive's standard query syntax. "
    "To find files by their CONTENT (not just filename), use fullText: "
    "\"fullText contains 'MPCI'\" matches the keyword in the file body, name, "
    'and indexed text — searching by "name contains" alone misses files '
    "where the keyword is only inside the document. Other examples: "
    "\"name contains 'report'\", \"mimeType='application/pdf'\", "
    "\"'<folderId>' in parents\" (list a folder's contents), "
    "\"modifiedTime > '2026-01-01T00:00:00'\". The search automatically covers "
    "the user's My Drive, shared drives (team drives), AND files shared with "
    "them by others ('shared with me') — so a file shared by a colleague is "
    "found too. Returns matching files with "
    "id, name, and mimeType. Use drive_get_content to read a file's text — "
    "Google Docs/Sheets/Slides, PDFs, and Office files (Word/Excel/PowerPoint) "
    "are extracted; images and other binaries return metadata only."
)


def make_drive_search(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """``drive_search`` — Drive q 문법 기반 파일 검색 (read-only)."""

    async def _drive_search(**kwargs) -> str:
        args = DriveSearchArgs(**kwargs)
        log.info(
            "drive_search: user_id=%s q_len=%d max=%d page_token=%s",
            user_id,
            len(args.q),
            args.max_results,
            "yes" if args.page_token else "no",
        )

        # 사용자가 접근 가능한 파일을 폭넓게 검색하기 위해 2-패스 병합:
        #  - Pass 1 (corpora=allDrives): 소유 + 공유 드라이브(팀 드라이브).
        #  - Pass 2 (sharedWithMe): '나와 공유됨' 파일 — 기본 corpora=user 는
        #    이를 제외하므로 sharedWithMe 연산자가 필요 (Drive API v3 공식).
        # 단일 q 로 소유+공유받음 union 이 안 돼 두 패스를 interleave·dedupe 한다.
        common = {
            "pageSize": args.max_results,
            "fields": (
                "files(id,name,mimeType,modifiedTime,"
                "owners(displayName,emailAddress),ownedByMe,driveId),nextPageToken"
            ),
            "spaces": "drive",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        p1: dict[str, Any] = {**common, "q": args.q, "corpora": "allDrives"}
        if args.page_token:
            p1["pageToken"] = args.page_token
        p2: dict[str, Any] = {
            "pageSize": args.max_results,
            "fields": (
                "files(id,name,mimeType,modifiedTime,"
                "owners(displayName,emailAddress),ownedByMe,driveId),nextPageToken"
            ),
            "spaces": "drive",
            "supportsAllDrives": True,
            "q": f"({args.q}) and sharedWithMe = true",
        }

        pass_results: list[list[dict]] = []
        next_token: Optional[str] = None
        errors: list[str] = []
        for idx, params in enumerate((p1, p2), start=1):
            kind = (
                "allDrives" if params.get("corpora") == "allDrives" else "sharedWithMe"
            )
            try:
                resp = await call_google_api(
                    method="GET",
                    path=_DRIVE_FILES_PATH,
                    user_id=user_id,
                    host=_DRIVE_HOST,
                    params=params,
                )
            except GoogleReauthRequired as exc:
                # 계정 레벨 — 어느 패스든 reauth 면 전체 안내.
                log.warning(
                    "drive_search DIAG pass%d(%s) reauth q=%r",
                    idx,
                    kind,
                    params.get("q"),
                )
                return _format_error("google_reauth_required", reason=exc.reason)
            except GoogleApiError as exc:
                # [DIAG] 어느 패스가 왜 실패하는지 — 디버깅 후 제거.
                log.warning(
                    "drive_search DIAG pass%d(%s) ERROR %s q=%r msg=%s",
                    idx,
                    kind,
                    exc.status_code,
                    params.get("q"),
                    str(exc.message)[:200],
                )
                errors.append(f"drive_api_error_{exc.status_code}")
                pass_results.append([])
                continue
            if next_token is None:
                next_token = resp.get("nextPageToken")
            files = [
                _candidate_from_file(f, kind)
                for f in (resp.get("files") or [])
                if f.get("id")
            ]
            # [DIAG] 패스별 실제 q + 결과 파일명 — 디버깅 후 제거.
            log.info(
                "drive_search DIAG pass%d(%s) q=%r → %d files: %s",
                idx,
                kind,
                params.get("q"),
                len(files),
                [f["name"] for f in files][:10],
            )
            pass_results.append(files)

        # 모든 패스가 실패(결과 없음 + 에러)면 첫 에러 반환.
        if all(not r for r in pass_results) and errors:
            return _format_error(errors[0], message="drive search failed")

        # interleave + dedupe — 공유받음 결과가 소유 결과에 밀려 잘리지 않게.
        merged: list[dict] = []
        seen: set[str] = set()
        for i in range(max((len(r) for r in pass_results), default=0)):
            for r in pass_results:
                if i < len(r) and r[i]["id"] not in seen:
                    seen.add(r[i]["id"])
                    merged.append(r[i])
        return json.dumps(
            {"results": merged[: args.max_results], "next_page_token": next_token},
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_drive_search,
        name="drive_search",
        description=_DRIVE_SEARCH_DESCRIPTION,
        args_schema=DriveSearchArgs,
    )


_DRIVE_GET_CONTENT_DESCRIPTION = (
    "Fetch the text content of a single Drive file by its id (from drive_search). "
    "Google Docs/Sheets/Slides are exported as plain text/CSV; text files "
    "(text/*, JSON, XML, YAML) are returned as-is; images, PDFs, and other "
    "binaries return metadata only with a note (no content extraction). "
    "Long documents are truncated with a 'truncated' flag set."
)


def make_drive_get_content(
    user_id: str,
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> StructuredTool:
    """``drive_get_content`` — 파일 메타데이터 + 텍스트 추출 (read-only).

    ``extraction_config`` (unified_agent 가 RAG 설정에서 resolve 한 평문 dict) 가
    주어지면 PDF/Office 바이너리도 기존 RAG Loader 로 본문 추출.  None 이면 기존
    동작(메타데이터 노트)으로 fallback.
    """

    async def _drive_get_content(**kwargs) -> str:
        args = DriveGetContentArgs(**kwargs)
        log.info("drive_get_content: user_id=%s file_id=%s", user_id, args.file_id)

        # 1. 메타데이터 (json 모드).
        try:
            meta = await call_google_api(
                method="GET",
                path=f"{_DRIVE_FILES_PATH}/{args.file_id}",
                user_id=user_id,
                host=_DRIVE_HOST,
                params={
                    "fields": "id,name,mimeType,size",
                    "supportsAllDrives": True,
                },
            )
        except GoogleReauthRequired as exc:
            return _format_error("google_reauth_required", reason=exc.reason)
        except GoogleApiError as exc:
            return _format_error(
                f"drive_api_error_{exc.status_code}",
                message=str(exc.message)[:300],
            )

        mime = meta.get("mimeType", "")
        name = meta.get("name")
        is_native = mime.startswith("application/vnd.google-apps.")

        # 2. native + export 화이트리스트 → export (text 모드).
        if is_native and mime in _EXPORT_MIME_BY_NATIVE:
            export_mime = _EXPORT_MIME_BY_NATIVE[mime]
            try:
                resp = await call_google_api(
                    method="GET",
                    path=f"{_DRIVE_FILES_PATH}/{args.file_id}/export",
                    user_id=user_id,
                    host=_DRIVE_HOST,
                    params={"mimeType": export_mime, "supportsAllDrives": True},
                    response_mode="text",
                )
            except GoogleReauthRequired as exc:
                return _format_error("google_reauth_required", reason=exc.reason)
            except GoogleApiError as exc:
                # native 는 size 가 없어 사전 캡 불가 → export 403 을 친화적 노트로.
                return _format_error(
                    "drive_export_too_large"
                    if exc.status_code == 403
                    else f"drive_api_error_{exc.status_code}",
                    name=name,
                    mimeType=mime,
                    message=str(exc.message)[:300],
                )
            # 빈 export 는 text 모드에서도 {} → get("text","") 로 KeyError 회피.
            return _format_content(meta, resp.get("text", ""))

        # 3. text 류 → alt=media (text 모드).
        if (not is_native) and _is_text_like(mime):
            try:
                resp = await call_google_api(
                    method="GET",
                    path=f"{_DRIVE_FILES_PATH}/{args.file_id}",
                    user_id=user_id,
                    host=_DRIVE_HOST,
                    params={"alt": "media", "supportsAllDrives": True},
                    response_mode="text",
                )
            except GoogleReauthRequired as exc:
                return _format_error("google_reauth_required", reason=exc.reason)
            except GoogleApiError as exc:
                return _format_error(
                    f"drive_api_error_{exc.status_code}",
                    name=name,
                    mimeType=mime,
                    message=str(exc.message)[:300],
                )
            return _format_content(meta, resp.get("text", ""))

        # 4. 비-native 바이너리:
        #    추출 화이트리스트(PDF/Office/ODF) + size 가드 + 추출 활성 →
        #    alt=media 로 bytes 다운로드 후 기존 RAG Loader 로 텍스트 추출.
        #    이미지/스캔/대용량/비활성/추출실패 → 메타 + 노트(다운로드 X).
        if (
            is_extractable(mime)
            and extraction_config
            and _within_extract_size(meta.get("size"))
        ):
            try:
                resp = await call_google_api(
                    method="GET",
                    path=f"{_DRIVE_FILES_PATH}/{args.file_id}",
                    user_id=user_id,
                    host=_DRIVE_HOST,
                    params={"alt": "media", "supportsAllDrives": True},
                    response_mode="bytes",
                )
            except GoogleReauthRequired as exc:
                return _format_error("google_reauth_required", reason=exc.reason)
            except GoogleApiError as exc:
                return _format_error(
                    f"drive_api_error_{exc.status_code}",
                    name=name,
                    mimeType=mime,
                    message=str(exc.message)[:300],
                )
            extracted = await extract_text_from_bytes(
                resp.get("content_bytes", b""),
                name or "",
                mime,
                extraction_config=extraction_config,
            )
            if extracted.get("content"):
                return json.dumps(
                    {
                        "id": meta.get("id"),
                        "name": name,
                        "mimeType": mime,
                        "content": extracted["content"],
                        "truncated": extracted.get("truncated", False),
                    },
                    ensure_ascii=False,
                )
            # 추출 실패/빈 본문 → 아래 메타 노트로 fall-through.

        return json.dumps(
            {
                "id": meta.get("id"),
                "name": name,
                "mimeType": mime,
                "size": meta.get("size"),
                "note": (
                    "This file is binary or has no text export "
                    "(image/PDF/other). No text extraction performed."
                ),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_drive_get_content,
        name="drive_get_content",
        description=_DRIVE_GET_CONTENT_DESCRIPTION,
        args_schema=DriveGetContentArgs,
    )


_MAX_BATCH_IDS = 20

# [T5] 배치 1회 출력의 누적 char 상한 — loop 컨텍스트·최종 프롬프트 폭증 방지.
_BATCH_MAX_CHARS = 200000

_DRIVE_GET_CONTENTS_DESCRIPTION = (
    "Read the text of MULTIPLE Drive files in ONE call (batch of "
    "drive_get_content). Pass a list of file ids from drive_search. PREFER this "
    "over many separate drive_get_content calls when gathering several files — "
    "it conserves the tool-call budget and returns all results together as "
    "{results: [...]}. Google Docs/Sheets/Slides, PDFs, and Office files are "
    "extracted; images return metadata only."
)


def make_drive_get_contents(
    user_id: str,
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> StructuredTool:
    """``drive_get_contents`` — 여러 파일 본문을 1회 호출로 일괄 읽기 (read-only).

    단건 ``drive_get_content`` 로직을 재사용해 N개 파일을 읽고 ``{results: [...]}``
    로 묶어 반환.  도구 호출 1회만 소비해 ToolCallLimit budget 을 절약한다.
    개별 파일 실패는 그 항목만 error 로 격리(최상위는 ``results``).
    """
    single = make_drive_get_content(
        user_id, conversation_id=conversation_id, extraction_config=extraction_config
    )

    async def _drive_get_contents(**kwargs) -> str:
        args = DriveGetContentsArgs(**kwargs)
        log.info("drive_get_contents: user_id=%s count=%d", user_id, len(args.file_ids))
        results: list[Any] = []
        used = 0
        for fid in args.file_ids[:_MAX_BATCH_IDS]:
            if used >= _BATCH_MAX_CHARS:
                results.append(
                    {"id": fid, "note": "batch output budget reached; not read"}
                )
                continue
            try:
                raw = await single.coroutine(file_id=fid)
                results.append(json.loads(raw))
                used += len(raw)
            except Exception as exc:  # 개별 항목 실패는 격리 — 나머지는 정상 반환.
                results.append({"id": fid, "error": str(exc)[:200]})
        return json.dumps({"results": results}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_drive_get_contents,
        name="drive_get_contents",
        description=_DRIVE_GET_CONTENTS_DESCRIPTION,
        args_schema=DriveGetContentsArgs,
    )


_DRIVE_CREATE_DOC_DESCRIPTION = (
    "Compose a Google Doc and request user confirmation before creating it. "
    "Use this when the user asks you to create / write / draft a document, "
    "report, or note in their Google Drive. The tool returns a "
    "confirmation_required preview — the actual document is created only after "
    "the user explicitly confirms in the UI. Pass an optional folder_id to "
    "place it in a specific folder (omit for My Drive root)."
)


def make_drive_create_doc(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """user_id + conversation_id 바인딩 + HITL confirm 응답을 만드는 ``drive_create_doc`` tool.

    Tool 자체는 외부 API 를 호출하지 않는다.  per-turn write quota 통과 시
    HITL preview 를 반환하고, frontend 가 사용자에게 보여준 뒤 confirm endpoint
    로 실제 생성을 보낸다.
    """

    def _drive_create_doc(**kwargs) -> str:
        args = DriveCreateDocArgs(**kwargs)
        log.info(
            "drive_create_doc draft requested: user_id=%s name_len=%d content_len=%d folder=%s",
            user_id,
            len(args.name or ""),
            len(args.content or ""),
            "yes" if args.folder_id else "no",
        )

        try:
            enforce_write_quota(
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="drive_create_doc",
            )
        except BatchQuotaExceeded as exc:
            log.warning(
                "drive_create_doc quota exceeded: user=%s tool=%s limit=%d",
                exc.user_id,
                exc.tool_name,
                exc.limit,
            )
            return _format_quota_error(tool_name=exc.tool_name, limit=exc.limit)

        message_id = mint_message_id(user_id)
        payload = make_drive_confirmation(
            message_id=message_id,
            name=args.name,
            content=args.content,
            folder_id=args.folder_id,
        )
        emit_event(
            "google.confirmation.shown",
            tool="drive_create_doc",
            user_id=user_id,
            conversation_id=conversation_id,
            risk_level=payload.get("risk_level"),
        )
        return _format_confirmation(payload)

    return StructuredTool.from_function(
        func=_drive_create_doc,
        name="drive_create_doc",
        description=_DRIVE_CREATE_DOC_DESCRIPTION,
        args_schema=DriveCreateDocArgs,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate_from_file(f: dict, kind: str) -> dict:
    """Drive files.list 항목 → picker/검색 결과 후보 dict.

    location enum (프론트가 i18n 매핑):
      - 'shared_with_me'  : Pass2(sharedWithMe) 결과
      - 'shared_drive'    : driveId 존재(공유 드라이브 멤버)
      - 'my_drive'        : 그 외(내 드라이브)
    owner 는 공유 드라이브 항목에서 빈 값일 수 있음(Drive API 사양).
    """
    if kind == "sharedWithMe":
        location = "shared_with_me"
    elif f.get("driveId"):
        location = "shared_drive"
    else:
        location = "my_drive"
    owners = f.get("owners") or []
    owner = owners[0].get("displayName") if owners else None
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mimeType": f.get("mimeType"),
        "modifiedTime": f.get("modifiedTime"),
        "owner": owner,
        "location": location,
    }


def _is_text_like(mime: str) -> bool:
    """비-native mimeType 이 텍스트 추출 가능한지 (text/* 또는 화이트리스트)."""
    if not mime:
        return False
    if any(mime.startswith(p) for p in _TEXT_LIKE_PREFIXES):
        return True
    return mime in _TEXT_LIKE_EXACT


def _within_extract_size(size: Optional[Any]) -> bool:
    """[H2] Drive 메타 ``size``(문자열 bytes)가 추출 임계 이내인지.

    size 가 없으면(native 등) best-effort 로 허용 — 단 이 경로는 is_extractable
    바이너리만 타므로 실제로는 size 가 거의 항상 존재한다.
    """
    if size is None:
        return True
    try:
        return int(size) <= MAX_EXTRACT_BYTES
    except (TypeError, ValueError):
        return True


def _format_content(meta: dict, text: str) -> str:
    """추출 텍스트를 출력 캡 적용 후 LLM-친화 JSON 으로.

    ~50k 자 캡 + ``truncated`` 플래그 (LLM 컨텍스트 보호).
    """
    truncated = len(text) > _MAX_CONTENT_CHARS
    content = text[:_MAX_CONTENT_CHARS] if truncated else text
    return json.dumps(
        {
            "id": meta.get("id"),
            "name": meta.get("name"),
            "mimeType": meta.get("mimeType"),
            "content": content,
            "truncated": truncated,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Response formatters — marker + JSON payload
# ---------------------------------------------------------------------------


def _format_confirmation(payload: dict) -> str:
    """Frontend 가 DriveConfirmation.svelte 를 렌더할 수 있는 직렬화 응답."""
    return (
        f"{DRIVE_CONFIRM_MARKER}\n```json\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n```"
    )


def _format_quota_error(tool_name: str, limit: int) -> str:
    """per-turn write quota 초과 — LLM 에 사용자 확인 안내 유도용 응답."""
    payload = {
        "error": "batch_quota_exceeded",
        "tool": tool_name,
        "limit": limit,
        "hint": (
            "이번 메시지에서 가능한 문서 생성 횟수를 초과했습니다.  사용자에게 "
            "한 번에 진행할지 확인해 주세요."
        ),
    }
    return (
        f"{DRIVE_QUOTA_MARKER}\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    )


def _format_error(error_code: str, **fields: Any) -> str:
    """drive_search / drive_get_content 의 외부 호출 실패를 LLM-친화 JSON 으로.

    gmail.py 의 _format_error 가 module-private 이므로 동일 형태로 자체 복사
    (spec §4.3).  drive_export_too_large 는 native 문서가 10MB export 캡을
    넘긴 경우의 친화적 노트.
    """
    payload: dict[str, Any] = {"error": error_code, **fields}
    if error_code == "google_reauth_required":
        payload.setdefault(
            "hint",
            "Google 계정 재인증이 필요합니다.  사용자에게 설정 > 연결에서 Google "
            "다시 연결을 안내해 주세요.",
        )
    elif error_code == "drive_export_too_large":
        payload.setdefault(
            "hint",
            "문서가 너무 커서 텍스트로 내보낼 수 없습니다 (10MB 초과).  "
            "사용자에게 문서를 직접 열어 확인하도록 안내해 주세요.",
        )
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


__all__ = [
    "DRIVE_CONFIRM_MARKER",
    "DRIVE_QUOTA_MARKER",
    "DriveCreateDocArgs",
    "DriveGetContentArgs",
    "DriveGetContentsArgs",
    "DriveSearchArgs",
    "make_drive_create_doc",
    "make_drive_get_content",
    "make_drive_get_contents",
    "make_drive_search",
    "make_drive_tools",
]


def make_drive_tools(
    user_id: str,
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> list[StructuredTool]:
    """user_id + conversation_id 바인딩 Drive 툴 모음.

    구성:
    - ``drive_search``       (read-only) — Drive q 문법 검색
    - ``drive_get_content``  (read-only) — native export / text alt=media /
      바이너리(PDF/Office) 추출 (``extraction_config`` 제공 시)
    - ``drive_create_doc``   (HITL preview) — Google Doc 생성

    ``conversation_id`` 는 ``drive_create_doc`` 의 per-turn write quota scope.
    ``extraction_config`` 는 unified_agent 가 RAG 설정에서 resolve 한 평문 dict
    (None → 바이너리 추출 비활성, 메타데이터 fallback).  read-only 툴은
    quota/conv 사용 안 함.
    """
    return [
        make_drive_search(user_id, conversation_id=conversation_id),
        make_drive_get_content(
            user_id,
            conversation_id=conversation_id,
            extraction_config=extraction_config,
        ),
        make_drive_get_contents(
            user_id,
            conversation_id=conversation_id,
            extraction_config=extraction_config,
        ),
        make_drive_create_doc(user_id, conversation_id=conversation_id),
    ]
