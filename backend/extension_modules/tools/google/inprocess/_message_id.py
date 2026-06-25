"""Stateless message_id minting for Google HITL drafts.

T-B13 의 acceptance "owner == user.id 검증" 을 multi-worker (UVICORN_WORKERS
>1) 환경에서도 만족시키기 위해 in-memory pending registry 대신 HMAC 으로
message_id 에 소유자를 묶는다.  Confirm endpoint 는 message_id + JWT user.id
만으로 ownership 을 검증한다 (DB lookup 불필요).

Format: ``{uuid_hex32}.{sig_hex16}``  (총 49자, dot 1개)

- ``uuid_hex32`` : ``secrets.token_hex(16)`` — 128bit 엔트로피
- ``sig_hex16``  : ``HMAC-SHA256(WEBUI_SECRET_KEY, f"{user_id}:{uuid}")`` 의
  앞 16자 = 64bit. 위조 시도 = 2^64.

WEBUI_SECRET_KEY 가 회수되면 모든 미확인 drafts 가 무효화 — 동일 사용자가
같은 메시지로 두 번 confirm 해도 (즉 replay) 는 ``verify_message_id`` 가
통과시키지만, 실제 idempotency 는 audit log 가 차단 (T-B13 acceptance d).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from open_webui.env import WEBUI_SECRET_KEY

_SIG_LEN = 16  # hex chars = 64 bits


def _compute_sig(user_id: str, uid: str) -> str:
    """HMAC-SHA256 truncated to ``_SIG_LEN`` hex chars."""
    payload = f"{user_id}:{uid}".encode("utf-8")
    key = (WEBUI_SECRET_KEY or "").encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()[:_SIG_LEN]


def mint_message_id(user_id: str) -> str:
    """``{uuid}.{sig}`` 형태의 새 message_id 발급 — user_id 에 HMAC 으로 바인딩.

    Raises:
        ValueError: user_id 가 빈 string.
    """
    if not user_id:
        raise ValueError("user_id required to mint message_id")
    uid = secrets.token_hex(16)
    sig = _compute_sig(user_id, uid)
    return f"{uid}.{sig}"


def verify_message_id(message_id: str, user_id: str) -> bool:
    """``message_id`` 가 ``user_id`` 로 발급된 것인지 constant-time 검증.

    어떤 parse 실패나 길이 불일치도 False — IDOR 공격면을 최소화.
    """
    if not message_id or not user_id or "." not in message_id:
        return False
    try:
        uid, sig = message_id.rsplit(".", 1)
    except ValueError:
        return False
    if len(sig) != _SIG_LEN or not uid:
        return False
    expected = _compute_sig(user_id, uid)
    return hmac.compare_digest(expected, sig)


__all__ = ["mint_message_id", "verify_message_id"]
