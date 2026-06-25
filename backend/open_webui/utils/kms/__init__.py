"""
KMS (Key Management Service) abstraction layer.

Pluggable provider backend for sensitive value encryption — supports both
self-managed (Fernet) and managed KMS (Azure Key Vault, AWS KMS, GCP KMS,
HashiCorp Vault / OpenBao) without changing call-site code.

See .claude/work/kms_design.md for the full design.

Public surface:
    get_router()  → singleton KMSRouter
    KMSProvider   → ABC for new providers
"""

from open_webui.utils.kms.base import (
    KMSProvider,
    TaggedValue,
    build_tag,
    parse_tag,
)
from open_webui.utils.kms.classification import (
    Classification,
    aad_hash,
    aad_serialize,
    build_aad_context,
    infer_classification,
)
from open_webui.utils.kms.router import KMSRouter, get_router

__all__ = [
    "Classification",
    "KMSProvider",
    "KMSRouter",
    "TaggedValue",
    "aad_hash",
    "aad_serialize",
    "build_aad_context",
    "build_tag",
    "get_router",
    "infer_classification",
    "parse_tag",
]
