"""KMS Phase 1 — provider/router/tag plumbing tests.

These tests exercise the abstraction layer introduced in
`backend/open_webui/utils/kms/` and the thin wrapper in
`backend/open_webui/utils/crypto.py`. They guard backward compatibility
with legacy untagged `gAAAAA...` Fernet ciphertexts and pin down the
tag format so future providers (Azure KV, AWS KMS, ...) can plug in
without breaking existing data.

Backstory: Cloosphere previously stored sensitive PersistentConfig
values as untagged Fernet ciphertexts derived from WEBUI_SECRET_KEY.
Phase 1 wraps that in a `KMSProvider` ABC and a tag-dispatching
`KMSRouter` so deployments can later swap to managed KMS without a
data migration.
"""

import base64
import hashlib
import os

import pytest
from cryptography.fernet import Fernet

# Ensure WEBUI_SECRET_KEY is set before any open_webui imports — the env
# module reads it at import time.
os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-phase1")

from open_webui.utils import crypto
from open_webui.utils.kms import get_router
from open_webui.utils.kms.base import (
    LEGACY_FERNET_PREFIX,
    TAG_VERSION,
    KMSProvider,
    build_tag,
    is_legacy_fernet,
    is_tagged,
    parse_tag,
)
from open_webui.utils.kms.fernet import FernetProvider
from open_webui.utils.kms.router import reset_router_for_tests


@pytest.fixture(autouse=True)
def _reset_router(monkeypatch):
    """Each test gets a fresh router singleton — provider state is in-process.

    Pin KMS_PROVIDER to "fernet" so the test environment is independent of
    whatever `.env` happens to have configured. Tests that want to exercise
    a different provider override KMS_PROVIDER themselves.
    """
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


# --- tag format -----------------------------------------------------------


def test_build_tag_round_trips():
    tag = build_tag("fernet", "fernet", "payload-here")
    assert tag == f"kms:fernet:fernet:{TAG_VERSION}:payload-here"

    parsed = parse_tag(tag)
    assert parsed is not None
    assert parsed.provider == "fernet"
    assert parsed.algo == "fernet"
    assert parsed.version == TAG_VERSION
    assert parsed.payload == "payload-here"


def test_parse_tag_accepts_colons_in_payload():
    """Envelope provider payloads will contain ':' (wrapped_dek:nonce:ct etc.).

    parse_tag must split exactly 4 times so the payload stays intact.
    """
    tag = build_tag("azkv-env", "aes256gcm", "wrapped:nonce:aad:ct")
    parsed = parse_tag(tag)
    assert parsed is not None
    assert parsed.payload == "wrapped:nonce:aad:ct"


def test_parse_tag_rejects_non_kms_prefix():
    assert parse_tag("plaintext") is None
    assert parse_tag("gAAAAA-legacy-fernet") is None
    assert parse_tag("") is None


def test_parse_tag_rejects_truncated():
    assert parse_tag("kms:fernet") is None
    assert parse_tag("kms:fernet:fernet") is None
    assert parse_tag("kms:fernet:fernet:v1") is None  # missing payload separator


def test_is_tagged_and_is_legacy_fernet():
    assert is_tagged("kms:fernet:fernet:v1:abc")
    assert not is_tagged("gAAAAAxyz")
    assert not is_tagged("plain")

    assert is_legacy_fernet("gAAAAAxyz")
    assert not is_legacy_fernet("kms:fernet:fernet:v1:gAAAAA")
    assert not is_legacy_fernet("plain")


# --- FernetProvider -------------------------------------------------------


def test_fernet_provider_round_trip():
    provider = FernetProvider()
    ciphertext = provider.encrypt("hello")
    assert ciphertext.startswith(provider.tag_prefix)
    assert provider.decrypt(ciphertext) == "hello"


def test_fernet_provider_decrypts_legacy_untagged():
    """The pre-Phase-1 ciphertext format must keep working forever — there
    are existing deployments with `gAAAAA...` values in the Config table."""
    provider = FernetProvider()
    # Reproduce legacy crypto._get_fernet_key derivation
    key = base64.urlsafe_b64encode(
        hashlib.sha256(os.environ["WEBUI_SECRET_KEY"].encode()).digest()
    )
    legacy = Fernet(key).encrypt(b"legacy-value").decode()
    assert legacy.startswith(LEGACY_FERNET_PREFIX)

    assert provider.decrypt(legacy) == "legacy-value"


def test_fernet_provider_rejects_other_provider_tag():
    """FernetProvider.decrypt() should not silently process azkv tags."""
    provider = FernetProvider()
    with pytest.raises(ValueError):
        provider.decrypt("kms:azkv-env:aes256gcm:v1:not-fernet")


def test_fernet_provider_empty_input():
    provider = FernetProvider()
    assert provider.encrypt("") == ""
    assert provider.decrypt("") == ""


def test_fernet_tag_prefix_matches_emitted_value():
    """Critical invariant — KMSRouter dispatches by exact prefix match,
    so the provider's claimed tag_prefix must equal the prefix it emits."""
    provider = FernetProvider()
    ciphertext = provider.encrypt("anything")
    parsed = parse_tag(ciphertext)
    assert parsed is not None
    assert provider.tag_prefix == parsed.prefix


# --- KMSRouter ------------------------------------------------------------


def test_router_singleton():
    assert get_router() is get_router()


def test_router_round_trip_via_default_provider():
    router = get_router()
    ct = router.encrypt("hunter2")
    assert is_tagged(ct)
    assert router.decrypt(ct) == "hunter2"


def test_router_decrypts_legacy_untagged():
    """Even after switching the default provider in a future phase, legacy
    untagged ciphertexts keep decrypting through the FernetProvider fallback."""
    router = get_router()
    key = base64.urlsafe_b64encode(
        hashlib.sha256(os.environ["WEBUI_SECRET_KEY"].encode()).digest()
    )
    legacy = Fernet(key).encrypt(b"old-value").decode()
    assert router.decrypt(legacy) == "old-value"


def test_router_passes_plaintext_through_on_decrypt():
    """Matches the legacy `_decrypt_config_data` behavior — plaintext values
    in the JSON blob (not yet encrypted at all) must round-trip unchanged."""
    router = get_router()
    assert router.decrypt("not-encrypted") == "not-encrypted"
    assert router.decrypt("") == ""


def test_router_rejects_unknown_provider_tag():
    """Tagged value with a provider we don't have registered — fail loudly
    rather than silently returning ciphertext."""
    router = get_router()
    with pytest.raises(ValueError, match="No KMS provider"):
        router.decrypt("kms:azkv-env:aes256gcm:v1:opaque-payload")


def test_router_add_provider_dispatch():
    """A second provider with a distinct tag_prefix is dispatched correctly."""

    class _StubProvider(KMSProvider):
        name = "stub"
        algo = "noop"

        def encrypt(self, plaintext, context=None):
            return build_tag(self.name, self.algo, plaintext)

        def decrypt(self, tagged_or_legacy, context=None):
            parsed = parse_tag(tagged_or_legacy)
            assert parsed is not None
            return parsed.payload

    router = get_router()
    stub = _StubProvider()
    router.add_provider(stub)

    # Default provider still Fernet
    fernet_ct = router.encrypt("default-path")
    assert router.decrypt(fernet_ct) == "default-path"

    # Stub provider's tag dispatches to stub
    stub_ct = stub.encrypt("stub-path")
    assert router.decrypt(stub_ct) == "stub-path"


def test_router_is_encrypted_recognizes_both():
    router = get_router()
    tagged = router.encrypt("v")
    key = base64.urlsafe_b64encode(
        hashlib.sha256(os.environ["WEBUI_SECRET_KEY"].encode()).digest()
    )
    legacy = Fernet(key).encrypt(b"v").decode()

    assert router.is_encrypted(tagged)
    assert router.is_encrypted(legacy)
    assert not router.is_encrypted("plaintext")
    assert not router.is_encrypted("")


# --- crypto.py thin wrapper -----------------------------------------------


def test_crypto_module_round_trip():
    ct = crypto.encrypt_value("api-key-xyz")
    assert is_tagged(ct)
    assert crypto.is_encrypted(ct)
    assert crypto.decrypt_value(ct) == "api-key-xyz"


def test_crypto_module_handles_legacy_data():
    """config.py and dbsphere.py have stored `gAAAAA...` values — they must
    keep decrypting through the unchanged crypto.decrypt_value() signature."""
    key = base64.urlsafe_b64encode(
        hashlib.sha256(os.environ["WEBUI_SECRET_KEY"].encode()).digest()
    )
    legacy = Fernet(key).encrypt(b"db-password").decode()

    assert crypto.is_encrypted(legacy)
    assert crypto.decrypt_value(legacy) == "db-password"


def test_crypto_module_empty_inputs():
    assert crypto.encrypt_value("") == ""
    assert crypto.decrypt_value("") == ""
    assert not crypto.is_encrypted("")


def test_crypto_module_plaintext_passthrough_on_decrypt():
    """config._decrypt_config_data relied on plaintext values surviving an
    accidental decrypt_value() call. The wrapper must preserve that."""
    assert crypto.decrypt_value("not-encrypted") == "not-encrypted"
