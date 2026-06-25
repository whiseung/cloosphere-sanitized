"""대칭 암호화 헬퍼 — DB 컬럼 단위 비밀 보호.

`WEBUI_SECRET_KEY` 를 KEK(SHA256 → 32B)으로 derive 해 Fernet 인스턴스를 만든다.
주된 용도는 `user_oauth_token.access_token` / `refresh_token` 등 사용자 단위
OAuth 비밀 — DB 덤프/백업 유출 시 KEK 없이 복호화 불가.

Fernet 출력은 항상 `gAAAAA` prefix 의 url-safe base64 라서 평문과 구분 가능.
이 특성을 이용해 마이그레이션 없이 평문/암호문이 한 컬럼에 섞여 있어도 안전하게
조회된다 (평문은 그대로, 암호문만 복호화).

운영 환경에서 더 강한 격리가 필요하면 KEK 를 외부 KMS(Azure Key Vault / AWS
KMS) 에서 fetch 하도록 `_get_kek()` 만 교체.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from open_webui.env import SRC_LOG_LEVELS, WEBUI_SECRET_KEY

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("UTILS", "INFO"))

_FERNET_PREFIX = "gAAAAA"  # Fernet 토큰 출력의 고정 접두사
_fernet_singleton: Optional[Fernet] = None


def _get_kek() -> bytes:
    """WEBUI_SECRET_KEY 기반 32바이트 url-safe base64 KEK."""
    secret = WEBUI_SECRET_KEY or ""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not secret:
        # 운영 환경에선 startup 단에서 WEBUI_SECRET_KEY 강제. 여긴 fail-loud.
        raise RuntimeError(
            "WEBUI_SECRET_KEY is empty — cannot encrypt OAuth tokens. "
            "Set WEBUI_SECRET_KEY environment variable."
        )
    digest = hashlib.sha256(secret).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    global _fernet_singleton
    if _fernet_singleton is None:
        _fernet_singleton = Fernet(_get_kek())
    return _fernet_singleton


def encrypt_str(plain: Optional[str]) -> Optional[str]:
    """평문 → Fernet 암호문(ascii). None / "" 은 그대로 반환."""
    if plain is None or plain == "":
        return plain
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_str(value: Optional[str]) -> Optional[str]:
    """Fernet 암호문(ascii) → 평문. 평문이 들어오면 그대로 반환 (마이그레이션 안전).

    복호화 실패 시 None 반환 + WARN 로그 — 호출 측이 사용자 재인증 유도하도록.
    """
    if value is None or value == "":
        return value
    if not value.startswith(_FERNET_PREFIX):
        # 암호화 안 된 평문 — 기존 row 호환 또는 외부 입력 그대로 처리.
        return value
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        log.warning(f"Failed to decrypt token (KEK rotated or corrupted?): {e}")
        return None
