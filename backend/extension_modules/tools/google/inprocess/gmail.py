"""Gmail in-process tools — LangChain StructuredTool builders.

설계:
- ``make_gmail_send`` (sensitive scope ``gmail.send``): tool 자체는 외부 발송을
  하지 않고 HITL 응답 (``confirmation_required: True``) 만 반환한다.  실제
  발송은 frontend 가 확인 후 호출하는 ``POST /api/v1/google/gmail/confirm/
  {message_id}`` (T-B13) 가 처리.
- ``make_gmail_search`` (restricted scope ``gmail.readonly``): Gmail q syntax
  검색.  list + per-message metadata fetch 로 snippet + headers 까지 반환
  (LLM 이 추가 호출 없이 인덱스 페이지 정도의 정보를 받음).
- ``make_gmail_get`` (restricted scope ``gmail.readonly``): 메시지 id 로 full
  payload fetch 후 multipart MIME 트리에서 text/plain 본문 추출.
- per-turn write quota 가드 — LLM 이 동일 turn 에서 ``gmail_send`` 를 반복
  호출하는 사고 (plan §5.7, 베테랑 #12) 회피 (read-only tool 에는 적용 안 함).
"""

from __future__ import annotations

import base64
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
    MAX_EXTRACT_CHARS,
    extract_text_from_bytes,
    is_extractable,
)
from extension_modules.tools.google.inprocess._hitl import make_gmail_confirmation
from extension_modules.tools.google.inprocess._message_id import mint_message_id
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

# Frontend 가 ToolMessage 안에서 본 marker 를 보면 GmailConfirmation.svelte 를
# 렌더한다 (document tool 의 DOCUMENT_TOOL_MARKER 와 동일 패턴).
GMAIL_CONFIRM_MARKER = "[gmail_confirmation_required]"
GMAIL_QUOTA_MARKER = "[gmail_batch_quota_exceeded]"


# ---------------------------------------------------------------------------
# Pydantic args schemas
# ---------------------------------------------------------------------------


class GmailSendArgs(BaseModel):
    """``gmail_send`` 의 인자.  LLM 이 자연어에서 추출해 채운다.

    HITL 응답 단계에서는 검증만 수행 — 실제 발송은 confirm endpoint 가 받은
    수정본 (사용자가 frontend 에서 편집한 결과) 으로 진행하므로 여기서
    body 표현은 markdown 그대로 둔다.  변환 (MIME / base64url) 은 발송 단계.
    """

    to: list[str] = Field(
        default_factory=list,
        description=(
            "수신자 이메일 주소 목록.  수신자를 모르면 빈 리스트([])로 두라 — "
            "사용자가 확인 카드에서 직접 채운다.  수신자 미상이라는 이유로 메일을 "
            "텍스트로만 쓰지 말고 반드시 이 도구를 호출할 것.  실제 발송은 confirm "
            "단계에서 최소 1명을 요구한다."
        ),
    )
    subject: str = Field(..., description="메일 제목.")
    body: str = Field(
        ...,
        description=(
            "메일 본문 (markdown 가능).  발송 시 text/plain + text/html "
            "multipart 로 변환된다."
        ),
    )
    cc: Optional[list[str]] = Field(default=None, description="참조 수신자 (선택).")
    bcc: Optional[list[str]] = Field(
        default=None, description="숨은 참조 수신자 (선택)."
    )
    in_reply_to: Optional[str] = Field(
        default=None,
        description="회신 시 원본 메시지 ID (Gmail thread continuation).",
    )
    # 수신자 필수 검증은 confirm 단계(GmailConfirmBody, google_actions.py)에서만.
    # tool 단계는 빈 수신자를 허용해야 모델이 카드를 띄우고 사용자가 채울 수 있다.


class GmailSearchArgs(BaseModel):
    """``gmail_search`` 의 인자."""

    q: str = Field(
        ...,
        min_length=1,
        description=(
            "Gmail 검색 쿼리 — 표준 Gmail q 문법.  예: 'from:alice@example.com', "
            "'is:unread label:inbox', 'subject:invoice newer_than:7d', "
            "'has:attachment after:2026/01/01'.  비어 있을 수 없음 — 너무 광범위한 "
            "검색은 노이즈가 크다."
        ),
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description="반환할 최대 메시지 수 (1-25, 기본 10).  너무 크면 응답 지연.",
    )
    page_token: Optional[str] = Field(
        default=None,
        description=(
            "이전 검색 응답의 ``next_page_token`` — 다음 페이지 fetch 시 사용."
        ),
    )

    @field_validator("q", mode="after")
    @classmethod
    def _q_nonempty(cls, v: str) -> str:
        stripped = (v or "").strip()
        if not stripped:
            raise ValueError("'q' must be a non-empty Gmail search query")
        return stripped


class GmailGetArgs(BaseModel):
    """``gmail_get`` 의 인자."""

    message_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Gmail 메시지 ID (``gmail_search`` 결과의 ``id`` 필드).  주의: "
            "Cloosphere HITL message_id 와 다른 값 — Gmail 측 식별자."
        ),
    )


class GmailGetBatchArgs(BaseModel):
    """``gmail_get_batch`` 의 인자 — 여러 메시지 일괄 읽기 (배치)."""

    message_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Gmail 메시지 ID 목록 (``gmail_search`` 결과의 ``id``).  한 번의 호출로 "
            "여러 메일 본문+첨부를 읽어 도구 호출 budget 절약 (최대 20개)."
        ),
    )


# ---------------------------------------------------------------------------
# Constants — Gmail API endpoints
# ---------------------------------------------------------------------------


_GMAIL_HOST = "gmail.googleapis.com"
_GMAIL_LIST_PATH = "/gmail/v1/users/me/messages"

# Search 결과 / get 응답에서 LLM 에 노출할 헤더만 화이트리스트.  Reply-To 는
# 회신 시 in_reply_to 추적용으로 노출.
_INTERESTING_HEADERS: frozenset[str] = frozenset(
    {"Subject", "From", "To", "Cc", "Date", "Reply-To", "Message-Id"}
)

# T2 — 한 메시지에서 본문 추출을 시도할 최대 첨부 개수 (컨텍스트/지연 보호).
_MAX_ATTACHMENTS = 5

# T4 — 배치 읽기 1회 호출의 최대 메시지 수.
_MAX_BATCH_IDS = 20

# [T5] 배치 1회 출력의 누적 char 상한 — loop 컨텍스트·최종 프롬프트 폭증 방지.
_BATCH_MAX_CHARS = 200000


# ---------------------------------------------------------------------------
# Tool builders
# ---------------------------------------------------------------------------


_GMAIL_SEND_DESCRIPTION = (
    "Compose a draft email and request user confirmation before sending. "
    "Use this when the user asks you to send / write / draft / reply to an "
    "email. The tool returns a confirmation_required preview — the actual "
    "send happens only after the user explicitly confirms in the UI. "
    "Do NOT call this tool repeatedly in the same turn for multiple recipients; "
    "include all recipients in a single call's 'to' list."
)


def make_gmail_send(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """user_id + conversation_id 바인딩 + HITL confirm 응답을 만드는 ``gmail_send`` tool.

    Tool 자체는 외부 API 를 호출하지 않는다.  per-turn write quota 통과 시
    HITL preview 를 반환하고, frontend 가 그것을 사용자에게 보여준 뒤 confirm
    endpoint 로 실제 발송을 보낸다.
    """

    def _gmail_send(**kwargs) -> str:
        args = GmailSendArgs(**kwargs)
        log.info(
            "gmail_send draft requested: user_id=%s recipients=%d subject_len=%d",
            user_id,
            len(args.to) + len(args.cc or []) + len(args.bcc or []),
            len(args.subject or ""),
        )

        try:
            enforce_write_quota(
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name="gmail_send",
            )
        except BatchQuotaExceeded as exc:
            log.warning(
                "gmail_send quota exceeded: user=%s tool=%s limit=%d",
                exc.user_id,
                exc.tool_name,
                exc.limit,
            )
            return _format_quota_error(tool_name=exc.tool_name, limit=exc.limit)

        # mint HMAC-bound message_id — confirm endpoint 가 path 에서 받아
        # ownership 검증 + idempotency dedup 에 사용 (T-B13).
        message_id = mint_message_id(user_id)
        payload = make_gmail_confirmation(
            message_id=message_id,
            to=args.to,
            subject=args.subject,
            body=args.body,
            cc=args.cc,
            bcc=args.bcc,
            in_reply_to=args.in_reply_to,
        )
        emit_event(
            "google.confirmation.shown",
            tool="gmail_send",
            user_id=user_id,
            conversation_id=conversation_id,
            risk_level=payload.get("risk_level"),
            recipients=len(args.to) + len(args.cc or []) + len(args.bcc or []),
        )
        return _format_confirmation(payload)

    return StructuredTool.from_function(
        func=_gmail_send,
        name="gmail_send",
        description=_GMAIL_SEND_DESCRIPTION,
        args_schema=GmailSendArgs,
    )


_GMAIL_SEARCH_DESCRIPTION = (
    "Search the user's Gmail using Gmail's standard query syntax. "
    "Examples: 'from:alice@example.com', 'is:unread label:inbox', "
    "'subject:invoice newer_than:7d', 'has:attachment after:2026/01/01'. "
    "Returns a list of matching messages with snippets and key headers "
    "(Subject, From, To, Date). Use gmail_get with a result's 'id' to fetch "
    "the full body of a specific message. Note: absolute date filters "
    "(after:/before:) use PST midnight — prefer relative (newer_than:Nd) "
    "when possible."
)


def make_gmail_search(
    user_id: str, conversation_id: Optional[str] = None
) -> StructuredTool:
    """``gmail_search`` — Gmail q syntax 기반 메시지 검색 (read-only).

    list endpoint 는 ``[{id, threadId}]`` 만 반환 → 각 메시지에 대해
    ``format=metadata`` 로 snippet + 화이트리스트 헤더만 fetch (전체 본문
    노출 회피).  N+1 호출이지만 ``max_results`` 기본 10 으로 캡.
    """

    async def _gmail_search(**kwargs) -> str:
        args = GmailSearchArgs(**kwargs)
        log.info(
            "gmail_search: user_id=%s q_len=%d max=%d page_token=%s",
            user_id,
            len(args.q),
            args.max_results,
            "yes" if args.page_token else "no",
        )

        list_params: dict[str, Any] = {
            "q": args.q,
            "maxResults": args.max_results,
        }
        if args.page_token:
            list_params["pageToken"] = args.page_token

        try:
            list_resp = await call_google_api(
                method="GET",
                path=_GMAIL_LIST_PATH,
                user_id=user_id,
                host=_GMAIL_HOST,
                params=list_params,
            )
        except GoogleReauthRequired as exc:
            return _format_error("google_reauth_required", reason=exc.reason)
        except GoogleApiError as exc:
            return _format_error(
                f"gmail_api_error_{exc.status_code}",
                message=str(exc.message)[:300],
            )

        message_stubs = list_resp.get("messages") or []
        results: list[dict[str, Any]] = []
        for stub in message_stubs:
            mid = stub.get("id")
            if not mid:
                continue
            try:
                meta = await call_google_api(
                    method="GET",
                    path=f"{_GMAIL_LIST_PATH}/{mid}",
                    user_id=user_id,
                    host=_GMAIL_HOST,
                    params={
                        "format": "metadata",
                        "metadataHeaders": [
                            "Subject",
                            "From",
                            "To",
                            "Cc",
                            "Date",
                            "Reply-To",
                            "Message-Id",
                        ],
                    },
                )
            except GoogleReauthRequired as exc:
                # 검색 도중 reauth 발생 — 전체 응답을 reauth error 로.
                return _format_error("google_reauth_required", reason=exc.reason)
            except GoogleApiError as exc:
                # 개별 메시지가 사라졌거나 권한 손실 — 그 한 건만 skip.
                log.warning(
                    "gmail_search: meta fetch failed for id=%s status=%d",
                    mid,
                    exc.status_code,
                )
                continue
            results.append(
                {
                    "id": meta.get("id", mid),
                    "thread_id": meta.get("threadId"),
                    "snippet": meta.get("snippet", ""),
                    "headers": _pick_headers(meta),
                    "label_ids": meta.get("labelIds", []),
                }
            )

        payload = {
            "results": results,
            "next_page_token": list_resp.get("nextPageToken"),
            "result_size_estimate": list_resp.get("resultSizeEstimate"),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_gmail_search,
        name="gmail_search",
        description=_GMAIL_SEARCH_DESCRIPTION,
        args_schema=GmailSearchArgs,
    )


_GMAIL_GET_DESCRIPTION = (
    "Fetch the full content of a single Gmail message by its id "
    "(typically obtained from gmail_search results). Returns the plain-text "
    "body, headers (Subject/From/To/Date/...), labels, and the Gmail thread id. "
    "If only HTML body exists, returns a best-effort text extraction with "
    "the 'body_is_html_fallback' flag set."
)


def make_gmail_get(
    user_id: str,
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> StructuredTool:
    """``gmail_get`` — 단일 메시지의 full payload + text body 추출 (read-only).

    ``extraction_config`` 가 주어지면 첨부(PDF/Office)도 기존 RAG Loader 로 본문
    추출.  None 이면 첨부는 메타데이터 노트만 (다운로드 X).
    """

    async def _gmail_get(**kwargs) -> str:
        args = GmailGetArgs(**kwargs)
        log.info("gmail_get: user_id=%s message_id=%s", user_id, args.message_id)

        try:
            resp = await call_google_api(
                method="GET",
                path=f"{_GMAIL_LIST_PATH}/{args.message_id}",
                user_id=user_id,
                host=_GMAIL_HOST,
                params={"format": "full"},
            )
        except GoogleReauthRequired as exc:
            return _format_error("google_reauth_required", reason=exc.reason)
        except GoogleApiError as exc:
            return _format_error(
                f"gmail_api_error_{exc.status_code}",
                message=str(exc.message)[:300],
            )

        payload_root = resp.get("payload") or {}
        body, is_html_fallback = _extract_message_body(payload_root)
        # [T5/M2] 장문 본문 per-message cap — 다건 종합 시 컨텍스트 폭증 방지.
        body_truncated = len(body) > MAX_EXTRACT_CHARS
        if body_truncated:
            body = body[:MAX_EXTRACT_CHARS]
        attachments = await _process_attachments(
            user_id=user_id,
            message_id=args.message_id,
            payload=payload_root,
            extraction_config=extraction_config,
        )
        return json.dumps(
            {
                "id": resp.get("id"),
                "thread_id": resp.get("threadId"),
                "snippet": resp.get("snippet", ""),
                "headers": _pick_headers(resp),
                "label_ids": resp.get("labelIds", []),
                "body": body,
                "body_is_html_fallback": is_html_fallback,
                "body_truncated": body_truncated,
                "attachments": attachments,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        coroutine=_gmail_get,
        name="gmail_get",
        description=_GMAIL_GET_DESCRIPTION,
        args_schema=GmailGetArgs,
    )


_GMAIL_GET_BATCH_DESCRIPTION = (
    "Fetch the full content of MULTIPLE Gmail messages in ONE call (batch of "
    "gmail_get). Pass a list of message ids from gmail_search. PREFER this over "
    "many separate gmail_get calls when gathering several emails — it conserves "
    "the tool-call budget and returns all results together as {results: [...]}, "
    "each with the body and the extracted text of PDF/Office attachments."
)


def make_gmail_get_batch(
    user_id: str,
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> StructuredTool:
    """``gmail_get_batch`` — 여러 메시지를 1회 호출로 일괄 읽기 (read-only).

    단건 ``gmail_get`` 로직을 재사용해 N개 메시지(본문+첨부)를 읽고
    ``{results: [...]}`` 로 묶어 반환.  도구 호출 1회만 소비해 budget 절약.
    개별 실패는 그 항목만 error 로 격리(최상위는 ``results``).
    """
    single = make_gmail_get(
        user_id, conversation_id=conversation_id, extraction_config=extraction_config
    )

    async def _gmail_get_batch(**kwargs) -> str:
        args = GmailGetBatchArgs(**kwargs)
        log.info("gmail_get_batch: user_id=%s count=%d", user_id, len(args.message_ids))
        results: list[Any] = []
        used = 0
        for mid in args.message_ids[:_MAX_BATCH_IDS]:
            if used >= _BATCH_MAX_CHARS:
                results.append(
                    {"id": mid, "note": "batch output budget reached; not read"}
                )
                continue
            try:
                raw = await single.coroutine(message_id=mid)
                results.append(json.loads(raw))
                used += len(raw)
            except Exception as exc:  # 개별 항목 실패 격리 — 나머지는 정상 반환.
                results.append({"id": mid, "error": str(exc)[:200]})
        return json.dumps({"results": results}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_gmail_get_batch,
        name="gmail_get_batch",
        description=_GMAIL_GET_BATCH_DESCRIPTION,
        args_schema=GmailGetBatchArgs,
    )


# ---------------------------------------------------------------------------
# T2 — 첨부 수집 + 추출
# ---------------------------------------------------------------------------


def _collect_attachments(payload: dict) -> list[dict]:
    """MIME 트리에서 첨부 part(filename + body.attachmentId)를 재귀 수집."""
    out: list[dict] = []

    def _walk(part: Any) -> None:
        if not isinstance(part, dict):
            return
        body = part.get("body") or {}
        filename = part.get("filename") or ""
        att_id = body.get("attachmentId")
        if filename and att_id:
            out.append(
                {
                    "filename": filename,
                    "mimeType": part.get("mimeType", ""),
                    "attachment_id": att_id,
                    "size": body.get("size"),
                }
            )
        for sub in part.get("parts") or []:
            _walk(sub)

    _walk(payload)
    return out


def _decode_b64url_bytes(data: str) -> bytes:
    """base64url(padding 없는 Gmail 형식) → raw bytes.  실패는 빈 bytes."""
    if not data:
        return b""
    try:
        return base64.urlsafe_b64decode(data + "===")
    except Exception:
        return b""


def _within_attach_size(size: Any) -> bool:
    """[H2] 첨부 size(int bytes)가 추출 임계 이내인지.  미상이면 best-effort 허용."""
    if size is None:
        return True
    try:
        return int(size) <= MAX_EXTRACT_BYTES
    except (TypeError, ValueError):
        return True


async def _process_attachments(
    *,
    user_id: str,
    message_id: str,
    payload: dict,
    extraction_config: Optional[dict],
    char_budget: int = MAX_EXTRACT_CHARS,
) -> list[dict]:
    """첨부별 본문 추출(추출 가능 + size + 활성) 또는 메타 노트.

    [T5/M2] 한 메시지의 첨부 본문 합산이 ``char_budget`` 를 넘지 않도록 누적 cap
    (본문 cap 과 합쳐 메시지 1건 총량을 bound).  실패/비활성/비추출/대용량 →
    ``{"filename", "mimeType", "note"}`` (다운로드 X).  본문 보존을 위해 첨부
    fetch 실패는 노트로 격리(전체 abort 안 함).
    """
    out: list[dict] = []
    used = 0
    for att in _collect_attachments(payload)[:_MAX_ATTACHMENTS]:
        fn = att["filename"]
        amime = att["mimeType"]
        size = att.get("size")

        if not (
            extraction_config and is_extractable(amime) and _within_attach_size(size)
        ):
            if not extraction_config:
                note = "extraction disabled"
            elif not is_extractable(amime):
                note = "binary attachment, no text extraction (image/other)"
            else:
                note = "attachment too large for extraction"
            out.append({"filename": fn, "mimeType": amime, "note": note})
            continue

        if used >= char_budget:
            out.append(
                {
                    "filename": fn,
                    "mimeType": amime,
                    "note": "message attachment budget reached; not extracted",
                }
            )
            continue

        try:
            att_resp = await call_google_api(
                method="GET",
                path=f"{_GMAIL_LIST_PATH}/{message_id}/attachments/{att['attachment_id']}",
                user_id=user_id,
                host=_GMAIL_HOST,
            )
        except (GoogleReauthRequired, GoogleApiError) as exc:
            log.warning("gmail_get attachment fetch failed for %s: %s", fn, exc)
            out.append(
                {"filename": fn, "mimeType": amime, "note": "attachment fetch failed"}
            )
            continue

        att_bytes = _decode_b64url_bytes(att_resp.get("data", ""))
        extracted = await extract_text_from_bytes(
            att_bytes, fn, amime, extraction_config=extraction_config
        )
        content = extracted.get("content") or ""
        if content:
            att_truncated = extracted.get("truncated", False)
            remaining = char_budget - used
            if len(content) > remaining:
                content = content[:remaining]
                att_truncated = True
            used += len(content)
            out.append(
                {
                    "filename": fn,
                    "mimeType": amime,
                    "content": content,
                    "truncated": att_truncated,
                }
            )
        else:
            out.append({"filename": fn, "mimeType": amime, "note": "no text extracted"})
    return out


# ---------------------------------------------------------------------------
# Helpers — header pick, MIME body extract, error formatting
# ---------------------------------------------------------------------------


def _pick_headers(message: dict) -> dict[str, str]:
    """``payload.headers`` 중 화이트리스트 만 dict 로.  중복 헤더는 마지막 값."""
    headers = ((message.get("payload") or {}).get("headers")) or []
    out: dict[str, str] = {}
    for h in headers:
        name = h.get("name", "")
        if name in _INTERESTING_HEADERS:
            out[name] = h.get("value", "")
    return out


def _decode_b64url(data: str) -> str:
    """base64url (padding 없는 Gmail 형식) → utf-8 string.  디코드 실패는 빈 string."""
    if not data:
        return ""
    try:
        # 패딩이 부족할 수 있어 끝에 '===' 추가 (잉여 padding 은 무시됨).
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_for_mime(part: dict, target_mime: str) -> Optional[str]:
    """MIME 트리를 재귀로 걸어 첫 번째 ``target_mime`` part 의 본문을 decode."""
    if not isinstance(part, dict):
        return None
    if part.get("mimeType") == target_mime:
        data = (part.get("body") or {}).get("data", "")
        decoded = _decode_b64url(data)
        if decoded:
            return decoded
    for sub in part.get("parts") or []:
        found = _walk_for_mime(sub, target_mime)
        if found is not None:
            return found
    return None


def _strip_html(html: str) -> str:
    """최소 HTML→text — stdlib HTMLParser 로 태그 제거.  실패 시 원본 반환."""
    if not html:
        return ""
    try:
        from html.parser import HTMLParser

        class _Stripper(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.parts: list[str] = []

            def handle_data(self, data: str) -> None:  # type: ignore[override]
                self.parts.append(data)

        s = _Stripper()
        s.feed(html)
        return " ".join(p.strip() for p in s.parts if p.strip())
    except Exception:
        return html


def _extract_message_body(payload: dict) -> tuple[str, bool]:
    """payload 의 multipart MIME 에서 본문 추출.

    Returns:
        ``(body, is_html_fallback)`` — text/plain 이 있으면 그것 (False).  없으면
        text/html 을 strip 한 결과 (True).  모두 없으면 ``("", False)``.
    """
    if not payload:
        return "", False
    plain = _walk_for_mime(payload, "text/plain")
    if plain is not None:
        return plain, False
    html = _walk_for_mime(payload, "text/html")
    if html is not None:
        return _strip_html(html), True
    # 단일 part 케이스 — payload 자체가 본문 (예: 본문 한 줄 + 첨부 없음).
    if payload.get("mimeType") in ("text/plain",):
        data = (payload.get("body") or {}).get("data", "")
        decoded = _decode_b64url(data)
        if decoded:
            return decoded, False
    return "", False


# ---------------------------------------------------------------------------
# Response formatters — marker + JSON payload
# ---------------------------------------------------------------------------


def _format_confirmation(payload: dict) -> str:
    """Frontend 가 GmailConfirmation.svelte 를 렌더할 수 있는 직렬화 응답."""
    return f"{GMAIL_CONFIRM_MARKER}\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _format_quota_error(tool_name: str, limit: int) -> str:
    """per-turn write quota 초과 — LLM 에 사용자 확인 안내 유도용 응답."""
    payload = {
        "error": "batch_quota_exceeded",
        "tool": tool_name,
        "limit": limit,
        "hint": (
            "이번 메시지에서 가능한 발송 횟수를 초과했습니다.  사용자에게 "
            "한꺼번에 보낼 대상을 모아 한 번에 발송할지 확인해 주세요."
        ),
    }
    return (
        f"{GMAIL_QUOTA_MARKER}\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    )


def _format_error(error_code: str, **fields: Any) -> str:
    """gmail_search / gmail_get 의 외부 호출 실패를 LLM-친화 JSON 으로.

    marker 는 붙이지 않음 — 검색/조회 실패는 frontend 가 별도 UI 를 띄울 게
    없고, LLM 이 사용자 안내 메시지를 작성하면 됨.  reauth 의 경우는 frontend
    가 OAuth reconnect 안내를 띄우도록 LLM 응답 안에 명시 안내를 포함.
    """
    payload: dict[str, Any] = {"error": error_code, **fields}
    if error_code == "google_reauth_required":
        payload.setdefault(
            "hint",
            "Google 계정 재인증이 필요합니다.  사용자에게 설정 > 연결에서 Google "
            "다시 연결을 안내해 주세요.",
        )
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


__all__ = [
    "GMAIL_CONFIRM_MARKER",
    "GMAIL_QUOTA_MARKER",
    "GmailGetArgs",
    "GmailGetBatchArgs",
    "GmailSearchArgs",
    "GmailSendArgs",
    "make_gmail_get",
    "make_gmail_get_batch",
    "make_gmail_search",
    "make_gmail_send",
    "make_gmail_tools",
]


def make_gmail_tools(
    user_id: str,
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> list[StructuredTool]:
    """user_id + conversation_id 바인딩 Gmail 툴 모음.

    구성:
    - ``gmail_send``   (sensitive scope ``gmail.send``)     — HITL preview
    - ``gmail_search`` (restricted scope ``gmail.readonly``) — read-only
    - ``gmail_get``    (restricted scope ``gmail.readonly``) — read-only +
      첨부(PDF/Office) 추출 (``extraction_config`` 제공 시)

    ``conversation_id`` 는 ``gmail_send`` 의 per-turn write quota scope.
    ``extraction_config`` 는 ``gmail_get`` 의 첨부 추출용(None → 메타 노트만).
    """
    return [
        make_gmail_send(user_id, conversation_id=conversation_id),
        make_gmail_search(user_id, conversation_id=conversation_id),
        make_gmail_get(
            user_id,
            conversation_id=conversation_id,
            extraction_config=extraction_config,
        ),
        make_gmail_get_batch(
            user_id,
            conversation_id=conversation_id,
            extraction_config=extraction_config,
        ),
    ]
