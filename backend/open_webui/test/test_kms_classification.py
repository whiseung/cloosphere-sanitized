"""KMS Phase 2 — classification + AAD context tests.

Phase 2 introduces:
  - data classification (public / internal / confidential / restricted)
  - name-based auto-inference for sensitive PersistentConfig entries
  - AAD context builder + canonical serialization for envelope providers
  - context kwargs threaded through encrypt_value / decrypt_value

Phase 2 does *not* yet bind AAD into Fernet ciphertexts (Fernet has no AEAD
support). The Fernet provider accepts and ignores `context`, preserving
binary compatibility with Phase 1 outputs. Phase 3 envelope providers
(AES-256-GCM via Azure KV / AWS KMS / GCP KMS) are the first to actually
verify AAD bindings on decrypt.
"""

import os

import pytest

os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-phase2")

from open_webui.utils import crypto
from open_webui.utils.kms import (
    Classification,
    aad_hash,
    aad_serialize,
    build_aad_context,
    infer_classification,
)
from open_webui.utils.kms.router import reset_router_for_tests


@pytest.fixture(autouse=True)
def _reset_router(monkeypatch):
    """Reset the router singleton AND pin KMS_PROVIDER=fernet so the test
    environment is independent of whatever `.env` has configured."""
    reset_router_for_tests()
    try:
        import open_webui.config as cfg

        class _H:
            value = "fernet"

        monkeypatch.setattr(cfg, "KMS_PROVIDER", _H(), raising=False)
    except Exception:
        pass
    yield
    reset_router_for_tests()


# --- classification enum --------------------------------------------------


def test_classification_ordered_values():
    """Enum values are stable identifiers stored in tags / DB / AAD context.
    Reordering or renaming would invalidate stored AAD hashes."""
    assert Classification.PUBLIC.value == "public"
    assert Classification.INTERNAL.value == "internal"
    assert Classification.CONFIDENTIAL.value == "confidential"
    assert Classification.RESTRICTED.value == "restricted"


def test_classification_from_value_accepts_str_and_enum():
    assert Classification.from_value("confidential") is Classification.CONFIDENTIAL
    assert Classification.from_value("CONFIDENTIAL") is Classification.CONFIDENTIAL
    assert (
        Classification.from_value(Classification.RESTRICTED)
        is Classification.RESTRICTED
    )
    with pytest.raises(ValueError):
        Classification.from_value("nonsense")
    with pytest.raises(ValueError):
        Classification.from_value(None)


# --- name-based inference -------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        # confidential — credentials / secrets
        ("openai.api_key", Classification.CONFIDENTIAL),
        ("OPENAI_API_KEYS", Classification.CONFIDENTIAL),
        ("oauth.google.client_secret", Classification.CONFIDENTIAL),
        ("db_password", Classification.CONFIDENTIAL),
        ("auth_token", Classification.CONFIDENTIAL),
        ("aws_access_key", Classification.CONFIDENTIAL),
        ("subscription_key", Classification.CONFIDENTIAL),
        ("webhook_url", Classification.CONFIDENTIAL),
        # restricted — PII
        ("user_ssn", Classification.RESTRICTED),
        ("national_id", Classification.RESTRICTED),
        ("RRN", Classification.RESTRICTED),
        ("resident_reg_number", Classification.RESTRICTED),
        ("passport_no", Classification.RESTRICTED),
        ("biometric_template", Classification.RESTRICTED),
        ("card_number", Classification.RESTRICTED),
        ("iban", Classification.RESTRICTED),
        ("account_number", Classification.RESTRICTED),
        # unknown sensitive-looking → default confidential, not restricted
        ("mystery_field", Classification.CONFIDENTIAL),
        ("", Classification.CONFIDENTIAL),
    ],
)
def test_infer_classification_by_name(name, expected):
    assert infer_classification(name).classification is expected


def test_infer_pii_flag():
    assert infer_classification("user_ssn").pii is True
    assert infer_classification("national_id").pii is True
    assert infer_classification("api_key").pii is False
    assert infer_classification("password").pii is False


def test_infer_restricted_takes_precedence_over_confidential():
    """A name like 'user_ssn_secret' contains both restricted and
    confidential markers — restricted (PII) must win so PII never falls
    through to the generic confidential bucket."""
    result = infer_classification("user_ssn_secret")
    assert result.classification is Classification.RESTRICTED
    assert result.pii is True


# --- AAD context builder --------------------------------------------------


def test_build_aad_context_required_fields():
    ctx = build_aad_context(
        config_path="oauth.google.client_secret",
        classification=Classification.CONFIDENTIAL,
    )
    assert ctx["config_path"] == "oauth.google.client_secret"
    assert ctx["classification"] == "confidential"
    assert ctx["tenant_id"] == ""
    assert ctx["written_at"] == ""


def test_build_aad_context_accepts_str_classification():
    ctx = build_aad_context(
        config_path="x.y", classification="restricted", tenant_id="org-abc"
    )
    assert ctx["classification"] == "restricted"
    assert ctx["tenant_id"] == "org-abc"


def test_build_aad_context_rejects_empty_path():
    with pytest.raises(ValueError):
        build_aad_context(config_path="", classification=Classification.CONFIDENTIAL)


def test_aad_serialize_is_canonical():
    """Two builds of the same logical context must produce byte-identical
    output. Otherwise GCM tag verification will fail across processes."""
    a = build_aad_context(
        config_path="x.y",
        classification=Classification.CONFIDENTIAL,
        tenant_id="org",
    )
    b = build_aad_context(
        classification="confidential",
        tenant_id="org",
        config_path="x.y",
    )
    assert aad_serialize(a) == aad_serialize(b)
    assert aad_hash(a) == aad_hash(b)


def test_aad_hash_changes_with_each_field():
    base = build_aad_context(
        config_path="oauth.google.client_secret",
        classification=Classification.CONFIDENTIAL,
        tenant_id="org-a",
    )
    base_hash = aad_hash(base)
    # tenant_id changes → hash changes
    h_other_tenant = aad_hash(
        build_aad_context(
            config_path="oauth.google.client_secret",
            classification=Classification.CONFIDENTIAL,
            tenant_id="org-b",
        )
    )
    assert h_other_tenant != base_hash
    # config_path changes → hash changes
    h_other_path = aad_hash(
        build_aad_context(
            config_path="oauth.microsoft.client_secret",
            classification=Classification.CONFIDENTIAL,
            tenant_id="org-a",
        )
    )
    assert h_other_path != base_hash
    # classification changes → hash changes
    h_other_class = aad_hash(
        build_aad_context(
            config_path="oauth.google.client_secret",
            classification=Classification.RESTRICTED,
            tenant_id="org-a",
        )
    )
    assert h_other_class != base_hash


def test_aad_serialize_no_whitespace():
    """Compact separators are required — adding whitespace breaks canonical
    form. Pin this so future refactors don't accidentally use json.dumps
    defaults."""
    ctx = build_aad_context(
        config_path="x.y", classification=Classification.CONFIDENTIAL
    )
    blob = aad_serialize(ctx)
    assert b" " not in blob
    assert b"\n" not in blob


# --- crypto API context kwargs -------------------------------------------


def test_encrypt_value_accepts_context():
    """Phase 1 callers (positional) keep working; Phase 2 callers can pass
    AAD context. Fernet provider ignores it but the kwarg must be accepted."""
    ctx = build_aad_context(
        config_path="oauth.google.client_secret",
        classification=Classification.CONFIDENTIAL,
    )
    ct = crypto.encrypt_value("hunter2", context=ctx)
    assert ct.startswith("kms:fernet:fernet:v1:")
    assert crypto.decrypt_value(ct, context=ctx) == "hunter2"


def test_encrypt_value_ignores_context_in_phase_2_fernet():
    """Until Phase 3 envelope arrives, Fernet does not bind context — so
    decrypting with a *different* context still works. This documents the
    Phase-2 limitation; the test should be flipped to xfail/strengthened
    once an AEAD provider is the default."""
    ct = crypto.encrypt_value(
        "v",
        context=build_aad_context(
            config_path="a.b", classification=Classification.CONFIDENTIAL
        ),
    )
    decoded = crypto.decrypt_value(
        ct,
        context=build_aad_context(
            config_path="completely.different",
            classification=Classification.RESTRICTED,
        ),
    )
    assert decoded == "v"


def test_encrypt_value_back_compat_no_context():
    """Existing call sites that don't pass context must keep working."""
    ct = crypto.encrypt_value("plain-old-call")
    assert crypto.decrypt_value(ct) == "plain-old-call"


# --- PersistentConfig integration ----------------------------------------


def test_persistent_config_accepts_phase2_fields():
    """The new keyword-only fields must not break existing PersistentConfig
    instantiation. Defaults preserve Phase 1 behavior."""
    from open_webui.config import PersistentConfig

    item = PersistentConfig(
        env_name="UNIT_TEST_FIELD",
        config_path="unit.test.field",
        env_value="default",
        sensitive=True,
        classification="restricted",
        pii=True,
        retention_days=30,
        local_only=True,
    )
    assert item.classification == "restricted"
    assert item.pii is True
    assert item.retention_days == 30
    assert item.local_only is True


def test_persistent_config_defaults_match_phase1():
    from open_webui.config import PersistentConfig

    item = PersistentConfig(
        env_name="UNIT_TEST_PLAIN",
        config_path="unit.test.plain",
        env_value="x",
    )
    assert item.classification is None  # → infer at lookup time
    assert item.pii is None
    assert item.retention_days is None
    assert item.local_only is False


def test_get_path_meta_falls_back_to_inference():
    """Paths that aren't registered as PersistentConfig must still get
    sensible metadata via name-based inference — used by code paths like
    DbSphere connection passwords stored under nested config blobs."""
    from open_webui.config import get_path_meta

    meta = get_path_meta("dbsphere.connections[0].password")
    assert meta["classification"] is Classification.CONFIDENTIAL
    assert meta["pii"] is False
    assert meta["local_only"] is False

    meta_pii = get_path_meta("user_profile.national_id")
    assert meta_pii["classification"] is Classification.RESTRICTED
    assert meta_pii["pii"] is True


def test_get_sensitive_paths_with_meta_returns_classification():
    """Spot-check that registered sensitive PersistentConfig entries appear
    with classification metadata. The exact paths depend on the live registry,
    but at least one entry should exist by the time tests run."""
    from open_webui.config import get_sensitive_paths_with_meta

    paths = get_sensitive_paths_with_meta()
    assert isinstance(paths, dict)
    if paths:  # registry populated by other test imports
        sample_meta = next(iter(paths.values()))
        assert "classification" in sample_meta
        assert isinstance(sample_meta["classification"], Classification)
        assert "pii" in sample_meta
        assert "local_only" in sample_meta
