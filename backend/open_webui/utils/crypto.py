"""
Encryption utilities for sensitive data like database credentials.

This module is a thin wrapper around the KMS router (`utils/kms/`).
The default backend is Fernet (WEBUI_SECRET_KEY-derived) for self-managed
deployments. Operators can switch to Azure Key Vault / AWS KMS / GCP KMS /
HashiCorp Vault without any call-site changes — the router auto-detects
the storage tag on each value.

Backward compatibility:
    - Legacy untagged 'gAAAAA...' Fernet ciphertexts keep decrypting.
    - New ciphertexts written by encrypt_value() use the tagged form
      'kms:<provider>:<algo>:v1:...' so a future provider switch can
      coexist with already-stored data.

Phase 2: encrypt_value/decrypt_value accept an optional `context` dict
(AAD context) — Phase 3 envelope providers (Azure KV / AWS KMS / GCP KMS
in AES-256-GCM mode) bind it into the GCM tag so a ciphertext written
under one (tenant, config_path) cannot be decrypted as another. The
Fernet provider ignores the context for backward binary compatibility.
"""

import logging
from typing import Optional

from open_webui.utils.kms import get_router
from open_webui.utils.kms.base import is_legacy_fernet, is_tagged
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

log = logging.getLogger(__name__)


class EncryptedText(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts on write and
    decrypts on read using the configured KMS provider.

    Use for columns whose only purpose is to store a sensitive bearer
    token / API key / password — every caller works with plaintext, the
    DB always sees ciphertext.

    Backward-compatible: a row written before this type was applied will
    contain plaintext; ``process_result_value`` detects unencrypted
    values via ``is_encrypted`` and returns them as-is, so a one-time
    migration job can re-save and the row will round-trip through
    encrypt next flush.

    The underlying SQL column type remains ``TEXT`` — applying this
    decorator to an existing column does NOT require a schema migration.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None or value == "":
            return value
        if not isinstance(value, str):
            return value
        if is_tagged(value) or is_legacy_fernet(value):
            # Already a ciphertext (e.g. a re-save of a previously
            # encrypted row, or an admin uploaded an already-encrypted
            # blob). Don't double-encrypt.
            return value
        try:
            return encrypt_value(value)
        except Exception as e:
            log.warning("EncryptedText encrypt failed: %s — storing plaintext", e)
            return value

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None or value == "":
            return value
        if not isinstance(value, str):
            return value
        if is_tagged(value) or is_legacy_fernet(value):
            try:
                return decrypt_value(value)
            except Exception as e:
                log.warning(
                    "EncryptedText decrypt failed: %s — returning ciphertext as-is",
                    e,
                )
                return value
        # Legacy plaintext row predating EncryptedText — pass through.
        return value


def encrypt_value(plain_text: str, context: Optional[dict] = None) -> str:
    """Encrypt a string value via the configured KMS provider.

    Args:
        plain_text: Value to encrypt. Empty input returns "".
        context: Optional AAD context (Phase 2+). Recommended for new
            call sites — pass `build_aad_context(config_path=..., ...)`
            from `utils.kms`. Existing positional-only call sites continue
            to work unchanged (Fernet provider ignores context).

    Returns:
        Tagged ciphertext (e.g. ``kms:fernet:fernet:v1:gAAAAA...``).
    """
    if not plain_text:
        return ""
    return get_router().encrypt(plain_text, context=context)


def decrypt_value(encrypted_text: str, context: Optional[dict] = None) -> str:
    """Decrypt a value previously produced by encrypt_value().

    Accepts both tagged (kms:...) and legacy untagged (gAAAAA...) Fernet
    ciphertexts. Plaintext input passes through unchanged (matches the
    behavior of the previous _decrypt_config_data helper).

    Args:
        encrypted_text: Tagged or legacy ciphertext, or plaintext (passthrough).
        context: Optional AAD context. Phase 3+ envelope providers require
            it to match the context used at encrypt time; Fernet ignores it.
    """
    if not encrypted_text:
        return ""
    return get_router().decrypt(encrypted_text, context=context)


def is_encrypted(value: str) -> bool:
    """True if the value appears to be a KMS-tagged or legacy Fernet ciphertext."""
    if not value:
        return False
    return is_tagged(value) or is_legacy_fernet(value)


####################################
# Sensitive value masking
####################################

MASK_PREFIX = "***"

# Key name patterns that indicate sensitive values
SENSITIVE_KEY_PATTERNS = {
    "secret",
    "password",
    "api_key",
    "api_keys",
    "credentials",
    "access_key",
    "credentials_json",
    "subscription_key",
    "service_account_key",
}


def mask_sensitive_value(value: str, show_last: int = 4) -> str:
    """
    Mask a sensitive string.
    Front portion replaced with '*', last N characters visible.
    Always ensures at least 3 leading '*' so is_masked() can detect it.
    E.g., 'sk-abc123xyz789' (15 chars) -> '***********z789' (15 chars)
         'sl123' (5 chars) -> '***23' (masked with 3 stars minimum)
    """
    if not value:
        return ""
    # Ensure at least 3 leading stars for is_masked() detection
    min_stars = 3
    if len(value) <= min_stars:
        return "*" * min_stars
    visible = max(0, len(value) - max(min_stars, len(value) - show_last))
    masked_len = len(value) - visible
    if masked_len < min_stars:
        masked_len = min_stars
        visible = len(value) - masked_len
    return "*" * masked_len + value[-visible:] if visible > 0 else "*" * masked_len


def is_masked(value: str) -> bool:
    """Check if a value is a masked placeholder (starts with * characters)."""
    if not isinstance(value, str) or len(value) < 4:
        return False
    # A masked value has leading '*' characters followed by a short visible suffix
    star_count = 0
    for ch in value:
        if ch == "*":
            star_count += 1
        else:
            break
    # At least 3 leading stars to be considered masked
    return star_count >= 3


def resolve_sensitive_value(new_value, current_value):
    """
    If new_value is a masked placeholder, keep the current value.
    Used in POST handlers to prevent overwriting secrets with masked values.

    For lists: preserves all items in new_value regardless of length difference.
    Masked items at index i are replaced with current_value[i] when available.
    """
    if isinstance(new_value, str) and is_masked(new_value):
        return current_value
    if isinstance(new_value, list):
        if not isinstance(current_value, list):
            current_value = []
        result = []
        for i, nv in enumerate(new_value):
            if isinstance(nv, str) and is_masked(nv):
                # Masked → fall back to current value if exists, else keep masked
                result.append(current_value[i] if i < len(current_value) else nv)
            else:
                result.append(nv)
        return result
    return new_value


def resolve_config_dict(new_data: dict, current_data: dict) -> dict:
    """
    Recursively walk *new_data* and resolve masked sensitive values
    against *current_data*.  Mirrors mask_config_dict but for the
    write (POST) path.

    For every key that matches SENSITIVE_KEY_PATTERNS:
      - string values that are masked → keep the current value
      - list values → element-wise resolve
    For every nested dict → recurse.
    For every list of dicts → recurse element-wise.
    """
    if not isinstance(new_data, dict):
        return new_data
    if not isinstance(current_data, dict):
        return new_data

    resolved = {}
    for key, new_val in new_data.items():
        cur_val = current_data.get(key)
        if _is_sensitive_key_name(key):
            resolved[key] = resolve_sensitive_value(new_val, cur_val)
        elif isinstance(new_val, dict) and isinstance(cur_val, dict):
            resolved[key] = resolve_config_dict(new_val, cur_val)
        elif isinstance(new_val, list):
            if cur_val is not None and isinstance(cur_val, list):
                items = []
                for i, item in enumerate(new_val):
                    cur_item = cur_val[i] if i < len(cur_val) else {}
                    if isinstance(item, dict) and isinstance(cur_item, dict):
                        items.append(resolve_config_dict(item, cur_item))
                    else:
                        items.append(item)
                resolved[key] = items
            else:
                resolved[key] = new_val
        else:
            resolved[key] = new_val
    return resolved


# Suffix patterns: any key ending with these is likely sensitive
SENSITIVE_KEY_SUFFIXES = {"_key", "_keys", "_secret", "_password", "_token"}

# Cached set of sensitive names from PersistentConfig registry
_registered_sensitive_names: set = None


def _get_registered_sensitive_names() -> set:
    """
    Lazily build a set of sensitive field names from PersistentConfig registry.
    This connects mask_config_dict to the PersistentConfig sensitive declarations,
    so that sensitive=True in PersistentConfig is automatically respected by API masking.
    """
    global _registered_sensitive_names
    if _registered_sensitive_names is not None:
        return _registered_sensitive_names

    try:
        from open_webui.config import PERSISTENT_CONFIG_REGISTRY, is_sensitive_path

        names = set()
        for item in PERSISTENT_CONFIG_REGISTRY:
            is_sens = item.sensitive is True or (
                item.sensitive is None and is_sensitive_path(item.config_path)
            )
            if is_sens:
                # Register both env_name and last segment of config_path
                names.add(item.env_name.lower())
                names.add(item.config_path.split(".")[-1].lower())
        _registered_sensitive_names = names
    except ImportError:
        _registered_sensitive_names = set()

    return _registered_sensitive_names


def _is_sensitive_key_name(key: str) -> bool:
    """
    Check if a dict key name is sensitive.
    Sources (in order):
      1. PersistentConfig registry (sensitive=True or auto-detected)
      2. Substring pattern matching (SENSITIVE_KEY_PATTERNS)
      3. Suffix matching (SENSITIVE_KEY_SUFFIXES)
    """
    key_lower = key.lower()
    # 1. Check PersistentConfig registry
    if key_lower in _get_registered_sensitive_names():
        return True
    # 2. Substring pattern
    if any(p in key_lower for p in SENSITIVE_KEY_PATTERNS):
        return True
    # 3. Suffix pattern
    return any(key_lower.endswith(s) for s in SENSITIVE_KEY_SUFFIXES)


def mask_config_dict(data: dict) -> dict:
    """
    Recursively walk a dict and mask values whose keys match sensitive patterns.
    Used for masking GET API responses before returning to frontend.
    """
    if not isinstance(data, dict):
        return data

    masked = {}
    for key, value in data.items():
        if _is_sensitive_key_name(key):
            if isinstance(value, str) and value:
                masked[key] = mask_sensitive_value(value)
            elif isinstance(value, list):
                masked[key] = [
                    mask_sensitive_value(v) if isinstance(v, str) and v else v
                    for v in value
                ]
            else:
                masked[key] = value
        elif isinstance(value, dict):
            masked[key] = mask_config_dict(value)
        elif isinstance(value, list):
            masked[key] = [
                mask_config_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            masked[key] = value
    return masked
