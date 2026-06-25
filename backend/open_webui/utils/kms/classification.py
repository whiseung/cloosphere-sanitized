"""
Data classification + AAD context for KMS Phase 2.

Classification drives three things:

  1. **Whether encryption is required** — `public` skips encryption entirely;
     everything else gets encrypted by the configured KMS provider.
  2. **Which DEK is used** (Phase 3+ envelope mode) — restricted/PII data
     gets a separate DEK (or a separate KEK in Phase 5) so PII can be
     crypto-shredded without affecting other secrets.
  3. **Which audit/UI policies apply** — restricted values trigger
     additional masking, audit detail, and access controls.

Phase 2 ships the metadata + AAD context plumbing. The Fernet provider
ignores the context (it has no AEAD support) — Phase 3 envelope providers
(AES-256-GCM via Azure KV / AWS KMS / GCP KMS) bind the AAD into the
ciphertext so cross-tenant copy-paste of an encrypted blob will fail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Classification(str, Enum):
    """Data classification levels (ordered by sensitivity, low → high)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

    @classmethod
    def from_value(cls, value: object) -> "Classification":
        """Permissive parser for config values that may be str or Classification."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.lower())
            except ValueError:
                pass
        raise ValueError(f"Unknown classification: {value!r}")


# --- name-based inference -------------------------------------------------
#
# Auto-inference by config path / key name. Used when a PersistentConfig
# entry sets sensitive=True without an explicit classification, or when
# scanning legacy config paths that predate Phase 2.
#
# Order matters within each tier — first match wins. Restricted patterns
# are checked first so a key like "user_ssn_token" is classified as
# restricted (PII) rather than confidential (token).

# Identifier-aware boundary — underscores/dots/digits act as separators so
# patterns like `ssn` match `user_ssn` and `auth.ssn.field` but not the
# substring inside an English word like `lessons`. (Python `\b` treats `_`
# as a word char, which would prevent matching inside snake_case identifiers.)
_BEFORE = r"(?<![A-Za-z])"
_AFTER = r"(?![A-Za-z])"

# Patterns indicating restricted/PII data — keep narrow to avoid
# over-classifying ordinary credentials.
_RESTRICTED_PII_PATTERNS = (
    re.compile(_BEFORE + r"ssn" + _AFTER, re.IGNORECASE),
    re.compile(r"national[_-]?id" + _AFTER, re.IGNORECASE),
    re.compile(r"tax[_-]?id" + _AFTER, re.IGNORECASE),
    re.compile(_BEFORE + r"rrn" + _AFTER, re.IGNORECASE),  # 주민등록번호
    re.compile(r"resident[_-]?reg", re.IGNORECASE),
    re.compile(r"passport[_-]?(no|number)", re.IGNORECASE),
    re.compile(r"biometric", re.IGNORECASE),
    re.compile(r"card[_-]?number", re.IGNORECASE),
    re.compile(_BEFORE + r"iban" + _AFTER, re.IGNORECASE),
    re.compile(r"account[_-]?number", re.IGNORECASE),
)

# Patterns indicating credentials/secrets (confidential).
_CONFIDENTIAL_PATTERNS = (
    re.compile(r"api[_-]?keys?", re.IGNORECASE),
    re.compile(r"access[_-]?key", re.IGNORECASE),
    re.compile(_BEFORE + r"secret" + _AFTER, re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(_BEFORE + r"token" + _AFTER, re.IGNORECASE),
    re.compile(r"credentials?", re.IGNORECASE),
    re.compile(r"subscription[_-]?key", re.IGNORECASE),
    re.compile(r"service[_-]?account[_-]?key", re.IGNORECASE),
    re.compile(r"client[_-]?secret", re.IGNORECASE),
    re.compile(r"webhook[_-]?url", re.IGNORECASE),
)


@dataclass(frozen=True)
class ClassificationInference:
    classification: Classification
    pii: bool


def infer_classification(name: str) -> ClassificationInference:
    """Infer classification + PII flag from a config path or env name.

    Returns CONFIDENTIAL/non-PII for sensitive-looking unknown names so the
    default behavior is "encrypt", matching the legacy auto-detect rule
    (`is_sensitive_path`) but adding a default classification.
    """
    if not name:
        return ClassificationInference(Classification.CONFIDENTIAL, pii=False)

    for pat in _RESTRICTED_PII_PATTERNS:
        if pat.search(name):
            return ClassificationInference(Classification.RESTRICTED, pii=True)

    for pat in _CONFIDENTIAL_PATTERNS:
        if pat.search(name):
            return ClassificationInference(Classification.CONFIDENTIAL, pii=False)

    return ClassificationInference(Classification.CONFIDENTIAL, pii=False)


# --- AAD context ----------------------------------------------------------


def build_aad_context(
    *,
    config_path: str,
    classification: Classification,
    tenant_id: Optional[str] = None,
    written_at: Optional[str] = None,
) -> dict:
    """Build an AAD (Additional Authenticated Data) dict for a sensitive value.

    Conventions:
      - tenant_id: organization id when the value is per-tenant; "" for
        system-wide config (e.g. Cloosphere admin settings shared across orgs).
      - written_at: caller-supplied write timestamp (ISO 8601). Phase 3
        envelope providers persist this alongside the ciphertext so
        decrypt() can rebuild the same AAD. Phase 2 / Fernet may pass None.

    Phase 3+ providers bind the serialized form into AES-GCM AAD so
    swapping a ciphertext between contexts (e.g. tenant A's value into
    tenant B's slot) fails the GCM tag check.
    """
    if not config_path:
        raise ValueError("config_path is required for AAD context")
    return {
        "tenant_id": tenant_id or "",
        "config_path": config_path,
        "classification": Classification.from_value(classification).value,
        "written_at": written_at or "",
    }


def aad_serialize(context: dict) -> bytes:
    """Canonical AAD bytes — sort_keys + compact separators for determinism.

    Two callers building "the same context" must produce byte-identical
    output, otherwise GCM tag verification fails on decrypt. Do NOT use
    json.dumps defaults (which insert whitespace).
    """
    return json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")


def aad_hash(context: dict) -> str:
    """SHA-256 hex digest of the canonical AAD bytes — for tag inclusion.

    Phase 3 envelope tags carry this hash so the router can sanity-check
    that the AAD reconstructed from runtime context matches what was
    written, before invoking the KMS unwrap path. (The real integrity
    check is the GCM tag inside the provider; the hash is a fast pre-check.)
    """
    return hashlib.sha256(aad_serialize(context)).hexdigest()
