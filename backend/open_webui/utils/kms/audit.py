"""
KMS audit shim — thin wrapper that providers + router call to record an
operation.

Lives in ``utils/kms/`` (not ``models/``) so the KMS layer doesn't grow a
hard dependency on ORM imports during bootstrap. The actual table append
runs through ``models.kms_audit_log.KmsAuditLogs``, imported lazily on
first call.

Why a shim?
  * Defensive — every audit write is wrapped in try/except so a broken
    audit DB never breaks the data path.
  * Best-effort metadata extraction from the AAD context dict (Phase 2)
    — providers don't have to know how the audit row is structured.
  * Single place to plug in future destinations (SIEM webhook, Splunk
    HEC, RFC 3161 anchoring) without touching every provider.

Phase 4.2 — see ``.claude/work/kms_design.md`` §11.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


# Lazily-resolved reference to ``KmsAuditLogs`` so importing this module
# during config.py / kms package bootstrap doesn't pull the ORM in early.
_logs = None


def _get_logs():
    """First-call import to break the kms ↔ models bootstrap cycle."""
    global _logs
    if _logs is None:
        try:
            from open_webui.models.kms_audit_log import KmsAuditLogs

            _logs = KmsAuditLogs
        except Exception as e:
            log.error("KMS audit shim: cannot import KmsAuditLogs (%s)", e)
            return None
    return _logs


def _extract_meta(context: Optional[dict]) -> dict:
    """Pull config_path/classification/tenant_id out of an AAD context dict
    (Phase 2 ``build_aad_context`` shape). Tolerates context=None / extra
    keys / missing keys — the audit row is best-effort, not authoritative."""
    if not isinstance(context, dict):
        return {}
    return {
        "config_path": context.get("config_path") or None,
        "classification": context.get("classification") or None,
        "org_id": context.get("tenant_id") or None,
    }


def record_op(
    *,
    operation: str,
    success: bool,
    context: Optional[dict] = None,
    kek_uri: Optional[str] = None,
    kek_version: Optional[str] = None,
    error_code: Optional[str] = None,
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    config_path: Optional[str] = None,
    classification: Optional[str] = None,
    org_id: Optional[str] = None,
) -> None:
    """Append a chained audit row. Errors are logged + swallowed.

    Explicit ``config_path`` / ``classification`` / ``org_id`` kwargs win
    over what's in ``context`` so callers without an AAD context (e.g.
    health_check, provider_change, migrate) can still tag the row.
    """
    logs = _get_logs()
    if logs is None:
        return

    meta = _extract_meta(context)
    try:
        logs.insert(
            operation=operation,
            success=success,
            actor_type=actor_type or "system",
            actor_id=actor_id,
            org_id=org_id or meta.get("org_id"),
            config_path=config_path or meta.get("config_path"),
            classification=classification or meta.get("classification"),
            kek_uri=kek_uri,
            kek_version=kek_version,
            error_code=error_code,
        )
    except Exception as e:
        # Never let audit failures bubble into the data path.
        log.error("KMS audit shim: record_op(%s) failed: %s", operation, e)


def parse_kek_version(key_id: str) -> Optional[str]:
    """Extract the version segment from a versioned Key Vault URI.

    Example:
        ``https://vault.vault.azure.net/keys/cloosphere-kek/abc123``
        → ``"abc123"``

    Returns None for unversioned/empty URIs — safe to pass directly to
    ``record_op(kek_version=...)``.
    """
    if not key_id:
        return None
    # Last URI segment is the version when the URI is versioned. Empty
    # for un-versioned KV URIs (no version pinned).
    tail = key_id.rstrip("/").rsplit("/", 1)[-1]
    return tail or None
