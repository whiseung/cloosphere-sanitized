"""
KMSRouter — single entry point for all encrypt/decrypt operations.

Dispatch rules:
    1. Tagged value (kms:<provider>:<algo>:<version>:...)
       → routed to the provider whose tag_prefix matches.
    2. Legacy untagged Fernet (gAAAAA...)
       → routed to FernetProvider (backward compat).
    3. Plaintext (anything else, including empty string)
       → returned unchanged.

This means a deployment with KMS_PROVIDER=fernet (default) keeps reading
both legacy and tagged data; a deployment that later switches to Azure
KV will write new tagged values via the new provider, while still
decrypting any legacy Fernet values via the FernetProvider fallback.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from open_webui.utils.kms.base import (
    KMSProvider,
    is_legacy_fernet,
    is_tagged,
    parse_tag,
)
from open_webui.utils.kms.fernet import FernetProvider

log = logging.getLogger(__name__)


class KMSRouter:
    """Provider dispatcher.

    Phase 1 ships with FernetProvider only as both `default` and the legacy
    fallback. Future phases register additional providers via add_provider().
    """

    def __init__(self, default: KMSProvider, fernet_fallback: FernetProvider) -> None:
        self._providers: dict[str, KMSProvider] = {}
        self._default: KMSProvider = default
        self._fernet: FernetProvider = fernet_fallback
        self.add_provider(fernet_fallback)
        if default is not fernet_fallback:
            self.add_provider(default)

    def add_provider(self, provider: KMSProvider) -> None:
        prefix = provider.tag_prefix
        existing = self._providers.get(prefix)
        if existing is not None and existing is not provider:
            log.warning(
                "KMSRouter: duplicate provider for prefix %r (replacing %r with %r)",
                prefix,
                type(existing).__name__,
                type(provider).__name__,
            )
        self._providers[prefix] = provider

    def set_default(self, provider: KMSProvider) -> None:
        self._default = provider
        self.add_provider(provider)

    @property
    def default_provider(self) -> KMSProvider:
        return self._default

    # --- core API ---------------------------------------------------------

    def encrypt(self, plaintext: str, context: Optional[dict] = None) -> str:
        """Encrypt with the currently configured default provider."""
        if not plaintext:
            return ""
        return self._default.encrypt(plaintext, context)

    def decrypt(self, value: str, context: Optional[dict] = None) -> str:
        """Decrypt — auto-routes by tag prefix; passes plaintext through."""
        if not value:
            return value

        # 1. Tagged → exact prefix match
        if is_tagged(value):
            parsed = parse_tag(value)
            if parsed is not None:
                provider = self._providers.get(parsed.prefix)
                if provider is not None:
                    return provider.decrypt(value, context)
                # Tagged but unknown provider — likely a deployment
                # downgrade or missing provider config. Fail loudly so
                # the operator notices instead of returning ciphertext.
                raise ValueError(
                    f"No KMS provider registered for tag prefix {parsed.prefix!r}"
                )
            # Malformed tag — fall through to legacy/plaintext

        # 2. Legacy untagged Fernet
        if is_legacy_fernet(value):
            return self._fernet.decrypt(value, context)

        # 3. Plaintext passthrough (matches legacy _decrypt_config_data behavior)
        return value

    def is_encrypted(self, value: str) -> bool:
        """Recognize tagged or legacy-Fernet ciphertext."""
        if not isinstance(value, str) or not value:
            return False
        return is_tagged(value) or is_legacy_fernet(value)


# --- module-level singleton -----------------------------------------------

_router: Optional[KMSRouter] = None
_router_lock = threading.Lock()


def get_router() -> KMSRouter:
    """Return the process-wide KMSRouter singleton.

    Construction order:
      1. Inside the lock, build a Fernet-only router and PUBLISH it
         immediately as the singleton. This is the bootstrap-safe state
         — anything that recursively calls back into get_router()
         during the next step (config.py imports, _decrypt_config_data
         on initial CONFIG_DATA load) sees a working router.
      2. Outside the lock, read `kms.provider` from PersistentConfig
         and, if a managed backend is configured, swap the router's
         default provider in-place. The Fernet fallback stays so
         legacy/tagged-Fernet ciphertexts keep decrypting.
      3. On any provider-construction error, log and stay on Fernet so
         the application keeps booting — managed-KMS misconfiguration
         must never lock operators out of their own deployment.

    Releasing the lock before the (potentially heavy, possibly
    recursive) config-driven init step is the critical bit: the
    earlier version held the lock around `_attach_configured_provider`
    and dead-locked when `_decrypt_config_data` triggered an inner
    `get_router()` call during config.py module load.
    """
    global _router
    if _router is not None:
        return _router
    with _router_lock:
        if _router is not None:
            return _router
        fernet = FernetProvider()
        _router = KMSRouter(default=fernet, fernet_fallback=fernet)
    # Outside the lock — heavy / re-entrant work allowed.
    _attach_configured_provider(_router)
    return _router


def _attach_configured_provider(router: KMSRouter) -> None:
    """Read kms.provider from config and register the matching provider.

    Reads from the PersistentConfig instance (which already resolved the
    env-value vs DB-value precedence at construction time) rather than
    `get_config_value()` — the latter only sees DB state, so a fresh
    deployment with `KMS_PROVIDER=azkv-env` in .env but nothing in the
    Config table would fall through to Fernet.

    Failures degrade to Fernet rather than blocking startup.
    """
    try:
        from open_webui.config import KMS_PROVIDER
    except Exception as e:
        log.debug("KMSRouter: KMS_PROVIDER not yet importable (%s)", e)
        return

    provider_name = (str(KMS_PROVIDER.value) or "fernet").strip().lower()
    if provider_name in ("", "fernet"):
        return

    try:
        provider = _build_provider(provider_name)
    except Exception as e:
        log.error(
            "KMSRouter: failed to initialise provider %r — staying on Fernet (%s)",
            provider_name,
            e,
        )
        return

    if provider is not None:
        router.set_default(provider)
        log.info("KMSRouter: default provider set to %r", provider_name)


def _build_provider(name: str) -> Optional[KMSProvider]:
    """Construct a managed-KMS provider from current config. Lazy imports
    keep azure-keyvault-keys / boto3 / google-cloud-kms out of the
    bootstrap path for deployments that don't use them."""
    if name == "azkv-env":
        from open_webui.config import (
            KMS_AZURE_KEY_VAULT_KEY_URI,
            KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED,
        )
        from open_webui.utils.kms.azure_key_vault import (
            AzureKeyVaultEnvelopeProvider,
        )

        key_uri = (str(KMS_AZURE_KEY_VAULT_KEY_URI.value) or "").strip()
        if not key_uri:
            raise ValueError(
                "kms.provider=azkv-env requires kms.azure.key_vault.key_uri"
            )
        # Phase 4.4 — optional Restricted-tier KEK. Empty string means
        # all classifications share the default KEK.
        restricted_uri = (
            str(KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED.value) or ""
        ).strip() or None
        return AzureKeyVaultEnvelopeProvider(
            key_id=key_uri, restricted_key_id=restricted_uri
        )

    raise ValueError(f"Unknown KMS provider: {name!r}")


def reset_router_for_tests() -> None:
    """Test hook — drop the singleton so tests can swap providers."""
    global _router
    with _router_lock:
        _router = None


def reload_router() -> None:
    """Drop the singleton so the next get_router() call rebuilds from
    current config. Used by the admin endpoint that saves new KMS
    provider settings — avoids requiring a process restart for the
    change to take effect."""
    global _router
    with _router_lock:
        _router = None
