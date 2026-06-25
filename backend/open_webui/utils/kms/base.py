"""
KMS provider ABC + tag format helpers.

Tag format (v1, Phase 1 — full envelope adds AAD/nonce/dek in Phase 2+):
    kms:<provider>:<algo>:<version>:<payload>

  provider  — 'fernet' | 'azkv-env' | 'azkv' | 'awskms' | 'gcpkms' | 'vault'
  algo      — 'aes256gcm' (mandatory once envelope is in)
              for fernet provider, fixed 'fernet'
  version   — tag schema version, currently 'v1'
  payload   — provider-specific opaque blob

Backward compatibility:
    Untagged 'gAAAAA...' values are treated as legacy fernet (no migration
    required — KMSRouter routes them to FernetProvider via fallback).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

TAG_SCHEME = "kms"
TAG_SEPARATOR = ":"
TAG_VERSION = "v1"

# Fernet untagged ciphertext prefix (legacy)
LEGACY_FERNET_PREFIX = "gAAAAA"


@dataclass(frozen=True)
class TaggedValue:
    """Parsed KMS tag.

    Round-trip: build_tag(parse_tag(s)...) == s
    """

    provider: str
    algo: str
    version: str
    payload: str

    @property
    def prefix(self) -> str:
        """The prefix portion that identifies the provider+algo+version."""
        return f"{TAG_SCHEME}{TAG_SEPARATOR}{self.provider}{TAG_SEPARATOR}{self.algo}{TAG_SEPARATOR}{self.version}{TAG_SEPARATOR}"


def build_tag(
    provider: str, algo: str, payload: str, version: str = TAG_VERSION
) -> str:
    """Build a tagged ciphertext.

    Payload may contain ':' — only the first 4 segments are structural.
    """
    if not provider or not algo or not version:
        raise ValueError("provider, algo, version are required")
    return f"{TAG_SCHEME}{TAG_SEPARATOR}{provider}{TAG_SEPARATOR}{algo}{TAG_SEPARATOR}{version}{TAG_SEPARATOR}{payload}"


def parse_tag(value: str) -> Optional[TaggedValue]:
    """Parse a tagged ciphertext.

    Returns None for non-tagged values (plaintext or legacy untagged Fernet).
    The caller should fall back to legacy detection (LEGACY_FERNET_PREFIX).
    """
    if not isinstance(value, str) or not value.startswith(
        f"{TAG_SCHEME}{TAG_SEPARATOR}"
    ):
        return None
    # Split at most 4 times; payload may itself contain colons
    parts = value.split(TAG_SEPARATOR, 4)
    if len(parts) != 5:
        return None
    _scheme, provider, algo, version, payload = parts
    if not provider or not algo or not version:
        return None
    return TaggedValue(provider=provider, algo=algo, version=version, payload=payload)


def is_tagged(value: str) -> bool:
    """Cheap check: does this value carry a kms: tag prefix?"""
    return isinstance(value, str) and value.startswith(f"{TAG_SCHEME}{TAG_SEPARATOR}")


def is_legacy_fernet(value: str) -> bool:
    """Cheap check: untagged Fernet ciphertext (gAAAAA prefix)."""
    return isinstance(value, str) and value.startswith(LEGACY_FERNET_PREFIX)


class KMSProvider(ABC):
    """Pluggable KMS backend.

    Each provider claims a (provider_name, algo) pair. The router dispatches
    by inspecting the tag prefix on decrypt.

    Phase 1 contract — encrypt/decrypt only.
    Phase 2+ adds: rotate(), health_check(), envelope-mode (DEK + AAD).
    """

    #: Stable provider identifier embedded in the tag (e.g. 'fernet', 'azkv-env').
    name: str = ""

    #: Algorithm identifier embedded in the tag (e.g. 'fernet', 'aes256gcm').
    algo: str = ""

    #: Tag schema version this provider produces and decrypts. Phase 1 = 'v1'.
    #: A future multi-version provider should override decrypt() to accept
    #: older tag versions while still emitting the current version on encrypt.
    version: str = TAG_VERSION

    @property
    def tag_prefix(self) -> str:
        """Fast-path prefix for KMSRouter dispatch — values starting with this
        prefix are decrypted by this provider. Must equal TaggedValue.prefix
        for any value this provider emits."""
        return f"{TAG_SCHEME}{TAG_SEPARATOR}{self.name}{TAG_SEPARATOR}{self.algo}{TAG_SEPARATOR}{self.version}{TAG_SEPARATOR}"

    @abstractmethod
    def encrypt(self, plaintext: str, context: Optional[dict] = None) -> str:
        """Encrypt and return a tagged ciphertext.

        `context` is reserved for AAD binding (Phase 2). Phase 1 providers may
        accept and ignore it; future providers MUST bind it into AAD.
        """

    @abstractmethod
    def decrypt(self, tagged_or_legacy: str, context: Optional[dict] = None) -> str:
        """Decrypt a tagged ciphertext (or legacy untagged for Fernet only).

        Raises ValueError on failure. Empty input returns "".
        """

    # --- Phase 2+ ---------------------------------------------------------

    def rotate(self, tagged: str, context: Optional[dict] = None) -> str:
        """Re-encrypt with the current KEK version. Default: decrypt+encrypt."""
        plaintext = self.decrypt(tagged, context)
        return self.encrypt(plaintext, context)

    def health_check(self) -> tuple[bool, str]:
        """Connectivity probe for the admin UI. Returns (ok, detail)."""
        return True, f"{self.name} provider available"
