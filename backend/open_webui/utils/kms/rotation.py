"""
KMS automatic KEK rotation (Phase 4.5).

The scheduler invokes :func:`check_and_rotate` on a configurable interval
(default 24h). For each configured KEK (default tier + optional Restricted
tier), the check resolves the **latest** key version from Azure Key Vault
and compares it against the version currently embedded in the configured
URI:

  * **Same version** → no-op.
  * **Newer version** → kick the existing rotate flow
    (``_run_kms_migrate_all_scopes``) so every envelope is re-wrapped
    under the new KEK. The configured URI is updated to the new version
    and the router is reloaded across workers via Redis pub/sub
    (``KMS_CONFIG_KEYS`` invalidation hook in ``main.py``).

KEK *creation* is left to Azure Key Vault's own ``rotation_policy`` —
backend doesn't need ``keys/create`` RBAC, just the existing
``keys/wrap`` + ``keys/get`` from the Crypto User role. This keeps the
attack surface minimal and matches Azure's recommended automation pattern.

Dry-run mode (``KMS_ROTATION_DRY_RUN=True``) records the would-rotate
decision to ``kms_audit_log`` without touching configuration — useful
for the first activation period to build operator trust before letting
the scheduler write live.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


# --- Key Vault metadata ----------------------------------------------------


def _split_key_uri(key_uri: str) -> tuple[str, str, str]:
    """Return ``(vault_url, key_name, version)`` from a versioned KV URI.

    A versioned URI looks like::

        https://my-vault.vault.azure.net/keys/cloosphere-kek/abc123def

    A bare-name URI (``.../keys/<name>``) returns an empty version.
    """
    if not key_uri:
        raise ValueError("Empty KEK URI")
    parts = key_uri.rstrip("/").split("/")
    # ['https:', '', 'my-vault.vault.azure.net', 'keys', '<name>', '<version>?']
    if len(parts) < 5 or parts[3] != "keys":
        raise ValueError(f"Malformed KEK URI: {key_uri!r}")
    vault_url = "https://" + parts[2]
    key_name = parts[4]
    version = parts[5] if len(parts) >= 6 else ""
    return vault_url, key_name, version


def _resolve_latest_version(vault_url: str, key_name: str, credential) -> Optional[str]:
    """Hit ``GET {vault}/keys/{name}`` (no version) — KV returns the
    currently-enabled latest version. Returns the version string only,
    not the full URI."""
    from azure.keyvault.keys import KeyClient

    client = KeyClient(vault_url=vault_url, credential=credential)
    key = client.get_key(key_name)
    # KeyVaultKey.id ends with the version path component.
    full_id = getattr(key, "id", None) or getattr(
        getattr(key, "properties", None), "id", ""
    )
    if not full_id:
        return None
    return full_id.rstrip("/").rsplit("/", 1)[-1]


# --- Rotation flow ---------------------------------------------------------


def _build_credential():
    """Reuse the live `CryptoClientFactory` resolution chain so the same
    Service Principal authenticates the rotation check that the runtime
    encrypt/decrypt path uses."""
    from open_webui.utils.kms.azure_key_vault import CryptoClientFactory

    factory = CryptoClientFactory(key_id="<rotation-check>")
    return factory._resolve_credential()


def _check_one_kek(
    *,
    classification: str,
    current_uri: str,
    actor_id: Optional[str],
    dry_run: bool,
) -> dict:
    """Compare the latest KV version against the configured URI for a
    single tier (default or restricted). On mismatch + non-dry-run, kick
    the existing rotate flow.

    Returns a status dict suitable for inclusion in the scheduler's
    summary payload.
    """
    if not current_uri:
        return {"classification": classification, "status": "skipped:not-configured"}

    try:
        vault_url, key_name, current_version = _split_key_uri(current_uri)
    except ValueError as e:
        return {
            "classification": classification,
            "status": "error",
            "error": f"bad-uri: {e}",
        }

    try:
        credential = _build_credential()
        latest_version = _resolve_latest_version(vault_url, key_name, credential)
    except Exception as e:
        return {
            "classification": classification,
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
        }

    if not latest_version or latest_version == current_version:
        return {
            "classification": classification,
            "status": "up-to-date",
            "current_version": current_version,
        }

    new_uri = f"{vault_url}/keys/{key_name}/{latest_version}"

    if dry_run:
        # Audit-only: record the decision but don't touch config.
        from open_webui.utils.kms.audit import record_op

        record_op(
            operation="rotate",
            success=True,
            actor_type="scheduled",
            actor_id=actor_id,
            classification=classification,
            kek_uri=new_uri,
            kek_version=latest_version,
            config_path=(
                f"DRY_RUN|tier={classification}|from={current_uri}|to={new_uri}"
            ),
        )
        return {
            "classification": classification,
            "status": "would-rotate",
            "from_version": current_version,
            "to_version": latest_version,
            "to_uri": new_uri,
        }

    # Live rotation — perform the swap + full rewrap.
    return _perform_rotation(
        classification=classification,
        current_uri=current_uri,
        new_uri=new_uri,
        new_version=latest_version,
        actor_id=actor_id,
    )


def _perform_rotation(
    *,
    classification: str,
    current_uri: str,
    new_uri: str,
    new_version: str,
    actor_id: Optional[str],
) -> dict:
    """Swap the configured URI for the affected tier, reload the router,
    re-encrypt every envelope, and emit a ``rotate`` audit row.

    Side effects:
      * Updates the relevant ``KMS_AZURE_KEY_VAULT_KEY_URI`` /
        ``..._RESTRICTED`` PersistentConfig (which fires Redis pub/sub
        invalidation → other workers reload their KMSRouter).
      * Calls :func:`reload_router` on this worker.
      * Synchronously re-encrypts every protected scope.

    The router reload + URI update is intentionally completed *before*
    the rewrap loop so any concurrent encrypt() call on this worker
    starts emitting under the new KEK from the moment the swap lands.
    """
    from open_webui.config import (
        KMS_AZURE_KEY_VAULT_KEY_URI,
        KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED,
    )
    from open_webui.routers.configs import (
        _format_migrate_scope,
        _run_kms_migrate_all_scopes,
    )
    from open_webui.utils.kms.audit import record_op
    from open_webui.utils.kms.router import reload_router

    if classification == "restricted":
        cfg = KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED
    else:
        cfg = KMS_AZURE_KEY_VAULT_KEY_URI

    try:
        cfg.value = new_uri
        cfg.save()
    except Exception as e:
        record_op(
            operation="rotate",
            success=False,
            actor_type="scheduled",
            actor_id=actor_id,
            classification=classification,
            kek_uri=new_uri,
            error_code=f"config-save-failed:{type(e).__name__}",
            config_path=f"tier={classification}|from={current_uri}|to={new_uri}",
        )
        return {
            "classification": classification,
            "status": "error",
            "error": f"config save failed: {e}",
        }

    reload_router()

    try:
        counts = _run_kms_migrate_all_scopes()
    except Exception as e:
        # Router is on the new KEK; any unwrap of legacy ciphertext
        # falls through CryptoClientFactory.get_for(prior_uri). Audit
        # the failure and let the next scheduler tick retry.
        record_op(
            operation="rotate",
            success=False,
            actor_type="scheduled",
            actor_id=actor_id,
            classification=classification,
            kek_uri=new_uri,
            kek_version=new_version,
            error_code=f"rewrap-failed:{type(e).__name__}",
            config_path=f"tier={classification}|from={current_uri}|to={new_uri}",
        )
        return {
            "classification": classification,
            "status": "error",
            "error": f"rewrap failed: {e}",
        }

    record_op(
        operation="rotate",
        success=True,
        actor_type="scheduled",
        actor_id=actor_id,
        classification=classification,
        kek_uri=new_uri,
        kek_version=new_version,
        config_path=(
            f"tier={classification}|from={current_uri}|to={new_uri}|"
            + _format_migrate_scope(counts)
        ),
    )

    return {
        "classification": classification,
        "status": "rotated",
        "from_uri": current_uri,
        "to_uri": new_uri,
        "to_version": new_version,
        "counts": counts,
    }


def check_and_rotate(
    app, *, dry_run: Optional[bool] = None, actor_id: Optional[str] = None
) -> dict:
    """Top-level entry point used by the scheduler tick and the manual
    "Check Now" admin endpoint.

    :param app: FastAPI app — needed to read the current ``app.state.config``
        snapshot. The PersistentConfig values are also updated through
        ``cfg.value = new_uri`` so multi-worker invalidation fires.
    :param dry_run: When ``None``, falls back to ``KMS_ROTATION_DRY_RUN``.
        Manual triggers can override (e.g. admin "preview" button).
    :param actor_id: Audit row attribution. ``None`` for scheduled ticks
        (recorded as actor_type=``scheduled``); UUID for manual triggers.

    Returns a JSON-friendly dict that gets persisted to
    ``KMS_ROTATION_LAST_RESULT`` and rendered in the admin UI.
    """
    cfg = app.state.config
    if dry_run is None:
        dry_run = bool(getattr(cfg, "KMS_ROTATION_DRY_RUN", False))

    if (str(getattr(cfg, "KMS_PROVIDER", "fernet")) or "").lower() != "azkv-env":
        return {
            "ok": True,
            "checked_at": int(time.time()),
            "tiers": [],
            "skipped_reason": "provider!=azkv-env",
            "dry_run": dry_run,
        }

    tiers: list[dict] = []
    tiers.append(
        _check_one_kek(
            classification="confidential",
            current_uri=(getattr(cfg, "KMS_AZURE_KEY_VAULT_KEY_URI", "") or "").strip(),
            actor_id=actor_id,
            dry_run=dry_run,
        )
    )
    restricted_uri = (
        getattr(cfg, "KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED", "") or ""
    ).strip()
    if restricted_uri:
        tiers.append(
            _check_one_kek(
                classification="restricted",
                current_uri=restricted_uri,
                actor_id=actor_id,
                dry_run=dry_run,
            )
        )

    overall_ok = all(t.get("status") != "error" for t in tiers)
    summary = {
        "ok": overall_ok,
        "checked_at": int(time.time()),
        "dry_run": dry_run,
        "tiers": tiers,
    }

    # Persist the summary so the UI / next scheduler tick can read it.
    try:
        from open_webui.config import (
            KMS_ROTATION_LAST_CHECK_AT,
            KMS_ROTATION_LAST_RESULT,
        )

        KMS_ROTATION_LAST_CHECK_AT.value = summary["checked_at"]
        KMS_ROTATION_LAST_CHECK_AT.save()
        KMS_ROTATION_LAST_RESULT.value = json.dumps(summary, ensure_ascii=False)
        KMS_ROTATION_LAST_RESULT.save()
    except Exception as e:
        log.warning(f"Failed to persist rotation summary: {e}")

    return summary
