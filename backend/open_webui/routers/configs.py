import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from open_webui.config import (
    OAUTH_PROVIDERS,
    BannerModel,
    ConfigVersionConflict,
    get_config,
    get_config_version,
    save_config,
)
from open_webui.storage.provider import ImageStorage, Storage, get_storage_provider
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import (
    get_admin_monitoring_read_access,
    get_admin_monitoring_write_access,
    get_admin_settings_read_access,
    get_admin_settings_write_access,
    get_verified_user,
)
from open_webui.utils.crypto import (
    mask_config_dict,
    resolve_sensitive_value,
)
from open_webui.utils.license import require_feature
from open_webui.utils.monitoring import generate_monitoring_bundle
from open_webui.utils.tools import get_tool_server_data, get_tool_servers_data
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

router = APIRouter()


############################
# ImportConfig
############################


class ImportConfigForm(BaseModel):
    config: dict
    expected_version: Optional[int] = None


@router.post("/import", response_model=dict)
async def import_config(
    form_data: ImportConfigForm, user=Depends(get_admin_settings_write_access)
):
    try:
        success = save_config(
            form_data.config, expected_version=form_data.expected_version
        )
    except ConfigVersionConflict as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "CONFIG_VERSION_CONFLICT",
                "message": "Configuration was modified by another user. Please reload and try again.",
                "current_version": e.current_version,
                "expected_version": e.expected_version,
            },
        )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to save config to database.",
        )
    AuditLogger.log_settings_change("config/import", after_data=form_data.config)
    return mask_config_dict(get_config())


############################
# ExportConfig
############################


@router.get("/export", response_model=dict)
async def export_config(user=Depends(get_admin_settings_read_access)):
    return mask_config_dict(get_config())


############################
# Config Version (for optimistic locking)
############################


@router.get("/version")
async def get_version(user=Depends(get_admin_settings_read_access)):
    return {"version": get_config_version()}


############################
# Direct Connections Config
############################


class DirectConnectionsConfigForm(BaseModel):
    ENABLE_DIRECT_CONNECTIONS: bool


@router.get("/direct_connections", response_model=DirectConnectionsConfigForm)
async def get_direct_connections_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return {
        "ENABLE_DIRECT_CONNECTIONS": request.app.state.config.ENABLE_DIRECT_CONNECTIONS,
    }


@router.post("/direct_connections", response_model=DirectConnectionsConfigForm)
async def set_direct_connections_config(
    request: Request,
    form_data: DirectConnectionsConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.ENABLE_DIRECT_CONNECTIONS = (
        form_data.ENABLE_DIRECT_CONNECTIONS
    )
    AuditLogger.log_settings_change(
        "connections/direct", after_data=form_data.model_dump()
    )
    return {
        "ENABLE_DIRECT_CONNECTIONS": request.app.state.config.ENABLE_DIRECT_CONNECTIONS,
    }


############################
# Google Workspace Integration Config (Gmail / Calendar 채팅 통합)
############################


class GoogleIntegrationConfigForm(BaseModel):
    """Gmail / Calendar / Drive 채팅 통합 admin 토글.

    POST 는 모든 필드 Optional — 클라이언트가 일부만 갱신해도 나머지는
    기존 값 유지.  GET 응답은 항상 세 필드 채워서 반환.
    GOOGLE_OAUTH_CONFIGURED 는 read-only (POST 입력 무시) — Google OAuth
    자격증명(GOOGLE_CLIENT_ID/SECRET) 미설정 시 admin UI 가 섹션을 숨긴다.
    """

    ENABLE_GMAIL_INTEGRATION: Optional[bool] = None
    ENABLE_CALENDAR_INTEGRATION: Optional[bool] = None
    ENABLE_DRIVE_INTEGRATION: Optional[bool] = None
    GOOGLE_OAUTH_CONFIGURED: Optional[bool] = None


@router.get("/google_integration", response_model=GoogleIntegrationConfigForm)
async def get_google_integration_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return {
        "ENABLE_GMAIL_INTEGRATION": request.app.state.config.ENABLE_GMAIL_INTEGRATION,
        "ENABLE_CALENDAR_INTEGRATION": request.app.state.config.ENABLE_CALENDAR_INTEGRATION,
        "ENABLE_DRIVE_INTEGRATION": request.app.state.config.ENABLE_DRIVE_INTEGRATION,
        "GOOGLE_OAUTH_CONFIGURED": "google" in OAUTH_PROVIDERS,
    }


@router.post("/google_integration", response_model=GoogleIntegrationConfigForm)
async def set_google_integration_config(
    request: Request,
    form_data: GoogleIntegrationConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    if form_data.ENABLE_GMAIL_INTEGRATION is not None:
        request.app.state.config.ENABLE_GMAIL_INTEGRATION = (
            form_data.ENABLE_GMAIL_INTEGRATION
        )
    if form_data.ENABLE_CALENDAR_INTEGRATION is not None:
        request.app.state.config.ENABLE_CALENDAR_INTEGRATION = (
            form_data.ENABLE_CALENDAR_INTEGRATION
        )
    if form_data.ENABLE_DRIVE_INTEGRATION is not None:
        request.app.state.config.ENABLE_DRIVE_INTEGRATION = (
            form_data.ENABLE_DRIVE_INTEGRATION
        )
    AuditLogger.log_settings_change(
        "connections/google_integration",
        after_data={
            "ENABLE_GMAIL_INTEGRATION": request.app.state.config.ENABLE_GMAIL_INTEGRATION,
            "ENABLE_CALENDAR_INTEGRATION": request.app.state.config.ENABLE_CALENDAR_INTEGRATION,
            "ENABLE_DRIVE_INTEGRATION": request.app.state.config.ENABLE_DRIVE_INTEGRATION,
        },
    )
    return {
        "ENABLE_GMAIL_INTEGRATION": request.app.state.config.ENABLE_GMAIL_INTEGRATION,
        "ENABLE_CALENDAR_INTEGRATION": request.app.state.config.ENABLE_CALENDAR_INTEGRATION,
        "ENABLE_DRIVE_INTEGRATION": request.app.state.config.ENABLE_DRIVE_INTEGRATION,
        "GOOGLE_OAUTH_CONFIGURED": "google" in OAUTH_PROVIDERS,
    }


############################
# Google Cloud Config
############################


class GoogleCloudConfigForm(BaseModel):
    GOOGLE_CLOUD_ENABLED: bool = False
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY: str = ""


def _is_gcp_enabled(request: Request) -> bool:
    # Backward compat: pre-existing configs only have the key — treat them as enabled.
    return bool(
        getattr(request.app.state.config, "GOOGLE_CLOUD_ENABLED", False)
        or request.app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY
    )


@router.get("/google_cloud", response_model=GoogleCloudConfigForm)
async def get_google_cloud_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return mask_config_dict(
        {
            "GOOGLE_CLOUD_ENABLED": _is_gcp_enabled(request),
            "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY": request.app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
        }
    )


@router.post("/google_cloud", response_model=GoogleCloudConfigForm)
async def set_google_cloud_config(
    request: Request,
    form_data: GoogleCloudConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY = resolve_sensitive_value(
        form_data.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
        request.app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
    )
    request.app.state.config.GOOGLE_CLOUD_ENABLED = form_data.GOOGLE_CLOUD_ENABLED
    AuditLogger.log_settings_change(
        "connections/google_cloud",
        after_data={
            "enabled": form_data.GOOGLE_CLOUD_ENABLED,
            "configured": bool(form_data.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY),
        },
    )
    return mask_config_dict(
        {
            "GOOGLE_CLOUD_ENABLED": _is_gcp_enabled(request),
            "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY": request.app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY,
        }
    )


############################
# KMS / Key Management
############################


class KMSConfigForm(BaseModel):
    KMS_PROVIDER: str  # 'fernet' | 'azkv-env'
    KMS_AZURE_KEY_VAULT_KEY_URI: Optional[str] = ""
    # Phase 4.4 — optional Restricted-tier KEK (PII / financial).
    # Empty → all classifications share the default KEK.
    KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED: Optional[str] = ""
    KMS_AZURE_TENANT_ID: Optional[str] = ""
    KMS_AZURE_CLIENT_ID: Optional[str] = ""
    KMS_AZURE_CLIENT_SECRET: Optional[str] = ""


def _kms_config_payload(request: Request) -> dict:
    return {
        "KMS_PROVIDER": request.app.state.config.KMS_PROVIDER,
        "KMS_AZURE_KEY_VAULT_KEY_URI": request.app.state.config.KMS_AZURE_KEY_VAULT_KEY_URI,
        "KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED": (
            request.app.state.config.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED
        ),
        "KMS_AZURE_TENANT_ID": request.app.state.config.KMS_AZURE_TENANT_ID,
        "KMS_AZURE_CLIENT_ID": request.app.state.config.KMS_AZURE_CLIENT_ID,
        "KMS_AZURE_CLIENT_SECRET": request.app.state.config.KMS_AZURE_CLIENT_SECRET,
    }


@router.get(
    "/kms",
    response_model=KMSConfigForm,
    dependencies=[Depends(require_feature("encryption"))],
)
async def get_kms_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return mask_config_dict(_kms_config_payload(request))


@router.post(
    "/kms",
    response_model=KMSConfigForm,
    dependencies=[Depends(require_feature("encryption"))],
)
async def set_kms_config(
    request: Request,
    form_data: KMSConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    cfg = request.app.state.config
    cfg.KMS_PROVIDER = (form_data.KMS_PROVIDER or "fernet").strip().lower()
    cfg.KMS_AZURE_KEY_VAULT_KEY_URI = (
        form_data.KMS_AZURE_KEY_VAULT_KEY_URI or ""
    ).strip()
    cfg.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED = (
        form_data.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED or ""
    ).strip()
    cfg.KMS_AZURE_TENANT_ID = (form_data.KMS_AZURE_TENANT_ID or "").strip()
    cfg.KMS_AZURE_CLIENT_ID = (form_data.KMS_AZURE_CLIENT_ID or "").strip()
    # Secret: preserve existing if the form contains the masked placeholder.
    cfg.KMS_AZURE_CLIENT_SECRET = resolve_sensitive_value(
        form_data.KMS_AZURE_CLIENT_SECRET or "",
        cfg.KMS_AZURE_CLIENT_SECRET,
    )

    # Drop the router singleton so the next encrypt/decrypt rebuilds with
    # the new provider — avoids a process restart for the change to land.
    from open_webui.utils.kms.audit import record_op
    from open_webui.utils.kms.router import reload_router

    reload_router()

    AuditLogger.log_settings_change(
        "configs/kms",
        after_data={
            "KMS_PROVIDER": cfg.KMS_PROVIDER,
            "KMS_AZURE_KEY_VAULT_KEY_URI_set": bool(cfg.KMS_AZURE_KEY_VAULT_KEY_URI),
            "KMS_AZURE_TENANT_ID_set": bool(cfg.KMS_AZURE_TENANT_ID),
            "KMS_AZURE_CLIENT_ID_set": bool(cfg.KMS_AZURE_CLIENT_ID),
            "KMS_AZURE_CLIENT_SECRET_set": bool(cfg.KMS_AZURE_CLIENT_SECRET),
        },
    )
    record_op(
        operation="provider_change",
        success=True,
        actor_type="user",
        actor_id=user.id,
        kek_uri=cfg.KMS_AZURE_KEY_VAULT_KEY_URI or None,
        config_path=f"kms.provider={cfg.KMS_PROVIDER}",
    )
    return mask_config_dict(_kms_config_payload(request))


@router.post(
    "/kms/test",
    dependencies=[Depends(require_feature("encryption"))],
)
async def test_kms_connection(
    request: Request,
    form_data: KMSConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    """Probe the KMS configuration WITHOUT saving — admin can validate
    settings before committing them. Builds a temporary provider, runs
    health_check, returns result. The masked secret placeholder is
    resolved against the saved value so the admin doesn't have to
    re-enter the secret each time."""
    provider_name = (form_data.KMS_PROVIDER or "fernet").strip().lower()
    if provider_name in ("", "fernet"):
        return {"ok": True, "detail": "fernet provider available"}

    if provider_name != "azkv-env":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported KMS provider for test: {provider_name}",
        )

    key_uri = (form_data.KMS_AZURE_KEY_VAULT_KEY_URI or "").strip()
    if not key_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="KMS_AZURE_KEY_VAULT_KEY_URI is required for azkv-env",
        )

    # Resolve masked secret against current saved value (admin may submit
    # the form without re-typing the secret).
    cfg = request.app.state.config
    tenant = (form_data.KMS_AZURE_TENANT_ID or "").strip()
    client_id = (form_data.KMS_AZURE_CLIENT_ID or "").strip()
    client_secret = resolve_sensitive_value(
        form_data.KMS_AZURE_CLIENT_SECRET or "",
        cfg.KMS_AZURE_CLIENT_SECRET,
    )

    try:
        from azure.identity import ClientSecretCredential, DefaultAzureCredential
        from open_webui.utils.kms.azure_key_vault import (
            AzureKeyVaultEnvelopeProvider,
            CryptoClientFactory,
        )

        if tenant and client_id and client_secret:
            credential = ClientSecretCredential(
                tenant_id=tenant, client_id=client_id, client_secret=client_secret
            )
        else:
            # Fall back to the live resolution chain (MICROSOFT_CLIENT_* /
            # DefaultAzureCredential) — same path the runtime would take.
            credential = DefaultAzureCredential()

        factory = CryptoClientFactory(key_id=key_uri, credential=credential)

        # Phase 4.4 — when a Restricted KEK URI is supplied, probe both
        # tiers in one call so the admin gets a combined OK/FAIL.
        restricted_uri = (
            form_data.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED or ""
        ).strip() or None
        restricted_factory = (
            CryptoClientFactory(key_id=restricted_uri, credential=credential)
            if restricted_uri
            else None
        )

        candidate = AzureKeyVaultEnvelopeProvider(
            key_id=key_uri,
            crypto_client_factory=factory,
            restricted_key_id=restricted_uri,
            restricted_crypto_client_factory=restricted_factory,
        )
        ok, detail = candidate.health_check()
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    return {"ok": ok, "detail": detail}


############################
# KMS Migration (legacy → current provider)
############################


@router.post(
    "/kms/migrate",
    dependencies=[Depends(require_feature("encryption"))],
)
async def migrate_kms(request: Request, user=Depends(get_admin_settings_write_access)):
    """Re-encrypt every KMS-protected value under the **currently
    configured provider**.

    Effect: legacy ``gAAAAA...`` Fernet ciphertexts and any plaintext
    rows that predate column-level encryption become fresh tags under
    the active provider (e.g. ``kms:azkv-env:aes256gcm:v1:...``).
    Existing already-current ciphertexts are unchanged — the operation
    is **idempotent** and safe to re-run.

    Scope (matches Phase 3.5):
      - ``Config.data`` JSON sensitive paths (PersistentConfig registry)
      - DbSphere connection passwords / tokens / secrets
      - Tool connection ``data.connection.key``
      - Cloocus admin license / feature / registry tokens

    Returns counts per scope: how many rows were touched (re-encrypted)
    vs skipped (already current or empty) vs failed.
    """
    counts = _run_kms_migrate_all_scopes()

    AuditLogger.log_settings_change("configs/kms/migrate", after_data=counts)

    from open_webui.utils.kms.audit import record_op

    cfg = request.app.state.config
    record_op(
        operation="migrate",
        success=True,
        actor_type="user",
        actor_id=user.id,
        kek_uri=cfg.KMS_AZURE_KEY_VAULT_KEY_URI or None,
        config_path=_format_migrate_scope(counts),
    )

    return {
        "ok": True,
        "counts": counts,
    }


def _run_kms_migrate_all_scopes() -> dict[str, dict[str, int]]:
    """Re-encrypt every KMS-protected scope under the active provider.

    Shared between the explicit ``/configs/kms/migrate`` endpoint and
    the rotation flow (``/configs/kms/rotate``). Idempotent — running
    this twice in a row yields the same per-scope counts on the second
    run with ``touched`` becoming ``0`` for already-current envelopes.

    Cloocus admin license/feature/registry tokens are intentionally
    excluded — they are JWT-signed artefacts whose authenticity is
    enforced by signature, and encrypting them in the central admin DB
    would block operational support (re-issue / re-display / audit)
    without adding real security.
    """
    return {
        "config": _migrate_config_secrets(),
        "dbsphere": _migrate_dbsphere_connections(),
        "tool_connections": _migrate_tool_connections(),
        "user_api_keys": _migrate_user_api_keys(),
    }


def _format_migrate_scope(counts: dict[str, dict[str, int]]) -> str:
    """Compact scope summary for the audit row's config_path field."""
    parts = []
    for scope, c in counts.items():
        parts.append(f"{scope}({c.get('touched', 0)})")
    return "scope=" + ",".join(parts)


############################
# KMS Rotation (Phase 4.3)
############################


class KMSRotateForm(BaseModel):
    new_key_uri: str
    # Optional: rotate using a different SP. Empty strings preserve the
    # currently saved values (handy when admin doesn't want to re-type the
    # secret). Tenant/client/secret are kept independent so a single-tenant
    # deployment can leave them blank.
    new_tenant_id: Optional[str] = ""
    new_client_id: Optional[str] = ""
    new_client_secret: Optional[str] = ""


@router.post(
    "/kms/rotate",
    dependencies=[Depends(require_feature("encryption"))],
)
async def rotate_kms(
    request: Request,
    form_data: KMSRotateForm,
    user=Depends(get_admin_settings_write_access),
):
    """Rotate the KEK and re-encrypt every envelope under the new key.

    Procedure:
      1. Validate the new KEK URI is non-empty and different from current.
      2. Health-check the new KEK (wrap a throwaway DEK).
      3. Switch the configured KEK URI and rebuild the router.
      4. Run the full migrate flow — every existing envelope ciphertext
         is decrypted via the prior KEK (still resolvable via the
         per-key_id CryptographyClient cache the provider keeps) and
         re-encrypted under the new KEK.
      5. Audit the rotation with the from→to KEK URIs.

    Failure modes:
      * Health check fails (network / auth / RBAC) → no config change,
        clear error returned.
      * Migrate fails partway → router stays on the new KEK, but some
        rows may still be on the old KEK. Re-running the rotate (or
        plain migrate) endpoint completes the migration. The unwrap
        path tolerates mixed state because each tag carries its own
        kek_uri.
    """
    cfg = request.app.state.config

    new_key_uri = (form_data.new_key_uri or "").strip()
    if not new_key_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new_key_uri is required",
        )

    current_key_uri = (cfg.KMS_AZURE_KEY_VAULT_KEY_URI or "").strip()
    if new_key_uri == current_key_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new_key_uri must differ from the current KEK",
        )

    # Resolve credential for the new KEK — explicit form values win,
    # blanks fall back to the current saved triple, then to the global
    # resolution chain (MICROSOFT_CLIENT_* / DefaultAzureCredential).
    new_tenant = (form_data.new_tenant_id or "").strip() or (
        cfg.KMS_AZURE_TENANT_ID or ""
    ).strip()
    new_client = (form_data.new_client_id or "").strip() or (
        cfg.KMS_AZURE_CLIENT_ID or ""
    ).strip()
    new_secret = resolve_sensitive_value(
        form_data.new_client_secret or "",
        cfg.KMS_AZURE_CLIENT_SECRET or "",
    )

    # Step 1: Health check the new KEK before we touch any config.
    try:
        from azure.identity import ClientSecretCredential, DefaultAzureCredential
        from open_webui.utils.kms.azure_key_vault import (
            AzureKeyVaultEnvelopeProvider,
            CryptoClientFactory,
        )

        if new_tenant and new_client and new_secret:
            credential = ClientSecretCredential(
                tenant_id=new_tenant,
                client_id=new_client,
                client_secret=new_secret,
            )
        else:
            credential = DefaultAzureCredential()

        probe_factory = CryptoClientFactory(key_id=new_key_uri, credential=credential)
        probe_provider = AzureKeyVaultEnvelopeProvider(
            key_id=new_key_uri, crypto_client_factory=probe_factory
        )
        ok, detail = probe_provider.health_check()
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"New KEK health check failed: {detail}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New KEK probe error: {type(e).__name__}: {e}",
        ) from None

    # Step 2: Persist the new KEK URI and reload the router so the next
    # encrypt() call writes under the new key.
    cfg.KMS_AZURE_KEY_VAULT_KEY_URI = new_key_uri
    if new_tenant:
        cfg.KMS_AZURE_TENANT_ID = new_tenant
    if new_client:
        cfg.KMS_AZURE_CLIENT_ID = new_client
    if new_secret:
        cfg.KMS_AZURE_CLIENT_SECRET = new_secret

    from open_webui.utils.kms.audit import record_op
    from open_webui.utils.kms.router import reload_router

    reload_router()

    # Step 3: Re-encrypt every protected scope. Each provider's
    # per-key_id CryptographyClient cache lets unwrap of legacy
    # ciphertexts (still tagged with the old KEK URI) succeed.
    counts = _run_kms_migrate_all_scopes()

    AuditLogger.log_settings_change(
        "configs/kms/rotate",
        after_data={
            "from_kek": current_key_uri or None,
            "to_kek": new_key_uri,
            "counts": counts,
        },
    )

    record_op(
        operation="rotate",
        success=True,
        actor_type="user",
        actor_id=user.id,
        kek_uri=new_key_uri,
        config_path=(
            f"from={current_key_uri or '(none)'}|to={new_key_uri}|"
            + _format_migrate_scope(counts)
        ),
    )

    return {
        "ok": True,
        "from_kek": current_key_uri or None,
        "to_kek": new_key_uri,
        "counts": counts,
    }


############################
# KMS Auto-Rotation (Phase 4.5)
############################


class KMSRotationConfigForm(BaseModel):
    KMS_ROTATION_AUTO_ENABLED: bool
    KMS_ROTATION_CHECK_INTERVAL_HOURS: int
    KMS_ROTATION_DRY_RUN: bool


def _kms_rotation_payload(request: Request) -> dict:
    """Pull the current rotation config + last-check telemetry."""
    cfg = request.app.state.config
    last_result_raw = getattr(cfg, "KMS_ROTATION_LAST_RESULT", "") or ""
    last_result = None
    if last_result_raw:
        try:
            import json as _json

            last_result = _json.loads(last_result_raw)
        except Exception:
            last_result = None
    return {
        "KMS_ROTATION_AUTO_ENABLED": bool(
            getattr(cfg, "KMS_ROTATION_AUTO_ENABLED", False)
        ),
        "KMS_ROTATION_CHECK_INTERVAL_HOURS": int(
            getattr(cfg, "KMS_ROTATION_CHECK_INTERVAL_HOURS", 24)
        ),
        "KMS_ROTATION_DRY_RUN": bool(getattr(cfg, "KMS_ROTATION_DRY_RUN", False)),
        "last_check_at": int(getattr(cfg, "KMS_ROTATION_LAST_CHECK_AT", 0)),
        "last_result": last_result,
    }


@router.get(
    "/kms/rotation",
    dependencies=[Depends(require_feature("encryption"))],
)
async def get_kms_rotation_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return _kms_rotation_payload(request)


@router.post(
    "/kms/rotation",
    dependencies=[Depends(require_feature("encryption"))],
)
async def set_kms_rotation_config(
    request: Request,
    form_data: KMSRotationConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    cfg = request.app.state.config
    cfg.KMS_ROTATION_AUTO_ENABLED = bool(form_data.KMS_ROTATION_AUTO_ENABLED)
    cfg.KMS_ROTATION_CHECK_INTERVAL_HOURS = max(
        int(form_data.KMS_ROTATION_CHECK_INTERVAL_HOURS), 1
    )
    cfg.KMS_ROTATION_DRY_RUN = bool(form_data.KMS_ROTATION_DRY_RUN)

    AuditLogger.log_settings_change(
        "configs/kms/rotation",
        after_data={
            "enabled": cfg.KMS_ROTATION_AUTO_ENABLED,
            "interval_hours": cfg.KMS_ROTATION_CHECK_INTERVAL_HOURS,
            "dry_run": cfg.KMS_ROTATION_DRY_RUN,
        },
    )
    return _kms_rotation_payload(request)


@router.post(
    "/kms/rotation/check",
    dependencies=[Depends(require_feature("encryption"))],
)
async def trigger_kms_rotation_check(
    request: Request,
    dry_run: Optional[bool] = None,
    user=Depends(get_admin_settings_write_access),
):
    """Run the rotation check immediately. ``dry_run=true`` lets the admin
    preview what would happen without touching live config — useful for
    the first activation period.

    Distinct from the scheduler-driven check: a manual trigger ignores the
    interval and attributes the audit row to ``user.id`` (actor_type=user)
    rather than ``actor_type=scheduled``."""
    from open_webui.utils.kms.rotation import check_and_rotate

    return check_and_rotate(request.app, dry_run=dry_run, actor_id=user.id)


############################
# KMS Audit Log (Phase 4.2)
############################


class KMSAuditQuery(BaseModel):
    page: int = 1
    limit: int = 50
    operation: Optional[str] = None  # comma-separated list accepted
    success: Optional[bool] = None
    actor_id: Optional[str] = None
    org_id: Optional[str] = None
    config_path: Optional[str] = None
    from_ts_ms: Optional[int] = None
    to_ts_ms: Optional[int] = None


@router.get(
    "/kms/audit",
    dependencies=[Depends(require_feature("encryption"))],
)
async def list_kms_audit(
    request: Request,
    page: int = 1,
    limit: int = 50,
    operation: Optional[str] = None,
    success: Optional[bool] = None,
    actor_id: Optional[str] = None,
    org_id: Optional[str] = None,
    config_path: Optional[str] = None,
    from_ts_ms: Optional[int] = None,
    to_ts_ms: Optional[int] = None,
    user=Depends(get_admin_monitoring_read_access),
):
    """Paginated KMS audit log query — admin only.

    Filtering: ``operation`` accepts a comma-separated list (e.g.
    ``wrap,unwrap``). ``success`` is exact-match. Date range uses
    epoch-millisecond ints (matches the table's ``timestamp_ms`` column)."""
    from open_webui.models.kms_audit_log import KmsAuditLogs

    rows, total = KmsAuditLogs.list(
        page=max(page, 1),
        limit=min(max(limit, 1), 500),
        operation=operation,
        success=success,
        actor_id=actor_id,
        org_id=org_id,
        config_path=config_path,
        from_ts_ms=from_ts_ms,
        to_ts_ms=to_ts_ms,
    )
    return {
        "rows": [r.model_dump() for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get(
    "/kms/audit/verify",
    dependencies=[Depends(require_feature("encryption"))],
)
async def verify_kms_audit(
    request: Request,
    from_id: Optional[int] = None,
    to_id: Optional[int] = None,
    user=Depends(get_admin_monitoring_read_access),
):
    """Walk the audit chain and recompute every row_hash. Returns the
    first break (if any) or confirms full integrity.

    Sub-range verification: pass ``from_id`` / ``to_id`` to limit the
    walk — we anchor on the row immediately before ``from_id`` (or
    GENESIS if from_id<=1) so partial verifies still detect tampering."""
    from open_webui.models.kms_audit_log import KmsAuditLogs

    return KmsAuditLogs.verify_chain(from_id=from_id, to_id=to_id)


@router.get(
    "/kms/audit/export.csv",
    dependencies=[Depends(require_feature("encryption"))],
)
async def export_kms_audit_csv(
    request: Request,
    operation: Optional[str] = None,
    success: Optional[bool] = None,
    actor_id: Optional[str] = None,
    org_id: Optional[str] = None,
    config_path: Optional[str] = None,
    from_ts_ms: Optional[int] = None,
    to_ts_ms: Optional[int] = None,
    reason: Optional[str] = None,
    user=Depends(get_admin_monitoring_write_access),
):
    """CSV export of the audit log. Export itself is logged as
    ``audit_export`` so the chain captures who pulled the audit data
    and why (the ``reason`` query param, surfaced in the admin UI)."""
    import csv
    import io

    from open_webui.models.kms_audit_log import KmsAuditLogs

    # Page through the table to keep memory bounded — 500 rows per page
    # is comfortable for CSV and keeps the per-query overhead small.
    rows: list = []
    page = 1
    page_size = 500
    while True:
        batch, _total = KmsAuditLogs.list(
            page=page,
            limit=page_size,
            operation=operation,
            success=success,
            actor_id=actor_id,
            org_id=org_id,
            config_path=config_path,
            from_ts_ms=from_ts_ms,
            to_ts_ms=to_ts_ms,
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
        if len(rows) > 100_000:
            # Hard cap — anything beyond this should be a SIEM sync, not a CSV.
            break

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "timestamp_ms",
            "actor_type",
            "actor_id",
            "org_id",
            "operation",
            "config_path",
            "kek_uri",
            "kek_version",
            "classification",
            "success",
            "error_code",
            "request_id",
            "client_ip",
            "prev_hash",
            "row_hash",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.timestamp_ms,
                r.actor_type,
                r.actor_id or "",
                r.org_id or "",
                r.operation,
                r.config_path or "",
                r.kek_uri or "",
                r.kek_version or "",
                r.classification or "",
                "true" if r.success else "false",
                r.error_code or "",
                r.request_id or "",
                r.client_ip or "",
                r.prev_hash,
                r.row_hash,
            ]
        )

    # Audit the export itself — the reason is part of the row so reviewers
    # can later see "why was this exported".
    from open_webui.utils.kms.audit import record_op

    record_op(
        operation="audit_export",
        success=True,
        actor_type="user",
        actor_id=user.id,
        config_path=f"reason={reason or '(none)'}|rows={len(rows)}",
    )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=kms-audit-log.csv",
        },
    )


def _migrate_config_secrets() -> dict:
    """Walk PERSISTENT_CONFIG_REGISTRY sensitive paths and force re-encrypt.

    Reads CONFIG_DATA via get_config (which decrypts via the router —
    legacy Fernet survives via fallback), then save_to_db re-encrypts
    every sensitive path under the current default provider.
    """
    from open_webui.config import (
        ConfigVersionConflict,
        get_config_with_version,
        get_sensitive_paths_with_meta,
        save_to_db,
    )

    touched = 0
    skipped = 0
    failed = 0

    try:
        data, version = get_config_with_version()
        sensitive_paths = get_sensitive_paths_with_meta()
        # Count how many sensitive paths actually have a string value
        for path in sensitive_paths.keys():
            parts = path.split(".")
            cur = data
            for part in parts[:-1]:
                if not isinstance(cur, dict) or part not in cur:
                    cur = None
                    break
                cur = cur[part]
            if not isinstance(cur, dict):
                continue
            value = cur.get(parts[-1])
            if isinstance(value, str) and value:
                touched += 1
            else:
                skipped += 1

        # Re-save: save_to_db calls _encrypt_config_data which re-encrypts
        # every sensitive path under the current default provider.
        try:
            save_to_db(data, expected_version=version)
        except ConfigVersionConflict:
            # Someone else saved between our read and write — try once more
            data, version = get_config_with_version()
            save_to_db(data, expected_version=version)
    except Exception as e:
        log.exception("Config migrate failed: %s", e)
        failed += 1

    return {"touched": touched, "skipped": skipped, "failed": failed}


def _migrate_dbsphere_connections() -> dict:
    """For each DbSphere row, decrypt then re-encrypt the connection
    secrets via the router. Read+write triggers re-encryption under the
    current default provider — legacy Fernet decrypts via fallback."""
    import copy as _copy

    from open_webui.internal.db import get_db
    from open_webui.models.dbsphere import DbSphere
    from open_webui.utils.crypto import (
        decrypt_value as _decrypt,
    )
    from open_webui.utils.crypto import (
        encrypt_value as _encrypt,
    )
    from open_webui.utils.crypto import (
        is_encrypted as _is_encrypted,
    )

    touched = 0
    skipped = 0
    failed = 0

    try:
        with get_db() as db:
            rows = db.query(DbSphere).all()
            for row in rows:
                data = row.data or {}
                connection = data.get("connection") if isinstance(data, dict) else None
                if not isinstance(connection, dict):
                    skipped += 1
                    continue
                next_data = _copy.deepcopy(data)
                next_conn = next_data["connection"]
                changed = False
                for field in (
                    "password",
                    "access_token",
                    "client_secret",
                    "credentials_json",
                ):
                    val = next_conn.get(field)
                    if not (isinstance(val, str) and val):
                        continue
                    try:
                        plain = _decrypt(val) if _is_encrypted(val) else val
                        next_conn[field] = _encrypt(plain)
                        changed = True
                    except Exception as e:
                        log.warning(
                            "dbsphere %s.%s migrate failed: %s", row.id, field, e
                        )
                        failed += 1
                if changed:
                    row.data = next_data
                    touched += 1
                else:
                    skipped += 1
            db.commit()
    except Exception as e:
        log.exception("DbSphere migrate failed: %s", e)
        failed += 1

    return {"touched": touched, "skipped": skipped, "failed": failed}


def _migrate_user_api_keys() -> dict:
    """Re-encrypt every populated ``user.api_key`` under the current
    KMS provider.

    The column type is ``EncryptedText`` (Phase 4.1), so reading already
    decrypts via the router (legacy Fernet falls through fallback). We
    then re-assign the plaintext and ``flag_modified`` to force an UPDATE
    even when the value is byte-identical to what just got decrypted —
    SQLAlchemy's "value identical" optimization would otherwise skip the
    write and the envelope tag would stay on the old KEK.
    """
    from open_webui.internal.db import get_db
    from open_webui.models.users import User
    from sqlalchemy.orm.attributes import flag_modified

    touched = 0
    skipped = 0
    failed = 0

    try:
        with get_db() as db:
            users = db.query(User).all()
            for u in users:
                api_key = u.api_key
                if not (isinstance(api_key, str) and api_key):
                    skipped += 1
                    continue
                try:
                    # Re-assign + flag_modified forces process_bind_param
                    # to fire so EncryptedText emits a fresh envelope
                    # under the new default provider.
                    u.api_key = api_key
                    flag_modified(u, "api_key")
                    touched += 1
                except Exception as e:
                    log.warning("user %s api_key migrate failed: %s", u.id, e)
                    failed += 1
            db.commit()
    except Exception as e:
        log.exception("User api_key migrate failed: %s", e)
        failed += 1

    return {"touched": touched, "skipped": skipped, "failed": failed}


def _migrate_tool_connections() -> dict:
    """Tool connections: model layer encrypts on write, decrypts on read.
    Touch each row's data to trigger re-encryption under current provider."""
    from open_webui.internal.db import get_db
    from open_webui.models.tool_connections import (
        ToolConnection,
        _decrypt_data_in_place,
        _encrypt_data_in_place,
    )

    touched = 0
    skipped = 0
    failed = 0

    try:
        with get_db() as db:
            rows = db.query(ToolConnection).all()
            for row in rows:
                data = row.data
                if not isinstance(data, dict):
                    skipped += 1
                    continue
                connection = data.get("connection")
                if not (isinstance(connection, dict) and connection.get("key")):
                    skipped += 1
                    continue
                try:
                    # decrypt-in-place handles both legacy plaintext and any
                    # tagged ciphertext; encrypt-in-place writes under the
                    # currently configured router default.
                    import copy as _copy

                    next_data = _decrypt_data_in_place(_copy.deepcopy(data))
                    next_data = _encrypt_data_in_place(next_data)
                    row.data = next_data
                    touched += 1
                except Exception as e:
                    log.warning("tool_connection %s migrate failed: %s", row.id, e)
                    failed += 1
            db.commit()
    except Exception as e:
        log.exception("Tool connection migrate failed: %s", e)
        failed += 1

    return {"touched": touched, "skipped": skipped, "failed": failed}


############################
# ToolServers Config
############################


class ToolServerConnection(BaseModel):
    url: str
    path: str
    auth_type: Optional[str]
    key: Optional[str]
    config: Optional[dict]

    model_config = ConfigDict(extra="allow")


class ToolServersConfigForm(BaseModel):
    TOOL_SERVER_CONNECTIONS: list[ToolServerConnection]


@router.get("/tool_servers", response_model=ToolServersConfigForm)
async def get_tool_servers_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return mask_config_dict(
        {
            "TOOL_SERVER_CONNECTIONS": request.app.state.config.TOOL_SERVER_CONNECTIONS,
        }
    )


@router.post("/tool_servers", response_model=ToolServersConfigForm)
async def set_tool_servers_config(
    request: Request,
    form_data: ToolServersConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.TOOL_SERVER_CONNECTIONS = [
        connection.model_dump() for connection in form_data.TOOL_SERVER_CONNECTIONS
    ]

    request.app.state.TOOL_SERVERS = await get_tool_servers_data(
        request.app.state.config.TOOL_SERVER_CONNECTIONS
    )

    AuditLogger.log_settings_change(
        "connections/tool_servers", after_data=form_data.model_dump()
    )
    return mask_config_dict(
        {
            "TOOL_SERVER_CONNECTIONS": request.app.state.config.TOOL_SERVER_CONNECTIONS,
        }
    )


@router.post("/tool_servers/verify")
async def verify_tool_servers_config(
    request: Request,
    form_data: ToolServerConnection,
    user=Depends(get_admin_settings_write_access),
):
    """
    Verify the connection to the tool server.
    """
    try:
        token = None
        if form_data.auth_type == "bearer":
            token = form_data.key
        elif form_data.auth_type == "session":
            token = request.state.token.credentials

        url = f"{form_data.url}/{form_data.path}"
        return await get_tool_server_data(token, url)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect to the tool server: {str(e)}",
        )


############################
# CodeInterpreterConfig
############################
class CodeInterpreterConfigForm(BaseModel):
    ENABLE_CODE_EXECUTION: bool
    CODE_EXECUTION_ENGINE: str
    CODE_EXECUTION_JUPYTER_URL: Optional[str]
    CODE_EXECUTION_JUPYTER_AUTH: Optional[str]
    CODE_EXECUTION_JUPYTER_AUTH_TOKEN: Optional[str]
    CODE_EXECUTION_JUPYTER_AUTH_PASSWORD: Optional[str]
    CODE_EXECUTION_JUPYTER_TIMEOUT: Optional[int]


@router.get("/code_execution", response_model=CodeInterpreterConfigForm)
async def get_code_execution_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return mask_config_dict(
        {
            "ENABLE_CODE_EXECUTION": request.app.state.config.ENABLE_CODE_EXECUTION,
            "CODE_EXECUTION_ENGINE": request.app.state.config.CODE_EXECUTION_ENGINE,
            "CODE_EXECUTION_JUPYTER_URL": request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
            "CODE_EXECUTION_JUPYTER_AUTH": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH,
            "CODE_EXECUTION_JUPYTER_AUTH_TOKEN": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
            "CODE_EXECUTION_JUPYTER_AUTH_PASSWORD": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
            "CODE_EXECUTION_JUPYTER_TIMEOUT": request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        }
    )


@router.post("/code_execution", response_model=CodeInterpreterConfigForm)
async def set_code_execution_config(
    request: Request,
    form_data: CodeInterpreterConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.ENABLE_CODE_EXECUTION = form_data.ENABLE_CODE_EXECUTION

    request.app.state.config.CODE_EXECUTION_ENGINE = form_data.CODE_EXECUTION_ENGINE
    request.app.state.config.CODE_EXECUTION_JUPYTER_URL = (
        form_data.CODE_EXECUTION_JUPYTER_URL
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH = (
        form_data.CODE_EXECUTION_JUPYTER_AUTH
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN = (
        resolve_sensitive_value(
            form_data.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
            request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
        )
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD = (
        resolve_sensitive_value(
            form_data.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
            request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
        )
    )
    request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT = (
        form_data.CODE_EXECUTION_JUPYTER_TIMEOUT
    )

    AuditLogger.log_settings_change("code_execution", after_data=form_data.model_dump())
    return mask_config_dict(
        {
            "ENABLE_CODE_EXECUTION": request.app.state.config.ENABLE_CODE_EXECUTION,
            "CODE_EXECUTION_ENGINE": request.app.state.config.CODE_EXECUTION_ENGINE,
            "CODE_EXECUTION_JUPYTER_URL": request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
            "CODE_EXECUTION_JUPYTER_AUTH": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH,
            "CODE_EXECUTION_JUPYTER_AUTH_TOKEN": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
            "CODE_EXECUTION_JUPYTER_AUTH_PASSWORD": request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
            "CODE_EXECUTION_JUPYTER_TIMEOUT": request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        }
    )


############################
# SetDefaultModels
############################
class ModelsConfigForm(BaseModel):
    DEFAULT_MODELS: Optional[str]
    MODEL_ORDER_LIST: Optional[list[str]]


@router.get("/models", response_model=ModelsConfigForm)
async def get_models_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return {
        "DEFAULT_MODELS": request.app.state.config.DEFAULT_MODELS,
        "MODEL_ORDER_LIST": request.app.state.config.MODEL_ORDER_LIST,
    }


@router.post("/models", response_model=ModelsConfigForm)
async def set_models_config(
    request: Request,
    form_data: ModelsConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.DEFAULT_MODELS = form_data.DEFAULT_MODELS
    request.app.state.config.MODEL_ORDER_LIST = form_data.MODEL_ORDER_LIST
    AuditLogger.log_settings_change("models", after_data=form_data.model_dump())
    return {
        "DEFAULT_MODELS": request.app.state.config.DEFAULT_MODELS,
        "MODEL_ORDER_LIST": request.app.state.config.MODEL_ORDER_LIST,
    }


class PromptSuggestion(BaseModel):
    title: list[str]
    content: str


class SetDefaultSuggestionsForm(BaseModel):
    suggestions: list[PromptSuggestion]


@router.post("/suggestions", response_model=list[PromptSuggestion])
async def set_default_suggestions(
    request: Request,
    form_data: SetDefaultSuggestionsForm,
    user=Depends(get_admin_settings_write_access),
):
    data = form_data.model_dump()
    request.app.state.config.DEFAULT_PROMPT_SUGGESTIONS = data["suggestions"]
    AuditLogger.log_settings_change("interface/suggestions", after_data=data)
    return request.app.state.config.DEFAULT_PROMPT_SUGGESTIONS


############################
# SetBanners
############################


class SetBannersForm(BaseModel):
    banners: list[BannerModel]


@router.post("/banners", response_model=list[BannerModel])
async def set_banners(
    request: Request,
    form_data: SetBannersForm,
    user=Depends(get_admin_settings_write_access),
):
    data = form_data.model_dump()
    request.app.state.config.BANNERS = data["banners"]
    AuditLogger.log_settings_change("interface/banners", after_data=data)
    return request.app.state.config.BANNERS


@router.get("/banners", response_model=list[BannerModel])
async def get_banners(
    request: Request,
    user=Depends(get_verified_user),
):
    return request.app.state.config.BANNERS


############################
# Storage Config
############################


class S3ConfigForm(BaseModel):
    bucket_name: str = ""
    region_name: str = "us-east-1"
    endpoint_url: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    key_prefix: str = ""


class AzureConfigForm(BaseModel):
    endpoint: str = ""
    container_name: str = ""
    storage_key: str = ""


class GCSConfigForm(BaseModel):
    bucket_name: str = ""
    credentials_json: str = ""


class StorageConfigForm(BaseModel):
    image_upload_mode: str = "base64"  # 'base64' or 'storage'
    provider: str = "local"  # 'local', 's3', 'azure', 'gcs'
    s3: Optional[S3ConfigForm] = None
    azure: Optional[AzureConfigForm] = None
    gcs: Optional[GCSConfigForm] = None


@router.get("/storage", response_model=StorageConfigForm)
async def get_storage_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return mask_config_dict(
        {
            "image_upload_mode": request.app.state.config.IMAGE_UPLOAD_MODE,
            "provider": request.app.state.config.STORAGE_PROVIDER,
            "s3": {
                "bucket_name": request.app.state.config.S3_BUCKET_NAME,
                "region_name": request.app.state.config.S3_REGION_NAME,
                "endpoint_url": request.app.state.config.S3_ENDPOINT_URL,
                "access_key_id": request.app.state.config.S3_ACCESS_KEY_ID,
                "secret_access_key": request.app.state.config.S3_SECRET_ACCESS_KEY,
                "key_prefix": request.app.state.config.S3_KEY_PREFIX,
            },
            "azure": {
                "endpoint": request.app.state.config.AZURE_STORAGE_ENDPOINT,
                "container_name": request.app.state.config.AZURE_STORAGE_CONTAINER_NAME,
                "storage_key": request.app.state.config.AZURE_STORAGE_KEY,
            },
            "gcs": {
                "bucket_name": request.app.state.config.GCS_BUCKET_NAME,
                "credentials_json": request.app.state.config.GOOGLE_APPLICATION_CREDENTIALS_JSON,
            },
        }
    )


@router.post("/storage", response_model=StorageConfigForm)
async def set_storage_config(
    request: Request,
    form_data: StorageConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    # Update image upload mode
    request.app.state.config.IMAGE_UPLOAD_MODE = form_data.image_upload_mode
    request.app.state.config.STORAGE_PROVIDER = form_data.provider

    # Update S3 config
    if form_data.s3:
        request.app.state.config.S3_BUCKET_NAME = form_data.s3.bucket_name
        request.app.state.config.S3_REGION_NAME = form_data.s3.region_name
        request.app.state.config.S3_ENDPOINT_URL = form_data.s3.endpoint_url
        request.app.state.config.S3_ACCESS_KEY_ID = form_data.s3.access_key_id
        request.app.state.config.S3_SECRET_ACCESS_KEY = resolve_sensitive_value(
            form_data.s3.secret_access_key,
            request.app.state.config.S3_SECRET_ACCESS_KEY,
        )
        request.app.state.config.S3_KEY_PREFIX = form_data.s3.key_prefix

    # Update Azure config
    if form_data.azure:
        request.app.state.config.AZURE_STORAGE_ENDPOINT = form_data.azure.endpoint
        request.app.state.config.AZURE_STORAGE_CONTAINER_NAME = (
            form_data.azure.container_name
        )
        request.app.state.config.AZURE_STORAGE_KEY = resolve_sensitive_value(
            form_data.azure.storage_key,
            request.app.state.config.AZURE_STORAGE_KEY,
        )

    # Update GCS config
    if form_data.gcs:
        request.app.state.config.GCS_BUCKET_NAME = form_data.gcs.bucket_name
        request.app.state.config.GOOGLE_APPLICATION_CREDENTIALS_JSON = (
            resolve_sensitive_value(
                form_data.gcs.credentials_json,
                request.app.state.config.GOOGLE_APPLICATION_CREDENTIALS_JSON,
            )
        )

    AuditLogger.log_settings_change("storage", after_data=form_data.model_dump())

    # Reinitialize image storage provider with new config
    # Note: Only ImageStorage is reconfigured. The general Storage remains local.
    ImageStorage.reinitialize(
        storage_provider=form_data.provider,
        s3_config={
            "bucket_name": form_data.s3.bucket_name if form_data.s3 else "",
            "region_name": form_data.s3.region_name if form_data.s3 else "us-east-1",
            "endpoint_url": form_data.s3.endpoint_url if form_data.s3 else "",
            "access_key_id": form_data.s3.access_key_id if form_data.s3 else "",
            "secret_access_key": form_data.s3.secret_access_key if form_data.s3 else "",
            "key_prefix": form_data.s3.key_prefix if form_data.s3 else "",
        }
        if form_data.provider == "s3"
        else None,
        azure_config={
            "endpoint": form_data.azure.endpoint if form_data.azure else "",
            "container_name": form_data.azure.container_name if form_data.azure else "",
            "storage_key": form_data.azure.storage_key if form_data.azure else "",
        }
        if form_data.provider == "azure"
        else None,
        gcs_config={
            "bucket_name": form_data.gcs.bucket_name if form_data.gcs else "",
            "credentials_json": request.app.state.config.GOOGLE_APPLICATION_CREDENTIALS_JSON
            if form_data.gcs
            else "",
        }
        if form_data.provider == "gcs"
        else None,
    )

    return mask_config_dict(
        {
            "image_upload_mode": request.app.state.config.IMAGE_UPLOAD_MODE,
            "provider": request.app.state.config.STORAGE_PROVIDER,
            "s3": {
                "bucket_name": request.app.state.config.S3_BUCKET_NAME,
                "region_name": request.app.state.config.S3_REGION_NAME,
                "endpoint_url": request.app.state.config.S3_ENDPOINT_URL,
                "access_key_id": request.app.state.config.S3_ACCESS_KEY_ID,
                "secret_access_key": request.app.state.config.S3_SECRET_ACCESS_KEY,
                "key_prefix": request.app.state.config.S3_KEY_PREFIX,
            },
            "azure": {
                "endpoint": request.app.state.config.AZURE_STORAGE_ENDPOINT,
                "container_name": request.app.state.config.AZURE_STORAGE_CONTAINER_NAME,
                "storage_key": request.app.state.config.AZURE_STORAGE_KEY,
            },
            "gcs": {
                "bucket_name": request.app.state.config.GCS_BUCKET_NAME,
                "credentials_json": request.app.state.config.GOOGLE_APPLICATION_CREDENTIALS_JSON,
            },
        }
    )


class StorageTestForm(BaseModel):
    provider: str
    s3: Optional[S3ConfigForm] = None
    azure: Optional[AzureConfigForm] = None
    gcs: Optional[GCSConfigForm] = None


@router.post("/storage/test")
async def test_storage_connection(
    request: Request,
    form_data: StorageTestForm,
    user=Depends(get_admin_settings_write_access),
):
    """
    Test storage connection with provided configuration.
    """
    try:
        if form_data.provider == "local":
            return {"status": "ok", "message": "Local storage is always available"}

        # Create a temporary storage provider with the test config
        if form_data.provider == "s3":
            if not form_data.s3 or not form_data.s3.bucket_name:
                raise ValueError("S3 bucket name is required")
            provider = get_storage_provider(
                "s3",
                s3_config={
                    "bucket_name": form_data.s3.bucket_name,
                    "region_name": form_data.s3.region_name,
                    "endpoint_url": form_data.s3.endpoint_url or None,
                    "access_key_id": form_data.s3.access_key_id or None,
                    "secret_access_key": form_data.s3.secret_access_key or None,
                    "key_prefix": form_data.s3.key_prefix,
                },
            )
            # Test by listing bucket (will fail if credentials invalid)
            provider.s3_client.head_bucket(Bucket=form_data.s3.bucket_name)
            return {"status": "ok", "message": "S3 connection successful"}

        elif form_data.provider == "azure":
            if not form_data.azure or not form_data.azure.endpoint:
                raise ValueError("Azure storage endpoint is required")
            if not form_data.azure.container_name:
                raise ValueError("Azure container name is required")
            provider = get_storage_provider(
                "azure",
                azure_config={
                    "endpoint": form_data.azure.endpoint,
                    "container_name": form_data.azure.container_name,
                    "storage_key": form_data.azure.storage_key or None,
                },
            )
            # Test by checking container exists
            provider.container_client.get_container_properties()
            return {
                "status": "ok",
                "message": "Azure Blob Storage connection successful",
            }

        elif form_data.provider == "gcs":
            if not form_data.gcs or not form_data.gcs.bucket_name:
                raise ValueError("GCS bucket name is required")
            provider = get_storage_provider(
                "gcs",
                gcs_config={
                    "bucket_name": form_data.gcs.bucket_name,
                    "credentials_json": form_data.gcs.credentials_json or None,
                },
            )
            # Test by checking bucket exists
            provider.bucket.reload()
            return {
                "status": "ok",
                "message": "Google Cloud Storage connection successful",
            }

        else:
            raise ValueError(f"Unsupported storage provider: {form_data.provider}")

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Storage connection test failed: {str(e)}",
        )


############################
# File Storage Config
############################


class FileStorageConfigForm(BaseModel):
    provider: str = "local"  # 'local', 's3', 'azure', 'gcs'
    s3: Optional[S3ConfigForm] = None
    azure: Optional[AzureConfigForm] = None
    gcs: Optional[GCSConfigForm] = None


@router.get("/file-storage", response_model=FileStorageConfigForm)
async def get_file_storage_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return mask_config_dict(
        {
            "provider": request.app.state.config.FILE_STORAGE_PROVIDER,
            "s3": {
                "bucket_name": request.app.state.config.FILE_S3_BUCKET_NAME,
                "region_name": request.app.state.config.FILE_S3_REGION_NAME,
                "endpoint_url": request.app.state.config.FILE_S3_ENDPOINT_URL,
                "access_key_id": request.app.state.config.FILE_S3_ACCESS_KEY_ID,
                "secret_access_key": request.app.state.config.FILE_S3_SECRET_ACCESS_KEY,
                "key_prefix": request.app.state.config.FILE_S3_KEY_PREFIX,
            },
            "azure": {
                "endpoint": request.app.state.config.FILE_AZURE_STORAGE_ENDPOINT,
                "container_name": request.app.state.config.FILE_AZURE_STORAGE_CONTAINER_NAME,
                "storage_key": request.app.state.config.FILE_AZURE_STORAGE_KEY,
            },
            "gcs": {
                "bucket_name": request.app.state.config.FILE_GCS_BUCKET_NAME,
                "credentials_json": request.app.state.config.FILE_GCS_CREDENTIALS_JSON,
            },
        }
    )


@router.post("/file-storage", response_model=FileStorageConfigForm)
async def set_file_storage_config(
    request: Request,
    form_data: FileStorageConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.FILE_STORAGE_PROVIDER = form_data.provider

    if form_data.s3:
        request.app.state.config.FILE_S3_BUCKET_NAME = form_data.s3.bucket_name
        request.app.state.config.FILE_S3_REGION_NAME = form_data.s3.region_name
        request.app.state.config.FILE_S3_ENDPOINT_URL = form_data.s3.endpoint_url
        request.app.state.config.FILE_S3_ACCESS_KEY_ID = form_data.s3.access_key_id
        request.app.state.config.FILE_S3_SECRET_ACCESS_KEY = resolve_sensitive_value(
            form_data.s3.secret_access_key,
            request.app.state.config.FILE_S3_SECRET_ACCESS_KEY,
        )
        request.app.state.config.FILE_S3_KEY_PREFIX = form_data.s3.key_prefix

    if form_data.azure:
        request.app.state.config.FILE_AZURE_STORAGE_ENDPOINT = form_data.azure.endpoint
        request.app.state.config.FILE_AZURE_STORAGE_CONTAINER_NAME = (
            form_data.azure.container_name
        )
        request.app.state.config.FILE_AZURE_STORAGE_KEY = resolve_sensitive_value(
            form_data.azure.storage_key,
            request.app.state.config.FILE_AZURE_STORAGE_KEY,
        )

    if form_data.gcs:
        request.app.state.config.FILE_GCS_BUCKET_NAME = form_data.gcs.bucket_name
        request.app.state.config.FILE_GCS_CREDENTIALS_JSON = resolve_sensitive_value(
            form_data.gcs.credentials_json,
            request.app.state.config.FILE_GCS_CREDENTIALS_JSON,
        )

    AuditLogger.log_settings_change("file-storage", after_data=form_data.model_dump())

    # Reinitialize file storage with new credentials
    Storage.reinitialize(
        storage_provider=form_data.provider,
        s3_config={
            "bucket_name": form_data.s3.bucket_name if form_data.s3 else "",
            "region_name": form_data.s3.region_name if form_data.s3 else "us-east-1",
            "endpoint_url": form_data.s3.endpoint_url if form_data.s3 else "",
            "access_key_id": form_data.s3.access_key_id if form_data.s3 else "",
            "secret_access_key": form_data.s3.secret_access_key if form_data.s3 else "",
            "key_prefix": form_data.s3.key_prefix if form_data.s3 else "",
        }
        if form_data.provider == "s3"
        else None,
        azure_config={
            "endpoint": form_data.azure.endpoint if form_data.azure else "",
            "container_name": form_data.azure.container_name if form_data.azure else "",
            "storage_key": form_data.azure.storage_key if form_data.azure else "",
        }
        if form_data.provider == "azure"
        else None,
        gcs_config={
            "bucket_name": form_data.gcs.bucket_name if form_data.gcs else "",
            "credentials_json": request.app.state.config.FILE_GCS_CREDENTIALS_JSON
            if form_data.gcs
            else "",
        }
        if form_data.provider == "gcs"
        else None,
    )

    return mask_config_dict(
        {
            "provider": request.app.state.config.FILE_STORAGE_PROVIDER,
            "s3": {
                "bucket_name": request.app.state.config.FILE_S3_BUCKET_NAME,
                "region_name": request.app.state.config.FILE_S3_REGION_NAME,
                "endpoint_url": request.app.state.config.FILE_S3_ENDPOINT_URL,
                "access_key_id": request.app.state.config.FILE_S3_ACCESS_KEY_ID,
                "secret_access_key": request.app.state.config.FILE_S3_SECRET_ACCESS_KEY,
                "key_prefix": request.app.state.config.FILE_S3_KEY_PREFIX,
            },
            "azure": {
                "endpoint": request.app.state.config.FILE_AZURE_STORAGE_ENDPOINT,
                "container_name": request.app.state.config.FILE_AZURE_STORAGE_CONTAINER_NAME,
                "storage_key": request.app.state.config.FILE_AZURE_STORAGE_KEY,
            },
            "gcs": {
                "bucket_name": request.app.state.config.FILE_GCS_BUCKET_NAME,
                "credentials_json": request.app.state.config.FILE_GCS_CREDENTIALS_JSON,
            },
        }
    )


class FileStorageTestForm(BaseModel):
    provider: str
    s3: Optional[S3ConfigForm] = None
    azure: Optional[AzureConfigForm] = None
    gcs: Optional[GCSConfigForm] = None


@router.post("/file-storage/test")
async def test_file_storage_connection(
    request: Request,
    form_data: FileStorageTestForm,
    user=Depends(get_admin_settings_write_access),
):
    """Test file storage connection with provided configuration."""
    try:
        if form_data.provider == "local":
            return {"status": "ok", "message": "Local storage is always available"}

        if form_data.provider == "s3":
            if not form_data.s3 or not form_data.s3.bucket_name:
                raise ValueError("S3 bucket name is required")
            provider = get_storage_provider(
                "s3",
                s3_config={
                    "bucket_name": form_data.s3.bucket_name,
                    "region_name": form_data.s3.region_name,
                    "endpoint_url": form_data.s3.endpoint_url or None,
                    "access_key_id": form_data.s3.access_key_id or None,
                    "secret_access_key": form_data.s3.secret_access_key or None,
                    "key_prefix": form_data.s3.key_prefix,
                },
            )
            provider.s3_client.head_bucket(Bucket=form_data.s3.bucket_name)
            return {"status": "ok", "message": "S3 connection successful"}

        elif form_data.provider == "azure":
            if not form_data.azure or not form_data.azure.endpoint:
                raise ValueError("Azure storage endpoint is required")
            if not form_data.azure.container_name:
                raise ValueError("Azure container name is required")
            provider = get_storage_provider(
                "azure",
                azure_config={
                    "endpoint": form_data.azure.endpoint,
                    "container_name": form_data.azure.container_name,
                    "storage_key": form_data.azure.storage_key or None,
                },
            )
            provider.container_client.get_container_properties()
            return {
                "status": "ok",
                "message": "Azure Blob Storage connection successful",
            }

        elif form_data.provider == "gcs":
            if not form_data.gcs or not form_data.gcs.bucket_name:
                raise ValueError("GCS bucket name is required")
            provider = get_storage_provider(
                "gcs",
                gcs_config={
                    "bucket_name": form_data.gcs.bucket_name,
                    "credentials_json": form_data.gcs.credentials_json or None,
                },
            )
            provider.bucket.reload()
            return {
                "status": "ok",
                "message": "Google Cloud Storage connection successful",
            }

        else:
            raise ValueError(f"Unsupported storage provider: {form_data.provider}")

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"File storage connection test failed: {str(e)}",
        )


############################
# Monitoring Config
############################


class MonitoringConfigForm(BaseModel):
    ENABLE_OTEL: bool
    OTEL_EXPORTER_OTLP_ENDPOINT: str


@router.get("/monitoring", response_model=MonitoringConfigForm)
async def get_monitoring_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return {
        "ENABLE_OTEL": request.app.state.config.ENABLE_OTEL,
        "OTEL_EXPORTER_OTLP_ENDPOINT": request.app.state.config.OTEL_EXPORTER_OTLP_ENDPOINT,
    }


@router.post("/monitoring", response_model=MonitoringConfigForm)
async def update_monitoring_config(
    request: Request,
    form_data: MonitoringConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.ENABLE_OTEL = form_data.ENABLE_OTEL
    request.app.state.config.OTEL_EXPORTER_OTLP_ENDPOINT = (
        form_data.OTEL_EXPORTER_OTLP_ENDPOINT
    )
    AuditLogger.log_settings_change("monitoring", after_data=form_data.model_dump())
    return {
        "ENABLE_OTEL": request.app.state.config.ENABLE_OTEL,
        "OTEL_EXPORTER_OTLP_ENDPOINT": request.app.state.config.OTEL_EXPORTER_OTLP_ENDPOINT,
    }


@router.get("/monitoring/download")
async def download_monitoring_bundle(user=Depends(get_admin_settings_read_access)):
    from open_webui.env import DATABASE_URL, REDIS_URL

    data = generate_monitoring_bundle(database_url=DATABASE_URL, redis_url=REDIS_URL)
    return Response(
        content=data,
        media_type="application/gzip",
        headers={
            "Content-Disposition": "attachment; filename=cloosphere-monitor.tar.gz"
        },
    )


####################################
# External Worker Settings
####################################


@router.get("/external-worker/status")
async def get_external_worker_status(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    task_queue = getattr(request.app.state, "task_queue", None)
    redis_connected = False
    redis_message = "Redis not configured"
    queue_stats = {"total": 0, "pending": 0, "consumers": 0}

    if task_queue:
        health = await task_queue.health_check()
        redis_connected = health.get("status") == "connected"
        redis_message = health.get("status", "unknown")
        if redis_connected:
            queue_stats = await task_queue.get_queue_stats()

    return {
        "redis": {"connected": redis_connected, "message": redis_message},
        "queue": queue_stats,
    }


@router.get("/external-worker/tasks")
async def list_worker_tasks(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return []
    return await task_queue.list_tasks(count=100)


@router.delete("/external-worker/tasks/{msg_id}")
async def delete_worker_task(
    msg_id: str,
    request: Request,
    user=Depends(get_admin_settings_write_access),
):
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return {"success": False}
    success = await task_queue.delete_task(msg_id)
    return {"success": success}


@router.delete("/external-worker/tasks")
async def clear_worker_queue(
    request: Request, user=Depends(get_admin_settings_write_access)
):
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return {"deleted": 0}
    deleted = await task_queue.clear_queue()
    return {"deleted": deleted}


# ─────────────────────────────────────────
# Queue Consumer / Zombie 관리
# ─────────────────────────────────────────


@router.get("/external-worker/consumers")
async def list_worker_consumers(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    """Consumer group 내 consumer 목록 (좀비 여부 포함)."""
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return []
    return await task_queue.list_consumers()


@router.get("/external-worker/pending")
async def list_worker_pending(
    request: Request,
    count: int = 20,
    min_idle_ms: int = 0,
    user=Depends(get_admin_settings_read_access),
):
    """가장 오래된 미처리(pending) 메시지 목록 (기본 20개 샘플).

    - count: 최대 반환 개수 (기본 20)
    - min_idle_ms: 이 시간 이상 stuck된 것만 (0이면 전체)
    """
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return []
    return await task_queue.list_pending_messages(count=count, min_idle_ms=min_idle_ms)


@router.delete("/external-worker/pending/{msg_id}")
async def ack_and_delete_pending_message(
    msg_id: str,
    request: Request,
    user=Depends(get_admin_settings_write_access),
):
    """단일 pending 메시지 강제 ack + 삭제.

    특정 독성(poison) 메시지만 핀포인트로 제거할 때 사용.
    XACK + XDEL을 함께 수행하여 PEL을 정리한다.
    """
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return {"success": False, "error": "no_queue"}
    return await task_queue.ack_and_delete_message(msg_id)


@router.delete("/external-worker/consumers/{consumer_name}")
async def delete_worker_consumer(
    consumer_name: str,
    request: Request,
    reclaim_pending: bool = False,
    user=Depends(get_admin_settings_write_access),
):
    """특정 consumer 삭제.

    - reclaim_pending=false (기본): pending이 있으면 거부 (has_pending 에러)
    - reclaim_pending=true: pending 메시지를 먼저 ack/delete 후 consumer 삭제

    ⚠ Redis XGROUP DELCONSUMER는 pending 메시지가 있어도 그냥 삭제하지만,
    그 메시지들은 xpending 목록에서 사라지고 재배달되지 않아 사실상 유실된다.
    따라서 이 API는 명시적으로 reclaim_pending=true일 때만 pending 있는 consumer 삭제 허용.
    """
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return {
            "success": False,
            "reclaimed": 0,
            "pending_before": 0,
            "error": "no_queue",
        }
    return await task_queue.delete_consumer(
        consumer_name, reclaim_pending=reclaim_pending
    )


@router.post("/external-worker/cleanup-zombies")
async def cleanup_zombie_consumers(
    request: Request,
    idle_threshold_ms: int = 3_600_000,
    user=Depends(get_admin_settings_write_access),
):
    """좀비 consumer 일괄 정리.

    조건: idle > idle_threshold_ms (기본 1시간) AND pending == 0
    """
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return {"deleted": 0}
    deleted = await task_queue.cleanup_zombie_consumers(
        idle_threshold_ms=idle_threshold_ms
    )
    return {"deleted": deleted}


@router.post("/external-worker/reclaim-stuck")
async def reclaim_stuck_messages(
    request: Request,
    min_idle_ms: int = 300_000,
    user=Depends(get_admin_settings_write_access),
):
    """stuck된 pending 메시지 강제 ack + 삭제.

    오래 (기본 5분 이상) pending 상태인 메시지는 보통 crash된 워커가
    잡고 있던 것이므로 강제로 ack 처리하여 큐에서 제거.
    """
    task_queue = getattr(request.app.state, "task_queue", None)
    if not task_queue:
        return {"reclaimed": 0, "errors": 0}
    return await task_queue.reclaim_stuck_messages(min_idle_ms=min_idle_ms)
