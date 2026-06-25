"""HITL (Human-In-The-Loop) 응답 생성 helper.

Write 액션 (gmail_send, calendar_create_event) 의 tool wrapper 는 곧바로
외부 호출을 하지 않고 사용자 confirm 화면을 띄울 수 있도록 ``confirmation_required``
마커가 포함된 응답을 LLM 에 반환한다.  실제 발송/등록은 별도 confirm
endpoint (T-B13 / T-B18) 가 받는다.

응답 구조 (Gmail):
    {
        "confirmation_required": True,
        "tool": "gmail_send",
        "message_id": "<uuid>.<sig>",        # HMAC-bound, confirm endpoint path
        "risk_level": "low" | "high",
        "draft": { to, cc, bcc, subject, body, in_reply_to },
        "recipients_meta": [{"email": "...", "domain": "...", "is_external": bool}, ...]
    }

응답 구조 (Calendar):
    {
        "confirmation_required": True,
        "tool": "calendar_create_event",
        "message_id": "<uuid>.<sig>",        # HMAC-bound, confirm endpoint path
        "risk_level": "low" | "high",
        "draft": { title, description, start, end, timezone, attendees, send_updates, create_meet },
        "attendees_meta": [{"email": "...", "is_external": bool}, ...]
    }

Risk classifier (plan §5.9 — anti cargo-cult confirm):
- low  : 내부 도메인 단일 수신자 + body < 1000자
- high : 외부 도메인 / 3명 이상 / cc/bcc / 스레드 회신 / body ≥ 1000자

내부 도메인은 ``INTERNAL_EMAIL_DOMAINS`` 환경변수 (콤마 구분) 로 설정.  비어
있으면 모든 도메인을 external 취급 (안전 default — 모두 2-click 강제).
"""

from __future__ import annotations

import os
from typing import Any, Optional

# 내부 도메인 list — 환경변수 ``INTERNAL_EMAIL_DOMAINS=cloocus.com,acme.com`` 형식.
# 환경변수가 없거나 비어 있으면 빈 set → 모든 수신자 external.
_INTERNAL_DOMAINS_RAW = os.environ.get("INTERNAL_EMAIL_DOMAINS", "")
INTERNAL_EMAIL_DOMAINS: frozenset[str] = frozenset(
    d.strip().lower() for d in _INTERNAL_DOMAINS_RAW.split(",") if d.strip()
)

_GMAIL_BODY_HIGH_RISK_LEN = 1000
_RECIPIENT_HIGH_RISK_COUNT = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_domain(email: str) -> str:
    """간단 domain 추출 — '@' 우측을 lowercase 로.  부적절 값은 빈 string."""
    if not isinstance(email, str) or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def _is_external_domain(domain: str) -> bool:
    """내부 도메인 list 와 비교.  list 가 비어 있으면 모두 external (안전)."""
    if not domain:
        return True
    if not INTERNAL_EMAIL_DOMAINS:
        return True
    return domain not in INTERNAL_EMAIL_DOMAINS


# ---------------------------------------------------------------------------
# Risk classifier
# ---------------------------------------------------------------------------


def classify_gmail_risk(
    *,
    to: list[str],
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    body: str = "",
    in_reply_to: Optional[str] = None,
) -> str:
    """Gmail draft 의 risk level 분류 — 'low' or 'high'.

    high 조건 (OR):
    - 외부 도메인 수신자가 한 명이라도 포함
    - 수신자 (to + cc + bcc) 총 ≥ 3명
    - cc / bcc 사용 (수신 범위 확장)
    - in_reply_to 사용 (스레드 회신 — 이전 대화 N개 포함)
    - body 길이 ≥ 1000자

    그 외 (내부 도메인 단일 수신자 + body 짧음) = low.
    """
    cc = cc or []
    bcc = bcc or []
    all_recipients = [*to, *cc, *bcc]

    if len(all_recipients) >= _RECIPIENT_HIGH_RISK_COUNT:
        return "high"
    if cc or bcc:
        return "high"
    if in_reply_to:
        return "high"
    if len(body or "") >= _GMAIL_BODY_HIGH_RISK_LEN:
        return "high"

    for addr in all_recipients:
        if _is_external_domain(_extract_domain(addr)):
            return "high"

    return "low"


def classify_calendar_risk(
    *,
    attendees: Optional[list[dict]] = None,
    send_updates: str = "none",
    description: str = "",
) -> str:
    """Calendar draft 의 risk level 분류.

    high 조건:
    - 외부 도메인 참석자 한 명이라도 포함
    - 참석자 ≥ 3명
    - send_updates != 'none' (참석자에게 알림 메일 발송 — 외부 도달)
    - description 길이 ≥ 1000자
    """
    attendees = attendees or []

    if len(attendees) >= _RECIPIENT_HIGH_RISK_COUNT:
        return "high"
    if send_updates and send_updates != "none":
        return "high"
    if len(description or "") >= _GMAIL_BODY_HIGH_RISK_LEN:
        return "high"

    for attendee in attendees:
        email = attendee.get("email", "") if isinstance(attendee, dict) else ""
        if _is_external_domain(_extract_domain(email)):
            return "high"

    return "low"


# ---------------------------------------------------------------------------
# Confirmation response builders
# ---------------------------------------------------------------------------


def _recipients_meta(addresses: list[str]) -> list[dict[str, Any]]:
    """이메일 list 를 anti-spoof 표시용 메타 list 로.  domain + external 플래그."""
    meta: list[dict[str, Any]] = []
    for addr in addresses or []:
        domain = _extract_domain(addr)
        meta.append(
            {
                "email": addr,
                "domain": domain,
                "is_external": _is_external_domain(domain),
            }
        )
    return meta


def make_gmail_confirmation(
    *,
    message_id: str,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    in_reply_to: Optional[str] = None,
) -> dict[str, Any]:
    """``gmail_send`` 의 HITL 응답을 build.

    Args:
        message_id: ``mint_message_id(user_id)`` 로 발급된 HMAC-bound 식별자.
            Frontend 가 confirm 시 ``POST /gmail/confirm/{message_id}`` 의
            path 로 그대로 echo 한다.

    실제 발송은 frontend confirm → ``POST /api/v1/google/gmail/confirm/{message_id}``
    (T-B13) 가 받는다.  이 함수는 frontend 미리보기 컴포넌트
    (``GmailConfirmation.svelte``) 에 그대로 전달될 draft + meta.
    """
    risk = classify_gmail_risk(
        to=to, cc=cc, bcc=bcc, body=body, in_reply_to=in_reply_to
    )
    return {
        "confirmation_required": True,
        "tool": "gmail_send",
        "message_id": message_id,
        "risk_level": risk,
        "draft": {
            "to": list(to),
            "cc": list(cc) if cc else [],
            "bcc": list(bcc) if bcc else [],
            "subject": subject,
            "body": body,
            "in_reply_to": in_reply_to,
        },
        "recipients_meta": _recipients_meta([*to, *(cc or []), *(bcc or [])]),
    }


def make_calendar_confirmation(
    *,
    message_id: str,
    title: str,
    start: str,
    end: str,
    timezone: str,
    description: str = "",
    attendees: Optional[list[dict]] = None,
    send_updates: str = "none",
    create_meet: bool = False,
) -> dict[str, Any]:
    """``calendar_create_event`` 의 HITL 응답을 build.

    Args:
        message_id: ``mint_message_id(user_id)`` 로 발급된 HMAC-bound 식별자.
            Calendar HITL confirm endpoint (T-B18) 가 path 로 받는다.

    plan §5.5: ``send_updates`` 명시 (F2 회피), IANA timezone 강제,
    ``create_meet=False`` 기본 (Meet defer — v1.1).
    """
    attendees = attendees or []
    risk = classify_calendar_risk(
        attendees=attendees, send_updates=send_updates, description=description
    )
    attendees_meta = [
        {
            "email": a.get("email", ""),
            "is_external": _is_external_domain(_extract_domain(a.get("email", ""))),
        }
        for a in attendees
        if isinstance(a, dict)
    ]
    return {
        "confirmation_required": True,
        "tool": "calendar_create_event",
        "message_id": message_id,
        "risk_level": risk,
        "draft": {
            "title": title,
            "description": description,
            "start": start,
            "end": end,
            "timezone": timezone,
            "attendees": list(attendees),
            "send_updates": send_updates,
            "create_meet": create_meet,
        },
        "attendees_meta": attendees_meta,
    }


def make_drive_confirmation(
    *,
    message_id: str,
    name: str,
    content: str,
    folder_id: Optional[str] = None,
) -> dict[str, Any]:
    """``drive_create_doc`` 의 HITL 응답을 build.

    Args:
        message_id: ``mint_message_id(user_id)`` 로 발급된 HMAC-bound 식별자.
            Drive HITL confirm endpoint (POST /drive/confirm/{message_id}) 가
            path 로 받는다.

    spec §4.5: 내 드라이브 생성은 외부 도달이 없으므로 ``risk_level`` 을 항상
    ``"low"`` 로 하드코딩한다 (gmail/calendar 의 classify_*_risk 같은 분류기를
    만들지 않음).  recipients/attendees meta 도 없음.
    """
    return {
        "confirmation_required": True,
        "tool": "drive_create_doc",
        "message_id": message_id,
        "risk_level": "low",
        "draft": {
            "name": name,
            "content": content,
            "folder_id": folder_id,
        },
    }


__all__ = [
    "INTERNAL_EMAIL_DOMAINS",
    "classify_gmail_risk",
    "classify_calendar_risk",
    "make_gmail_confirmation",
    "make_calendar_confirmation",
    "make_drive_confirmation",
]
