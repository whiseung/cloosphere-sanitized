"""KMS Phase 4.5 — automatic KEK rotation tests.

These tests cover the rotation orchestration in
``backend/open_webui/utils/kms/rotation.py`` without contacting a real
Azure Key Vault. The KV ``KeyClient`` is patched to return a synthesized
"latest version" so we can drive each branch (up-to-date, would-rotate,
error, dry-run, multi-tier).

We do NOT test the live ``_perform_rotation`` swap+rewrap path here —
that runs through ``_run_kms_migrate_all_scopes`` which needs an actual
SQLAlchemy app + KMS provider. The existing envelope/router tests cover
that path; rotation-specific logic is the version comparison and the
audit-row decisions.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-phase4-5")

from open_webui.utils.kms import rotation as kms_rotation

# --- _split_key_uri parser ------------------------------------------------


def test_split_key_uri_versioned():
    vault, name, version = kms_rotation._split_key_uri(
        "https://my-vault.vault.azure.net/keys/cloosphere-kek/abc123"
    )
    assert vault == "https://my-vault.vault.azure.net"
    assert name == "cloosphere-kek"
    assert version == "abc123"


def test_split_key_uri_no_version():
    vault, name, version = kms_rotation._split_key_uri(
        "https://my-vault.vault.azure.net/keys/cloosphere-kek"
    )
    assert vault == "https://my-vault.vault.azure.net"
    assert name == "cloosphere-kek"
    assert version == ""


def test_split_key_uri_rejects_malformed():
    with pytest.raises(ValueError):
        kms_rotation._split_key_uri("not-a-url")
    with pytest.raises(ValueError):
        kms_rotation._split_key_uri("")


# --- _check_one_kek decision matrix ---------------------------------------


def _make_check_fixture(latest_version: str):
    """Return a context manager that patches:
      - the credential builder (returns a mock object)
      - the KV ``_resolve_latest_version`` to return ``latest_version``
    so a single test can run against a deterministic "latest"."""
    return patch.multiple(
        kms_rotation,
        _build_credential=lambda: object(),
        _resolve_latest_version=lambda *_, **__: latest_version,
    )


def test_check_one_kek_up_to_date():
    """Latest version == current → status='up-to-date', no rotation, no audit."""
    with _make_check_fixture(latest_version="v1"):
        result = kms_rotation._check_one_kek(
            classification="confidential",
            current_uri="https://v.vault.azure.net/keys/k/v1",
            actor_id=None,
            dry_run=True,
        )
    assert result["status"] == "up-to-date"
    assert result["current_version"] == "v1"


def test_check_one_kek_would_rotate_in_dry_run():
    """Latest != current + dry_run=True → records audit, no live swap."""
    with _make_check_fixture(latest_version="v2"):
        # The audit shim is best-effort; we don't assert on it firing.
        # The decision branch is what matters.
        result = kms_rotation._check_one_kek(
            classification="confidential",
            current_uri="https://v.vault.azure.net/keys/k/v1",
            actor_id="user-42",
            dry_run=True,
        )
    assert result["status"] == "would-rotate"
    assert result["from_version"] == "v1"
    assert result["to_version"] == "v2"
    assert result["to_uri"] == "https://v.vault.azure.net/keys/k/v2"


def test_check_one_kek_skipped_when_uri_blank():
    """Empty URI (e.g. Restricted tier not configured) → skipped:not-configured."""
    result = kms_rotation._check_one_kek(
        classification="restricted",
        current_uri="",
        actor_id=None,
        dry_run=True,
    )
    assert result["status"] == "skipped:not-configured"


def test_check_one_kek_error_on_kv_failure():
    """KV unreachable / credential rejected → status='error' with type name."""

    def boom(*_a, **_kw):
        raise RuntimeError("simulated KV outage")

    with patch.multiple(
        kms_rotation,
        _build_credential=lambda: object(),
        _resolve_latest_version=boom,
    ):
        result = kms_rotation._check_one_kek(
            classification="confidential",
            current_uri="https://v.vault.azure.net/keys/k/v1",
            actor_id=None,
            dry_run=True,
        )
    assert result["status"] == "error"
    assert "simulated KV outage" in result["error"]


def test_check_one_kek_error_on_bad_uri():
    """Malformed URI never reaches the KV call — early validation."""
    result = kms_rotation._check_one_kek(
        classification="confidential",
        current_uri="not-a-url",
        actor_id=None,
        dry_run=True,
    )
    assert result["status"] == "error"
    assert "bad-uri" in result["error"]


# --- check_and_rotate orchestration ---------------------------------------


class _FakeAppConfig:
    """Bare stand-in for ``app.state.config`` — only the attrs the
    rotation flow actually reads."""

    def __init__(
        self,
        provider: str = "azkv-env",
        default_uri: str = "https://v.vault.azure.net/keys/k/v1",
        restricted_uri: str = "",
        dry_run: bool = True,
    ):
        self.KMS_PROVIDER = provider
        self.KMS_AZURE_KEY_VAULT_KEY_URI = default_uri
        self.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED = restricted_uri
        self.KMS_ROTATION_DRY_RUN = dry_run


class _FakeApp:
    def __init__(self, config: _FakeAppConfig):
        # FastAPI shape: app.state.config
        self.state = type("S", (), {"config": config})()


def test_check_and_rotate_skips_on_fernet_provider():
    """Fernet has no KEK to rotate — the check must early-out without any
    KV call."""
    app = _FakeApp(_FakeAppConfig(provider="fernet"))
    with _make_check_fixture(latest_version="v2"):  # would never be hit
        summary = kms_rotation.check_and_rotate(app)
    assert summary["ok"] is True
    assert summary["tiers"] == []
    assert summary["skipped_reason"] == "provider!=azkv-env"


def test_check_and_rotate_default_only_when_restricted_unset():
    """Single-tier deployment — only the default KEK is checked."""
    app = _FakeApp(_FakeAppConfig(restricted_uri=""))
    with _make_check_fixture(latest_version="v1"):
        # Patch the persistence calls so the real config.save() doesn't
        # fire against a missing PersistentConfig instance.
        with patch.object(
            kms_rotation, "_resolve_latest_version", lambda *_a, **_kw: "v1"
        ):
            summary = kms_rotation.check_and_rotate(app, dry_run=True)
    assert summary["ok"] is True
    assert len(summary["tiers"]) == 1
    assert summary["tiers"][0]["classification"] == "confidential"


def test_check_and_rotate_both_tiers_when_restricted_set():
    """Dual-tier deployment — both confidential + restricted are checked,
    independently. Restricted having a different latest version → its
    own would-rotate while default stays up-to-date."""
    app = _FakeApp(
        _FakeAppConfig(
            default_uri="https://v.vault.azure.net/keys/default/v-current",
            restricted_uri="https://v.vault.azure.net/keys/pii/v-old",
        )
    )

    def latest_for(vault_url, key_name, _credential):
        # Default is current, Restricted has a newer version available.
        if key_name == "default":
            return "v-current"
        if key_name == "pii":
            return "v-new"
        return None

    with patch.multiple(
        kms_rotation,
        _build_credential=lambda: object(),
        _resolve_latest_version=latest_for,
    ):
        summary = kms_rotation.check_and_rotate(app, dry_run=True)

    assert summary["ok"] is True
    by_class = {t["classification"]: t for t in summary["tiers"]}
    assert by_class["confidential"]["status"] == "up-to-date"
    assert by_class["restricted"]["status"] == "would-rotate"
    assert by_class["restricted"]["to_version"] == "v-new"


def test_check_and_rotate_dry_run_falls_back_to_config():
    """When the caller doesn't pass dry_run, the value comes from the
    PersistentConfig snapshot — operator opt-in via UI."""
    app = _FakeApp(_FakeAppConfig(dry_run=True))
    with patch.multiple(
        kms_rotation,
        _build_credential=lambda: object(),
        _resolve_latest_version=lambda *_a, **_kw: "v2",
    ):
        summary = kms_rotation.check_and_rotate(app)  # no explicit dry_run
    assert summary["dry_run"] is True
    # Even though the latest differs, no live swap fired (would-rotate path).
    assert summary["tiers"][0]["status"] == "would-rotate"
