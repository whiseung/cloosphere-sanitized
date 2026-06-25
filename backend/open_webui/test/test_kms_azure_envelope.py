"""KMS Phase 3 — Azure Key Vault envelope provider tests.

These tests do not contact a real Azure Key Vault — the
``CryptographyClient`` is replaced with a fake that wraps/unwraps DEKs
in-memory. The fake is bit-faithful enough to exercise:

  - tag format invariants (5 pipe-delimited segments inside the payload)
  - AES-256-GCM AAD binding (decrypt with mismatched context fails)
  - DEK cache (unwrap is called once even when the same value is
    decrypted multiple times)
  - KEK rotation handling — embedded key_id mismatch logs a warning but
    still proceeds (production KV would still unwrap as long as the
    key version is enabled)
  - router auto-selection when ``KMS_PROVIDER=azkv-env`` is configured

Phase 2 left ``test_encrypt_value_ignores_context_in_phase_2_fernet``
as a documented limitation. The corresponding Phase 3 test below flips
that to active enforcement: AAD binding under the envelope provider
must reject a context swap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-phase3")

from open_webui.utils.kms import (
    Classification,
    build_aad_context,
    parse_tag,
)
from open_webui.utils.kms.azure_key_vault import (
    PAYLOAD_SEPARATOR,
    AzureKeyVaultEnvelopeProvider,
    CryptoClientFactory,
    _DekCache,
)
from open_webui.utils.kms.router import (
    KMSRouter,
    get_router,
    reset_router_for_tests,
)

# --- Fake KV CryptographyClient -------------------------------------------


@dataclass
class _WrappedResult:
    encrypted_key: bytes


@dataclass
class _UnwrappedResult:
    key: bytes


class _FakeCryptoClient:
    """In-memory stand-in for azure.keyvault.keys.crypto.CryptographyClient.

    "Wrap" simply XORs the DEK with a fixed pseudo-KEK so we can verify
    the unwrap path without bringing a real Azure dependency into the
    test. Counts wrap/unwrap calls so cache tests can assert KV
    round-trip behavior.
    """

    def __init__(self, kek_bytes: bytes = b"\xa5" * 32) -> None:
        self._kek = kek_bytes
        self.wrap_calls = 0
        self.unwrap_calls = 0

    def wrap_key(self, algorithm, key: bytes) -> _WrappedResult:
        self.wrap_calls += 1
        return _WrappedResult(
            encrypted_key=bytes(b ^ k for b, k in zip(key, self._kek))
        )

    def unwrap_key(self, algorithm, encrypted_key: bytes) -> _UnwrappedResult:
        self.unwrap_calls += 1
        return _UnwrappedResult(
            key=bytes(b ^ k for b, k in zip(encrypted_key, self._kek))
        )


class _FakeFactory(CryptoClientFactory):
    def __init__(self, key_id: str, client: _FakeCryptoClient):
        self.key_id = key_id
        self._credential = None
        self._injected = client
        # Per-key_id stand-ins so the rotation tests can verify each KEK's
        # client is queried separately. The factory falls back to the
        # injected client whenever the requested key_id matches self.key_id.
        self._aux_clients: dict[str, _FakeCryptoClient] = {}

    def get(self):
        return self._injected

    def get_for(self, key_id: str):
        if not key_id or key_id == self.key_id:
            return self._injected
        cached = self._aux_clients.get(key_id)
        if cached is None:
            # Different KEK byte-pattern so wrap/unwrap under one KEK never
            # accidentally unwraps under another.
            kek_byte = (sum(ord(c) for c in key_id) % 251) | 0x01
            cached = _FakeCryptoClient(kek_bytes=bytes([kek_byte]) * 32)
            self._aux_clients[key_id] = cached
        return cached

    def register_prior_kek(self, key_id: str, client: _FakeCryptoClient) -> None:
        """Test helper — pre-seed a specific client for a given key_id so
        a test can wrap under one KEK then assert unwrap routes to that
        same client even after the factory's primary key_id changes."""
        self._aux_clients[key_id] = client


# --- fixtures -------------------------------------------------------------


KEY_ID = "https://test-vault.vault.azure.net/keys/cloosphere-kek/abcv1"


@pytest.fixture
def fake_client():
    return _FakeCryptoClient()


@pytest.fixture
def provider(fake_client):
    return AzureKeyVaultEnvelopeProvider(
        key_id=KEY_ID,
        crypto_client_factory=_FakeFactory(KEY_ID, fake_client),
    )


@pytest.fixture
def context():
    return build_aad_context(
        config_path="oauth.google.client_secret",
        classification=Classification.CONFIDENTIAL,
        tenant_id="org-a",
    )


@pytest.fixture(autouse=True)
def _reset_router():
    reset_router_for_tests()
    yield
    reset_router_for_tests()


# --- core round-trip ------------------------------------------------------


def test_envelope_round_trip(provider, context):
    ct = provider.encrypt("hunter2", context=context)
    assert ct.startswith(provider.tag_prefix)
    assert provider.decrypt(ct, context=context) == "hunter2"


def test_envelope_tag_format(provider, context):
    ct = provider.encrypt("v", context=context)
    parsed = parse_tag(ct)
    assert parsed is not None
    assert parsed.provider == "azkv-env"
    assert parsed.algo == "aes256gcm"
    assert parsed.version == "v1"
    # Payload has exactly 5 pipe-separated b64u/hex fields.
    parts = parsed.payload.split(PAYLOAD_SEPARATOR)
    assert len(parts) == 5, parts


def test_envelope_handles_empty_input(provider):
    assert provider.encrypt("") == ""
    assert provider.decrypt("") == ""


def test_envelope_decrypt_rejects_non_envelope_tag(provider):
    with pytest.raises(ValueError):
        provider.decrypt("kms:fernet:fernet:v1:gAAAAAxyz")


def test_envelope_decrypt_rejects_malformed_payload(provider):
    # Build a tag with the right prefix but a single-segment payload.
    bad = provider.tag_prefix + "only-one-segment"
    with pytest.raises(ValueError, match="Malformed envelope"):
        provider.decrypt(bad)


# --- AAD binding ----------------------------------------------------------


def test_envelope_aad_binding_rejects_swapped_context(provider, context):
    """The Phase-2 limitation (Fernet ignored context) must NOT exist
    under the envelope provider. Decrypting under a different AAD must
    fail, not silently return the value."""
    ct = provider.encrypt("private", context=context)

    other_context = build_aad_context(
        config_path="oauth.microsoft.client_secret",  # different path
        classification=Classification.CONFIDENTIAL,
        tenant_id="org-b",  # different tenant
    )
    with pytest.raises(ValueError):
        provider.decrypt(ct, context=other_context)


def test_envelope_aad_binding_rejects_missing_context(provider, context):
    """If the value was written under a context, decrypting without one
    must fail — would otherwise let an attacker bypass binding by simply
    omitting the kwarg."""
    ct = provider.encrypt("v", context=context)

    # Decrypt with no context — the cipher was bound with AAD bytes
    # so AESGCM tag check fails. Provider raises ValueError.
    with pytest.raises(ValueError):
        provider.decrypt(ct)


def test_envelope_works_without_context_when_written_without(provider):
    ct = provider.encrypt("v")
    assert provider.decrypt(ct) == "v"


def test_envelope_aad_pre_check_avoids_kv_call(provider, context, fake_client):
    """When the AAD hash mismatch is obvious (caller passed a different
    context), the provider must reject before calling unwrap_key — saves
    KV round-trips and audit-log noise on misuse."""
    ct = provider.encrypt("v", context=context)

    bad_context = build_aad_context(
        config_path="x.y", classification=Classification.RESTRICTED
    )
    unwrap_before = fake_client.unwrap_calls
    with pytest.raises(ValueError, match="AAD context mismatch"):
        provider.decrypt(ct, context=bad_context)
    assert fake_client.unwrap_calls == unwrap_before


# --- DEK cache ------------------------------------------------------------


def test_envelope_dek_cache_hits_on_repeat_decrypt(provider, context, fake_client):
    """Decrypting the same ciphertext twice must hit the in-process
    cache for the second call (one unwrap KV round-trip total)."""
    ct = provider.encrypt("repeat", context=context)
    # Encryption itself populates the cache, so even the *first* decrypt
    # is a cache hit. The contract we want is: across N decrypts of the
    # same wrapped DEK there is at most one unwrap call.
    unwrap_before = fake_client.unwrap_calls
    for _ in range(5):
        assert provider.decrypt(ct, context=context) == "repeat"
    assert fake_client.unwrap_calls - unwrap_before == 0  # served from cache


def test_envelope_dek_cache_independent_per_value(provider, context, fake_client):
    """Distinct values use distinct DEKs (security property — DEK reuse
    would leak structure under GCM). Each encrypt → fresh DEK → fresh
    wrap call."""
    a = provider.encrypt("a", context=context)
    b = provider.encrypt("b", context=context)
    assert a != b
    # DEKs are fresh per-message → wrap_key called twice
    assert fake_client.wrap_calls >= 2


def test_envelope_dek_cache_ttl_expiry():
    """Cached DEKs expire after their TTL. Pin the contract so an
    eventual key-revocation flow can rely on it (set TTL=0 to flush)."""
    cache = _DekCache(ttl_secs=0, capacity=4)
    cache.put(b"wrapped", b"dek-bytes-32-aaaaaaaaaaaaaaaaaaaa")
    assert cache.get(b"wrapped") is None  # already expired


def test_envelope_dek_cache_capacity_evicts_oldest():
    cache = _DekCache(ttl_secs=600, capacity=2)
    cache.put(b"a", b"x" * 32)
    cache.put(b"b", b"y" * 32)
    cache.put(b"c", b"z" * 32)
    # one of the older entries must have been evicted to fit "c"
    assert cache.get(b"c") is not None
    assert sum(1 for k in (b"a", b"b") if cache.get(k) is not None) <= 1


# --- KEK identity / rotation ---------------------------------------------


def test_envelope_unwraps_under_prior_kek_after_rotation(context):
    """Phase 4.3 — KEK rotation invariant.

    Sequence:
      1. Wrap a value under KEK_A.
      2. Reconfigure the provider so its primary key_id is KEK_B (as if
         an admin just ran ``/configs/kms/rotate``).
      3. Decrypt the KEK_A-tagged ciphertext.

    The unwrap path must route the request to KEK_A's client (looked up
    via ``factory.get_for``), not to the now-current KEK_B client —
    otherwise every historic envelope would become un-decryptable the
    moment rotation lands.
    """
    KEK_A = "https://test-vault.vault.azure.net/keys/cloosphere-kek/version-A"
    KEK_B = "https://test-vault.vault.azure.net/keys/cloosphere-kek/version-B"

    client_a = _FakeCryptoClient(kek_bytes=b"\xa5" * 32)
    client_b = _FakeCryptoClient(kek_bytes=b"\x5a" * 32)

    # Step 1: provider on KEK_A — wrap a value.
    factory_a = _FakeFactory(KEK_A, client_a)
    provider_a = AzureKeyVaultEnvelopeProvider(
        key_id=KEK_A, crypto_client_factory=factory_a
    )
    ct = provider_a.encrypt("rotate-me", context=context)
    assert client_a.wrap_calls == 1

    # Step 2: rotation — new provider on KEK_B with KEK_A registered as
    # a prior KEK so the factory can unwrap historic ciphertexts.
    factory_b = _FakeFactory(KEK_B, client_b)
    factory_b.register_prior_kek(KEK_A, client_a)
    # Force a fresh DEK cache — production rotation rebuilds the router
    # so the in-memory unwrap cache is naturally cleared.
    provider_b = AzureKeyVaultEnvelopeProvider(
        key_id=KEK_B, crypto_client_factory=factory_b
    )

    # Step 3: decrypt the KEK_A-tagged ciphertext after rotation.
    plain = provider_b.decrypt(ct, context=context)
    assert plain == "rotate-me"
    # Routing assertion — the unwrap must have hit KEK_A's client, NOT
    # KEK_B's (which would corrupt the DEK because the fake KEKs differ).
    assert client_a.unwrap_calls == 1
    assert client_b.unwrap_calls == 0


def test_envelope_unwrap_caches_aux_client_per_key_id():
    """Repeated decrypt of ciphertexts under the same prior KEK must
    reuse a single CryptographyClient — we don't want to rebuild a KV
    client on every unwrap when many envelopes share the same legacy
    KEK URI."""
    KEK_PRIOR = "https://test-vault.vault.azure.net/keys/cloosphere-kek/v-prior"
    KEK_NEW = "https://test-vault.vault.azure.net/keys/cloosphere-kek/v-new"

    prior_client = _FakeCryptoClient(kek_bytes=b"\x11" * 32)
    new_client = _FakeCryptoClient(kek_bytes=b"\x22" * 32)

    factory_prior = _FakeFactory(KEK_PRIOR, prior_client)
    provider_prior = AzureKeyVaultEnvelopeProvider(
        key_id=KEK_PRIOR, crypto_client_factory=factory_prior
    )
    ct1 = provider_prior.encrypt("a")
    ct2 = provider_prior.encrypt("b")

    # Now rotate.
    factory_new = _FakeFactory(KEK_NEW, new_client)
    factory_new.register_prior_kek(KEK_PRIOR, prior_client)
    provider_new = AzureKeyVaultEnvelopeProvider(
        key_id=KEK_NEW, crypto_client_factory=factory_new
    )
    assert provider_new.decrypt(ct1) == "a"
    assert provider_new.decrypt(ct2) == "b"
    # Both unwraps must have routed to the prior KEK's client.
    assert prior_client.unwrap_calls == 2
    assert new_client.unwrap_calls == 0


def test_envelope_health_check_calls_wrap_key(provider, fake_client):
    ok, detail = provider.health_check()
    assert ok is True
    assert "azkv-env: ok" in detail
    assert fake_client.wrap_calls >= 1


# --- Phase 4.4: per-classification KEK separation ------------------------


def _build_dual_tier_provider():
    """Helper: provider with both default + restricted KEKs configured.

    Returns ``(provider, default_client, restricted_client)`` so tests can
    assert which tier handled a given wrap/unwrap.
    """
    KEK_DEFAULT = "https://test-vault.vault.azure.net/keys/default-kek/v1"
    KEK_RESTRICTED = "https://test-vault.vault.azure.net/keys/restricted-kek/v1"

    default_client = _FakeCryptoClient(kek_bytes=b"\x10" * 32)
    restricted_client = _FakeCryptoClient(kek_bytes=b"\x20" * 32)

    default_factory = _FakeFactory(KEK_DEFAULT, default_client)
    restricted_factory = _FakeFactory(KEK_RESTRICTED, restricted_client)

    provider = AzureKeyVaultEnvelopeProvider(
        key_id=KEK_DEFAULT,
        crypto_client_factory=default_factory,
        restricted_key_id=KEK_RESTRICTED,
        restricted_crypto_client_factory=restricted_factory,
    )
    return provider, default_client, restricted_client, KEK_DEFAULT, KEK_RESTRICTED


def test_dual_tier_routes_confidential_to_default():
    """Phase 4.4 — Confidential classification → default KEK."""
    provider, default_client, restricted_client, KEK_DEFAULT, _ = (
        _build_dual_tier_provider()
    )
    ctx = build_aad_context(
        config_path="oauth.google.client_secret",
        classification=Classification.CONFIDENTIAL,
        tenant_id="org-a",
    )
    ct = provider.encrypt("secret", context=ctx)
    # The tag must embed the default KEK URI, NOT the restricted one.
    parsed = parse_tag(ct)
    payload_parts = parsed.payload.split(PAYLOAD_SEPARATOR)
    embedded_kek_b64 = payload_parts[0]
    import base64

    pad = "=" * (-len(embedded_kek_b64) % 4)
    embedded_kek = base64.urlsafe_b64decode(embedded_kek_b64 + pad).decode("utf-8")
    assert embedded_kek == KEK_DEFAULT
    assert default_client.wrap_calls == 1
    assert restricted_client.wrap_calls == 0
    # Round-trip works.
    assert provider.decrypt(ct, context=ctx) == "secret"


def test_dual_tier_routes_restricted_to_restricted_kek():
    """Phase 4.4 — Restricted (PII) classification → restricted KEK."""
    provider, default_client, restricted_client, _, KEK_RESTRICTED = (
        _build_dual_tier_provider()
    )
    ctx = build_aad_context(
        config_path="user.ssn",
        classification=Classification.RESTRICTED,
        tenant_id="org-a",
    )
    ct = provider.encrypt("123-45-6789", context=ctx)
    parsed = parse_tag(ct)
    embedded_kek_b64 = parsed.payload.split(PAYLOAD_SEPARATOR)[0]
    import base64

    pad = "=" * (-len(embedded_kek_b64) % 4)
    embedded_kek = base64.urlsafe_b64decode(embedded_kek_b64 + pad).decode("utf-8")
    assert embedded_kek == KEK_RESTRICTED
    # Default tier KEK never touched the wrap.
    assert default_client.wrap_calls == 0
    assert restricted_client.wrap_calls == 1
    # Decrypt routes to the restricted client (NOT the default), even though
    # the provider's primary key_id is the default — the unwrap path keys
    # off the embedded URI. Invalidate the in-process DEK cache first to
    # force a real unwrap call (encrypt populates the cache as a hot-path
    # optimization).
    provider._cache.invalidate()
    assert provider.decrypt(ct, context=ctx) == "123-45-6789"
    assert default_client.unwrap_calls == 0
    assert restricted_client.unwrap_calls == 1


def test_single_tier_provider_ignores_classification():
    """When ``restricted_key_id`` is unset, every classification wraps
    under the default KEK — same behavior as before Phase 4.4."""
    KEK = "https://test-vault.vault.azure.net/keys/k/v"
    client = _FakeCryptoClient()
    factory = _FakeFactory(KEK, client)
    provider = AzureKeyVaultEnvelopeProvider(
        key_id=KEK,
        crypto_client_factory=factory,  # no restricted_key_id
    )
    ctx_pii = build_aad_context(
        config_path="user.ssn",
        classification=Classification.RESTRICTED,
        tenant_id="org-a",
    )
    ct = provider.encrypt("data", context=ctx_pii)
    # Tag's embedded KEK must be the default — fallback when no restricted
    # KEK is configured.
    parsed = parse_tag(ct)
    embedded_kek_b64 = parsed.payload.split(PAYLOAD_SEPARATOR)[0]
    import base64

    pad = "=" * (-len(embedded_kek_b64) % 4)
    embedded_kek = base64.urlsafe_b64decode(embedded_kek_b64 + pad).decode("utf-8")
    assert embedded_kek == KEK
    # Verify there's no second factory.
    assert provider.restricted_key_id is None


def test_dual_tier_health_check_probes_both():
    """Phase 4.4 — health_check must wrap a throwaway DEK on BOTH KEKs
    so the admin gets a single combined OK/FAIL signal."""
    provider, default_client, restricted_client, _, _ = _build_dual_tier_provider()
    ok, detail = provider.health_check()
    assert ok is True
    assert default_client.wrap_calls == 1
    assert restricted_client.wrap_calls == 1
    assert "default=" in detail and "restricted=" in detail


def test_dual_tier_health_check_fails_if_restricted_unreachable():
    """If the Restricted KEK can't wrap (RBAC missing, network), the
    overall health_check must FAIL even though the default tier is OK —
    otherwise the admin won't notice that PII writes will throw."""
    KEK_DEFAULT = "https://test-vault.vault.azure.net/keys/default-kek/v1"
    KEK_RESTRICTED = "https://test-vault.vault.azure.net/keys/restricted-kek/v1"

    default_client = _FakeCryptoClient()

    class _BrokenClient:
        wrap_calls = 0
        unwrap_calls = 0

        def wrap_key(self, *_a, **_kw):
            raise RuntimeError("ForbiddenByRbac (simulated)")

        def unwrap_key(self, *_a, **_kw):
            raise RuntimeError("unreachable")

    provider = AzureKeyVaultEnvelopeProvider(
        key_id=KEK_DEFAULT,
        crypto_client_factory=_FakeFactory(KEK_DEFAULT, default_client),
        restricted_key_id=KEK_RESTRICTED,
        restricted_crypto_client_factory=_FakeFactory(KEK_RESTRICTED, _BrokenClient()),
    )
    ok, detail = provider.health_check()
    assert ok is False
    assert "restricted" in detail
    # Default tier was probed first and succeeded — only the restricted
    # tier contributed the failure signal.
    assert default_client.wrap_calls == 1


# --- Router integration --------------------------------------------------


def test_router_routes_envelope_tags_when_provider_registered(provider, context):
    """A real router instance with the envelope provider added should
    decrypt envelope tags AND still decrypt legacy Fernet tags via the
    fallback. This is the steady-state Phase-3 deployment shape."""
    from open_webui.utils.kms.fernet import FernetProvider

    fernet = FernetProvider()
    router = KMSRouter(default=provider, fernet_fallback=fernet)
    router.add_provider(provider)

    envelope_ct = router.encrypt("e", context=context)
    assert envelope_ct.startswith("kms:azkv-env:aes256gcm:v1:")
    assert router.decrypt(envelope_ct, context=context) == "e"

    # Round-trip a legacy Fernet ciphertext through the same router.
    legacy_ct = fernet.encrypt("legacy")
    assert router.decrypt(legacy_ct) == "legacy"


def _patch_kms_config(monkeypatch, *, provider: str, key_uri: str = "") -> None:
    """Set KMS_PROVIDER and KMS_AZURE_KEY_VAULT_KEY_URI on the config
    module to simulate a deployment with those env-driven settings.

    The router reads the PersistentConfig instances directly (not via
    get_config_value) so that env-only deployments — where the value
    has not yet been written to the Config table — also pick up the
    intended provider."""
    import open_webui.config as cfg

    class _H:
        def __init__(self, value: str = "") -> None:
            self.value = value

    monkeypatch.setattr(cfg, "KMS_PROVIDER", _H(provider), raising=False)
    monkeypatch.setattr(cfg, "KMS_AZURE_KEY_VAULT_KEY_URI", _H(key_uri), raising=False)


def test_get_router_falls_back_to_fernet_when_azkv_misconfigured(monkeypatch):
    """KMS_PROVIDER=azkv-env without a key URI must NOT crash startup —
    log + stay on Fernet so the deployment keeps working."""
    _patch_kms_config(monkeypatch, provider="azkv-env", key_uri="")

    router = get_router()
    # Encrypt should still work (via Fernet fallback)
    ct = router.encrypt("alive")
    assert ct.startswith("kms:fernet:fernet:v1:")
    assert router.decrypt(ct) == "alive"


def test_get_router_attaches_envelope_when_configured(monkeypatch):
    """Happy path — KMS_PROVIDER=azkv-env with a key URI swaps the
    default provider. Existing legacy/Fernet ciphertexts still decrypt."""
    import open_webui.utils.kms.router as router_mod
    from open_webui.utils.kms.fernet import FernetProvider

    _patch_kms_config(monkeypatch, provider="azkv-env", key_uri=KEY_ID)

    # Stub _build_provider so we don't actually try to talk to Azure
    # — equivalent to dependency injection at the seam tests can reach.
    fake_client = _FakeCryptoClient()
    monkeypatch.setattr(
        router_mod,
        "_build_provider",
        lambda name: AzureKeyVaultEnvelopeProvider(
            key_id=KEY_ID,
            crypto_client_factory=_FakeFactory(KEY_ID, fake_client),
        ),
    )

    router = get_router()
    assert router.default_provider.name == "azkv-env"

    # New writes use envelope
    ctx = build_aad_context(
        config_path="x.y", classification=Classification.CONFIDENTIAL
    )
    ct = router.encrypt("env", context=ctx)
    assert ct.startswith("kms:azkv-env:aes256gcm:v1:")
    assert router.decrypt(ct, context=ctx) == "env"

    # Legacy Fernet still readable
    legacy = FernetProvider().encrypt("legacy")
    assert router.decrypt(legacy) == "legacy"


# --- Phase 2 follow-up: flip the documented limitation -------------------


def test_phase2_context_ignored_invariant_flips_under_envelope(provider, context):
    """In Phase 2 we documented (and tested) that Fernet ignores AAD
    context. Phase 3 envelope provider must enforce it — same logical
    test, opposite assertion."""
    ct = provider.encrypt("v", context=context)
    other = build_aad_context(
        config_path="completely.different",
        classification=Classification.RESTRICTED,
    )
    with pytest.raises(ValueError):
        provider.decrypt(ct, context=other)
