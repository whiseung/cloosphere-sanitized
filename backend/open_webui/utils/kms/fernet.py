"""
Fernet provider — default KMS backend for self-managed deployments.

Behavior:
    encrypt() → writes tagged form: kms:fernet:fernet:v1:<gAAAAA...>
    decrypt() → accepts BOTH tagged form AND legacy untagged 'gAAAAA...'
                (so existing data keeps working without migration)

Key derivation: SHA-256(WEBUI_SECRET_KEY) → Fernet key (unchanged from
legacy `utils/crypto.py` to preserve binary compatibility with existing
ciphertexts).
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from open_webui.env import WEBUI_SECRET_KEY
from open_webui.utils.kms.base import (
    KMSProvider,
    build_tag,
    is_legacy_fernet,
    parse_tag,
)

log = logging.getLogger(__name__)


def _derive_fernet_key() -> bytes:
    """Derive a 32-byte Fernet-compatible key from WEBUI_SECRET_KEY.

    Identical to legacy utils.crypto._get_fernet_key — must stay
    bit-compatible so legacy gAAAAA ciphertexts decrypt correctly.
    """
    key_bytes = hashlib.sha256(WEBUI_SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


class FernetProvider(KMSProvider):
    name = "fernet"
    algo = "fernet"

    def __init__(self) -> None:
        self._fernet = Fernet(_derive_fernet_key())

    def encrypt(self, plaintext: str, context: Optional[dict] = None) -> str:
        if not plaintext:
            return ""
        try:
            ciphertext = self._fernet.encrypt(plaintext.encode()).decode()
        except Exception as e:
            log.error(f"Fernet encrypt failed: {e}")
            raise ValueError("Failed to encrypt value")
        return build_tag(self.name, self.algo, ciphertext)

    def decrypt(self, tagged_or_legacy: str, context: Optional[dict] = None) -> str:
        if not tagged_or_legacy:
            return ""

        # Tagged form: kms:fernet:fernet:v1:<ciphertext>
        parsed = parse_tag(tagged_or_legacy)
        if parsed is not None:
            if parsed.provider != self.name or parsed.algo != self.algo:
                raise ValueError(
                    f"FernetProvider received non-fernet tag: provider={parsed.provider} algo={parsed.algo}"
                )
            return self._fernet_decrypt(parsed.payload)

        # Legacy untagged: gAAAAA...
        if is_legacy_fernet(tagged_or_legacy):
            return self._fernet_decrypt(tagged_or_legacy)

        # Plaintext passthrough — caller should have routed via KMSRouter
        # which handles plaintext, so reaching here is suspicious.
        raise ValueError("FernetProvider.decrypt called on non-fernet value")

    def _fernet_decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            log.error("Fernet decrypt: invalid token (key may have changed)")
            raise ValueError(
                "Failed to decrypt value - encryption key may have changed"
            )
        except Exception as e:
            log.error(f"Fernet decrypt failed: {e}")
            raise ValueError("Failed to decrypt value")
