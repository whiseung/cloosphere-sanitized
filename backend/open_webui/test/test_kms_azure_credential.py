"""Credential resolution tests for the Azure KV envelope provider.

These cover the three-tier fallback in ``CryptoClientFactory._resolve_credential``:

  1. ``KMS_AZURE_*`` Service Principal (dedicated for cross-tenant Key Vault)
  2. ``MICROSOFT_CLIENT_*`` Service Principal (re-use existing OAuth app)
  3. ``DefaultAzureCredential`` (Managed Identity / az login)

The fallback exists because Cloosphere often has the OAuth identity in one
tenant and Key Vault in a different tenant. The dedicated Service
Principal is only required for the cross-tenant case; otherwise the
existing OAuth credentials work.

Tests stub out the azure-identity classes so no real auth occurs.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Optional

import pytest

os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-credential")

from open_webui.utils.kms.azure_key_vault import CryptoClientFactory

# --- azure-identity stubs -------------------------------------------------


class _StubClientSecretCredential:
    instances: list["_StubClientSecretCredential"] = []

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        type(self).instances.append(self)


class _StubDefaultAzureCredential:
    instances: list["_StubDefaultAzureCredential"] = []

    def __init__(self) -> None:
        type(self).instances.append(self)


@pytest.fixture(autouse=True)
def _patch_azure_identity(monkeypatch):
    """Replace azure.identity classes with stubs so resolution can be
    inspected without making real auth calls."""
    _StubClientSecretCredential.instances.clear()
    _StubDefaultAzureCredential.instances.clear()

    fake_module = types.SimpleNamespace(
        ClientSecretCredential=_StubClientSecretCredential,
        DefaultAzureCredential=_StubDefaultAzureCredential,
    )
    monkeypatch.setitem(sys.modules, "azure.identity", fake_module)
    yield


@pytest.fixture
def cfg_stub(monkeypatch):
    """Patch open_webui.config attributes that CryptoClientFactory reads.

    Returns a setter so each test can declare exactly which credential
    variables are populated. Unset values use empty string (matches the
    PersistentConfig default).
    """
    import open_webui.config as cfg

    class _Holder:
        def __init__(self, value: str = "") -> None:
            self.value = value

    holders = {
        name: _Holder()
        for name in (
            "KMS_AZURE_TENANT_ID",
            "KMS_AZURE_CLIENT_ID",
            "KMS_AZURE_CLIENT_SECRET",
            "MICROSOFT_CLIENT_TENANT_ID",
            "MICROSOFT_CLIENT_ID",
            "MICROSOFT_CLIENT_SECRET",
        )
    }
    for name, holder in holders.items():
        monkeypatch.setattr(cfg, name, holder, raising=False)

    def _set(**values: Optional[str]) -> None:
        for name, value in values.items():
            holders[name].value = value or ""

    return _set


# --- tests ----------------------------------------------------------------


def test_kms_azure_credentials_take_priority(cfg_stub):
    cfg_stub(
        KMS_AZURE_TENANT_ID="tenant-b",
        KMS_AZURE_CLIENT_ID="kms-client-id",
        KMS_AZURE_CLIENT_SECRET="kms-secret",
        MICROSOFT_CLIENT_TENANT_ID="tenant-a",
        MICROSOFT_CLIENT_ID="ms-client-id",
        MICROSOFT_CLIENT_SECRET="ms-secret",
    )

    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()

    assert isinstance(cred, _StubClientSecretCredential)
    assert cred.tenant_id == "tenant-b"
    assert cred.client_id == "kms-client-id"
    assert cred.client_secret == "kms-secret"
    # The MS fallback path must NOT have been touched
    assert len(_StubClientSecretCredential.instances) == 1
    assert not _StubDefaultAzureCredential.instances


def test_microsoft_oauth_creds_used_when_kms_unset(cfg_stub):
    cfg_stub(
        KMS_AZURE_TENANT_ID="",
        KMS_AZURE_CLIENT_ID="",
        KMS_AZURE_CLIENT_SECRET="",
        MICROSOFT_CLIENT_TENANT_ID="tenant-a",
        MICROSOFT_CLIENT_ID="ms-client-id",
        MICROSOFT_CLIENT_SECRET="ms-secret",
    )

    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()

    assert isinstance(cred, _StubClientSecretCredential)
    assert cred.tenant_id == "tenant-a"
    assert cred.client_id == "ms-client-id"
    assert cred.client_secret == "ms-secret"


def test_default_azure_credential_when_nothing_set(cfg_stub):
    cfg_stub()  # all empty
    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()

    assert isinstance(cred, _StubDefaultAzureCredential)
    assert not _StubClientSecretCredential.instances


def test_partial_kms_credentials_skip_to_default(cfg_stub):
    """If only 1-2 of the KMS triple are set, the resolver must NOT build
    a half-initialised ClientSecretCredential. Phase 4.1 cross-tenant fix:
    when ``KMS_AZURE_TENANT_ID`` is set, the operator has explicitly named
    the KV tenant — falling through to the MICROSOFT_CLIENT_* OAuth
    credential (whose tenant is unrelated) would build a cross-tenant
    credential and surface as ``additionally_allowed_tenants`` errors at
    unwrap time. Skip to ``DefaultAzureCredential`` instead so the
    operator's AZURE_* env vars or Managed Identity can take over within
    the chosen tenant."""
    cfg_stub(
        KMS_AZURE_TENANT_ID="tenant-b",
        KMS_AZURE_CLIENT_ID="",  # missing
        KMS_AZURE_CLIENT_SECRET="kms-secret",
        MICROSOFT_CLIENT_TENANT_ID="tenant-a",
        MICROSOFT_CLIENT_ID="ms-client-id",
        MICROSOFT_CLIENT_SECRET="ms-secret",
    )
    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()

    # Cross-tenant fallback skip — DefaultAzureCredential, NOT a
    # MICROSOFT_CLIENT_*-derived ClientSecretCredential.
    assert isinstance(cred, _StubDefaultAzureCredential)
    assert not _StubClientSecretCredential.instances


def test_partial_microsoft_credentials_skip_to_default(cfg_stub):
    cfg_stub(
        MICROSOFT_CLIENT_TENANT_ID="tenant-a",
        MICROSOFT_CLIENT_ID="ms-client-id",
        MICROSOFT_CLIENT_SECRET="",  # missing
    )
    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()

    assert isinstance(cred, _StubDefaultAzureCredential)


def test_whitespace_only_credentials_treated_as_unset(cfg_stub):
    """Trim whitespace before deciding "is this credential set" — common
    .env mistake (trailing space, copy-paste artefacts)."""
    cfg_stub(
        KMS_AZURE_TENANT_ID="   ",
        KMS_AZURE_CLIENT_ID="\t",
        KMS_AZURE_CLIENT_SECRET="",
    )
    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()

    assert isinstance(cred, _StubDefaultAzureCredential)


def test_explicit_credential_argument_bypasses_resolution(cfg_stub):
    """Tests that inject a mock credential must not have it overridden by
    env-var resolution (the production CryptoClientFactory in tests for
    other behaviour relies on this)."""
    cfg_stub(
        KMS_AZURE_TENANT_ID="tenant-b",
        KMS_AZURE_CLIENT_ID="kms-client-id",
        KMS_AZURE_CLIENT_SECRET="kms-secret",
    )
    sentinel = object()
    factory = CryptoClientFactory(key_id="https://vault/keys/k/v", credential=sentinel)
    assert factory._resolve_credential() is sentinel
    assert not _StubClientSecretCredential.instances


def test_config_import_failure_falls_back_to_default(monkeypatch):
    """If config.py cannot be imported (e.g. tests in an environment where
    open_webui isn't fully bootstrapped), the resolver must not crash —
    fall back to DefaultAzureCredential."""
    import open_webui.config as cfg

    # Make the names unreadable so the lazy import inside _resolve_credential
    # raises. Simpler than monkeypatching __import__.
    for name in ("KMS_AZURE_TENANT_ID", "MICROSOFT_CLIENT_TENANT_ID"):
        monkeypatch.delattr(cfg, name, raising=False)

    factory = CryptoClientFactory(key_id="https://vault/keys/k/v")
    cred = factory._resolve_credential()
    assert isinstance(cred, _StubDefaultAzureCredential)
