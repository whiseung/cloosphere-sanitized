"""Phase 3.5 — model-layer column encryption tests.

Phase 3 wired KMS at the Config / DbSphere layer. Phase 3.5 extends it to:
  - tool_connections.data.connection.key (model helpers)
  - cloocus_admin token columns (transparent ``EncryptedText`` TypeDecorator)

These tests don't bring up a real DB — they exercise the small pure-Python
helpers that decide what gets encrypted, what stays plaintext, and how
legacy rows behave on first read.
"""

import os

import pytest

os.environ.setdefault("WEBUI_SECRET_KEY", "test-secret-key-for-kms-phase35")

from open_webui.utils.kms.router import reset_router_for_tests


@pytest.fixture(autouse=True)
def _reset_router(monkeypatch):
    """Pin KMS_PROVIDER=fernet so tests don't try to talk to a real KV
    even if the operator's .env points at azkv-env."""
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


# --- tool_connections model helpers ---------------------------------------


def test_tool_connection_encrypt_round_trip():
    from open_webui.models.tool_connections import (
        _decrypt_data_in_place,
        _encrypt_data_in_place,
    )

    data = {"connection": {"type": "mcp", "url": "https://x", "key": "secret-tok-abc"}}
    encrypted = _encrypt_data_in_place({**data, "connection": dict(data["connection"])})
    # Sibling fields untouched
    assert encrypted["connection"]["url"] == "https://x"
    assert encrypted["connection"]["type"] == "mcp"
    # The sensitive field carries a kms: tag
    assert encrypted["connection"]["key"].startswith("kms:")

    decrypted = _decrypt_data_in_place(
        {**encrypted, "connection": dict(encrypted["connection"])}
    )
    assert decrypted["connection"]["key"] == "secret-tok-abc"


def test_tool_connection_encrypt_idempotent():
    """Encrypting an already-encrypted payload must not double-wrap —
    re-saving an unchanged row would otherwise grow the ciphertext on
    every flush."""
    from open_webui.models.tool_connections import _encrypt_data_in_place

    once = _encrypt_data_in_place({"connection": {"key": "value"}})
    twice = _encrypt_data_in_place({"connection": {"key": once["connection"]["key"]}})
    assert twice["connection"]["key"] == once["connection"]["key"]


def test_tool_connection_decrypt_legacy_plaintext_passthrough():
    """Rows written before encryption was added contain plaintext. The
    decrypt path must not raise — it returns the value as-is."""
    from open_webui.models.tool_connections import _decrypt_data_in_place

    out = _decrypt_data_in_place({"connection": {"key": "raw-legacy-token"}})
    assert out["connection"]["key"] == "raw-legacy-token"


def test_tool_connection_handles_missing_or_unexpected_shape():
    from open_webui.models.tool_connections import (
        _decrypt_data_in_place,
        _encrypt_data_in_place,
    )

    # No connection key — passthrough
    assert _encrypt_data_in_place({"connection": {"type": "mcp"}}) == {
        "connection": {"type": "mcp"}
    }
    # data is None — passthrough (model column allows nullable)
    assert _encrypt_data_in_place(None) is None
    assert _decrypt_data_in_place(None) is None
    # connection is a primitive instead of dict — passthrough
    assert _encrypt_data_in_place({"connection": "not-a-dict"}) == {
        "connection": "not-a-dict"
    }


def test_tool_connection_router_mask_helper():
    """API responses must not leak the plaintext bearer token."""
    from open_webui.routers.tool_connections import _mask_connection_key
    from open_webui.utils.crypto import is_masked

    masked = _mask_connection_key({"connection": {"key": "sk-very-secret-value-xyz"}})
    assert is_masked(masked["connection"]["key"])
    # Original input was not mutated
    assert "sk-very-secret-value-xyz" not in masked["connection"]["key"]


def test_tool_connection_router_resolve_masked_key():
    """If the form re-submits a masked placeholder, the saved value must
    be preserved — otherwise editing any other field would silently
    overwrite the secret with the mask string."""
    from open_webui.routers.tool_connections import _resolve_connection_key

    masked_form = {"connection": {"key": "**********xyz"}}
    current = {"connection": {"key": "sk-real-current-value"}}
    resolved = _resolve_connection_key(masked_form, current)
    assert resolved["connection"]["key"] == "sk-real-current-value"


def test_tool_connection_router_resolve_real_value_overrides():
    """A non-masked value in the form is honored — admin can update."""
    from open_webui.routers.tool_connections import _resolve_connection_key

    form = {"connection": {"key": "sk-new-value"}}
    current = {"connection": {"key": "sk-old-value"}}
    resolved = _resolve_connection_key(form, current)
    assert resolved["connection"]["key"] == "sk-new-value"


# --- EncryptedText TypeDecorator -----------------------------------------


def test_encrypted_text_bind_encrypts_plaintext():
    from open_webui.utils.crypto import EncryptedText
    from open_webui.utils.kms.base import is_tagged

    out = EncryptedText().process_bind_param("plain-license-token", None)
    assert is_tagged(out)


def test_encrypted_text_bind_skips_already_tagged():
    """Calling encrypt on an already-tagged value would double-encrypt;
    skip it. Required for the Cloocus migration path which assigns the
    same value back to trigger a re-flush."""
    from open_webui.utils.crypto import EncryptedText

    cipher = EncryptedText().process_bind_param("once", None)
    again = EncryptedText().process_bind_param(cipher, None)
    assert again == cipher


def test_encrypted_text_bind_preserves_legacy_fernet():
    from open_webui.utils.crypto import EncryptedText
    from open_webui.utils.kms.fernet import FernetProvider

    legacy = FernetProvider().encrypt("legacy")
    out = EncryptedText().process_bind_param(legacy, None)
    assert out == legacy


def test_encrypted_text_result_decrypts():
    from open_webui.utils.crypto import EncryptedText

    cipher = EncryptedText().process_bind_param("hunter2", None)
    plain = EncryptedText().process_result_value(cipher, None)
    assert plain == "hunter2"


def test_encrypted_text_result_passthrough_legacy_plaintext():
    """Rows written before EncryptedText was applied still carry
    plaintext — decrypt path must return them unchanged so the table
    stays readable during the migration window."""
    from open_webui.utils.crypto import EncryptedText

    out = EncryptedText().process_result_value("never-encrypted", None)
    assert out == "never-encrypted"


def test_encrypted_text_handles_empty_and_none():
    from open_webui.utils.crypto import EncryptedText

    et = EncryptedText()
    assert et.process_bind_param(None, None) is None
    assert et.process_bind_param("", None) == ""
    assert et.process_result_value(None, None) is None
    assert et.process_result_value("", None) == ""
