"""HITL confirm 후의 실제 외부 호출 (Gmail send / Calendar event create).

Confirm endpoint (``routers/google_actions.py``) 에서만 호출.  LangChain tool
wrapper (``gmail.py``, ``calendar.py``) 는 본 모듈을 호출하지 않는다 — tool 은
HITL preview 만 반환.

Gmail 설계:
- ``stdlib email.message.EmailMessage`` 사용 — ``MIMEMultipart`` 보다 footgun 적음.
- F1 회피: ``base64.urlsafe_b64encode`` (NOT ``b64encode``).
- ``in_reply_to`` 는 RFC822 Message-Id 헤더 값 — Gmail 이 In-Reply-To /
  References 헤더로부터 thread 추론.  명시적 ``threadId`` 필드는 MVP 에서 미설정
  (multi-message thread 의 정확한 id 가 frontend 에 전달되는지 불확실 — v1.1).

Calendar 설계:
- F2: ``sendUpdates`` query param 명시 (Gmail 의 기본값 ``none`` 회피 — 호출자가
  명시).  caller 책임으로 ``"all"`` / ``"externalOnly"`` / ``"none"`` 전달.
- F3: timezone 은 caller 단에서 IANA ID 로 이미 검증된 상태 (tool 의
  ``iana_timezone()``).  여기서는 그대로 전달.
- ``create_meet=True`` 시 conferenceData.createRequest + ``conferenceDataVersion=1``
  쿼리 추가.  ``requestId`` 는 unique uuid (Google 측 중복 방지).
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from email.message import EmailMessage
from typing import Any, Optional

from extension_modules.tools.google.inprocess._common import call_google_api

log = logging.getLogger(__name__)

_GMAIL_HOST = "gmail.googleapis.com"
_GMAIL_SEND_PATH = "/gmail/v1/users/me/messages/send"

_CALENDAR_HOST = "www.googleapis.com"
_CALENDAR_EVENTS_PATH = "/calendar/v3/calendars/primary/events"

_DRIVE_HOST = "www.googleapis.com"
_DRIVE_FILES_PATH = "/drive/v3/files"
_DOCS_HOST = "docs.googleapis.com"


def compose_gmail_mime(
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    in_reply_to: Optional[str] = None,
) -> str:
    """RFC822 message build + base64url encode → Gmail send ``raw`` 필드 string.

    Returns:
        ``base64.urlsafe_b64encode(msg.as_bytes())`` 의 ascii string (padding 제거).
    """
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    if in_reply_to:
        # 표준 thread continuation 헤더.  Gmail 은 In-Reply-To / References
        # 둘 다 같은 값으로 보내도 정상 처리.
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    # multipart/alternative — 깔끔한 평문(마크다운 마커 제거, 개행 보존) +
    # HTML 대체본(마크다운 렌더).  수신 클라이언트는 HTML 을 보여주고, HTML 미지원
    # 환경은 평문 fallback.  → 원문 "**굵게**"/"#"/"- " 가 그대로 노출되지 않음.
    plain = _md_to_prose(body or "")
    msg.set_content(plain)
    html = _md_to_html(body or "")
    if html:
        msg.add_alternative(html, subtype="html")
    raw_bytes = base64.urlsafe_b64encode(msg.as_bytes()).rstrip(b"=")
    return raw_bytes.decode("ascii")


async def send_gmail_now(
    *,
    user_id: str,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    in_reply_to: Optional[str] = None,
) -> dict:
    """Gmail send API 호출 — 호출자는 이미 HITL + 게이트 통과를 검증한 상태.

    Returns:
        Gmail API 응답 dict — keys: ``id``, ``threadId``, ``labelIds``.

    Raises:
        GoogleReauthRequired: 토큰 invalid_grant / 401 영구 실패.
        GoogleApiError: 그 외 4xx.
        (transient 429/5xx 은 ``call_google_api`` 의 tenacity 가 흡수)
    """
    raw = compose_gmail_mime(
        to=to, subject=subject, body=body, cc=cc, bcc=bcc, in_reply_to=in_reply_to
    )
    response = await call_google_api(
        method="POST",
        path=_GMAIL_SEND_PATH,
        user_id=user_id,
        host=_GMAIL_HOST,
        json={"raw": raw},
    )
    log.info(
        "gmail sent: user=%s recipients=%d gmail_id=%s thread=%s",
        user_id,
        len(to) + len(cc or []) + len(bcc or []),
        response.get("id"),
        response.get("threadId"),
    )
    return response


async def create_calendar_event_now(
    *,
    user_id: str,
    title: str,
    start: str,
    end: str,
    timezone: str,
    description: str = "",
    attendees: Optional[list[str]] = None,
    send_updates: str = "all",
    create_meet: bool = False,
) -> dict:
    """Calendar event create API 호출.

    Args:
        user_id: 호출 주체 (token lookup).
        title: 이벤트 제목 (Calendar API 의 ``summary``).
        start: ISO 8601 datetime string (예: ``2026-05-20T10:00:00``).
        end: ISO 8601 datetime string.
        timezone: IANA timezone ID (caller 가 ``iana_timezone()`` 으로 이미 검증).
        description: 이벤트 설명 (선택).
        attendees: 참석자 email 목록 (선택).
        send_updates: ``"all"`` / ``"externalOnly"`` / ``"none"``.  F2 — 명시 필수.
        create_meet: Meet 링크 생성 여부.  True 시 conferenceData 자동 추가.

    Returns:
        Calendar API 응답 dict — keys: ``id``, ``htmlLink``, ``hangoutLink``,
        ``conferenceData``.

    Raises:
        GoogleReauthRequired / GoogleApiError — caller 가 변환 책임.
    """
    body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone},
    }
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    params: dict[str, Any] = {"sendUpdates": send_updates}
    if create_meet:
        # conferenceData.createRequest — Meet 링크 비동기 생성.  응답 즉시
        # hangoutLink 가 안 올 수 있으므로 호출자는 conferenceData.entryPoints
        # 또는 별도 polling 으로 확인 가능 (MVP 는 응답을 그대로 사용).
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        params["conferenceDataVersion"] = 1

    response = await call_google_api(
        method="POST",
        path=_CALENDAR_EVENTS_PATH,
        user_id=user_id,
        host=_CALENDAR_HOST,
        json=body,
        params=params,
    )
    log.info(
        "calendar event created: user=%s event_id=%s attendees=%d meet=%s",
        user_id,
        response.get("id"),
        len(attendees or []),
        bool(response.get("hangoutLink")),
    )
    return response


# Markdown inline/leading 마커 stripper — Docs insertText 는 평문이라 ##/**
# 가 그대로 박힌다.  gmail.py 의 _strip_html 은 모든 텍스트를 단일 공백으로
# join 해 한 줄로 뭉개므로 재사용 금지 (spec §4.1).  여기서는 줄 단위로 처리해
# 줄바꿈·불릿을 보존한다.
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_MD_LIST_RE = re.compile(r"^(\s*)[-*+]\s+")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)")


def _md_to_prose(text: str) -> str:
    """LLM markdown 출력을 Docs insertText 용 평문으로 변환 — 줄바꿈/불릿 보존.

    - 선두 ``#+ `` heading 마커 제거.
    - 리스트 마커 ``- ``/``* ``/``+ `` → ``• `` (들여쓰기 유지).
    - ``[text](url)`` → ``text (url)``.
    - ``**``/``__``/``*``/``_``/백틱 강조 마커 제거.
    - 빈 줄/줄바꿈은 그대로 둔다 (gmail _strip_html 의 한 줄 뭉개기 회피).
    """
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.split("\n"):
        line = _MD_HEADING_RE.sub("", line)
        line = _MD_LIST_RE.sub(lambda m: f"{m.group(1)}• ", line)
        line = _MD_LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", line)
        line = _MD_EMPHASIS_RE.sub("", line)
        out_lines.append(line)
    return "\n".join(out_lines)


def _md_to_html(text: str) -> str:
    """LLM markdown 출력 → 이메일용 HTML (gmail HTML alternative).

    - ``nl2br``: LLM 이 단일 줄바꿈으로 쓴 개행을 ``<br>`` 로 보존 (표준 markdown
      은 단일 개행을 무시 → 메일에서 줄이 다 붙어버리는 문제 방지).
    - ``extra``/``sane_lists``: 표·리스트·코드 등 일반 마크다운 처리.
    - 메일 클라이언트가 ``<head>`` style 을 자주 제거하므로 body wrapper 에
      inline style 만 부여 (system 폰트 + 줄간격).
    """
    if not text:
        return ""
    import markdown as _markdown  # lazy — 도구 빌드 시점 import 비용 회피

    rendered = _markdown.markdown(
        text,
        extensions=["extra", "nl2br", "sane_lists"],
        output_format="html",
    )
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,'
        "Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;"
        'color:#1f2328;">' + rendered + "</div>"
    )


async def create_drive_doc_now(
    *,
    user_id: str,
    name: str,
    content: str,
    folder_id: Optional[str] = None,
) -> dict:
    """Google Doc 생성 — 2-call (Drive files.create + Docs batchUpdate).

    ``call_google_api`` 는 JSON body 만 보내므로 multipart 업로드가 불가하다.
    대신 빈 Google Doc 을 만든 뒤 (Drive API) 본문을 삽입한다 (Docs API).
    둘 다 순수 JSON — 인프라 무변경.

    Args:
        user_id: 호출 주체 (token lookup).
        name: 문서 제목.
        content: 본문 (LLM markdown).  ``_md_to_prose`` 로 평문 변환 후 삽입.
        folder_id: 부모 폴더 ID (선택).  지정 시 ``parents`` 로 전달.

    Returns:
        ``{"id", "web_view_link", "name"}``.

    Raises:
        GoogleReauthRequired / GoogleApiError — caller 가 변환 책임.  Step 2
            (Docs batchUpdate) 에서 실패하면 빈 orphan 문서가 남으므로, 예외
            객체에 ``.partial = {"id", "web_view_link", "name"}`` 를 실어
            confirm endpoint 가 ``DRIVE_CREATE_DOC_FAILED.after_state`` 로
            추적 가능하게 한다 (자동삭제 안 함 — spec §4.1).
    """
    file_body: dict[str, Any] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        file_body["parents"] = [folder_id]

    # Step 1 — 빈 Google Doc 생성.  기본 응답엔 webViewLink 가 없어 fields 명시 필수.
    doc = await call_google_api(
        method="POST",
        path=_DRIVE_FILES_PATH,
        user_id=user_id,
        host=_DRIVE_HOST,
        json=file_body,
        params={"fields": "id,name,webViewLink"},
    )
    doc_id = doc["id"]
    web_view_link = (
        doc.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit"
    )
    result = {"id": doc_id, "web_view_link": web_view_link, "name": name}

    prose = _md_to_prose(content)
    # Step 2 — 본문 삽입.  index=1 필수 (index=0 은 초기 sectionBreak 에 닿아 400
    # INVALID_ARGUMENT).  segmentId 생략 = 본문.  줄바꿈 prepend/append 금지.
    try:
        await call_google_api(
            method="POST",
            path=f"/v1/documents/{doc_id}:batchUpdate",
            user_id=user_id,
            host=_DOCS_HOST,
            json={
                "requests": [{"insertText": {"location": {"index": 1}, "text": prose}}]
            },
        )
    except Exception as exc:
        # orphan 문서 — Step1 성공 / Step2 실패.  doc_id 를 예외에 실어 추적.
        try:
            exc.partial = result  # type: ignore[attr-defined]
        except Exception:
            pass
        log.warning(
            "drive doc body insert failed (orphan doc left): user=%s doc_id=%s err=%s",
            user_id,
            doc_id,
            exc,
        )
        raise

    log.info(
        "drive doc created: user=%s doc_id=%s name_len=%d folder=%s",
        user_id,
        doc_id,
        len(name or ""),
        folder_id or "-",
    )
    return result


__all__ = [
    "compose_gmail_mime",
    "create_calendar_event_now",
    "create_drive_doc_now",
    "send_gmail_now",
]
