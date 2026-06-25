"""HMAC message_id mint / verify 단위 테스트.

T-B13 의 multi-worker safe owner binding 의 핵심 — verify 가 cross-user /
tampered / garbage / empty 모두 False 를 돌려줘야 IDOR 차단.
"""

from __future__ import annotations

from extension_modules.tools.google.inprocess._message_id import (
    mint_message_id,
    verify_message_id,
)


class TestMintMessageId:
    def test_format_uuid_dot_sig(self):
        mid = mint_message_id("user-a")
        assert "." in mid
        uuid_part, sig = mid.rsplit(".", 1)
        assert len(uuid_part) == 32  # token_hex(16) = 32 hex chars
        assert len(sig) == 16  # truncated HMAC

    def test_unique_per_call(self):
        ids = {mint_message_id("user-a") for _ in range(100)}
        assert len(ids) == 100  # no collision

    def test_empty_user_id_rejects(self):
        import pytest

        with pytest.raises(ValueError):
            mint_message_id("")


class TestVerifyMessageId:
    def test_roundtrip(self):
        mid = mint_message_id("user-a")
        assert verify_message_id(mid, "user-a") is True

    def test_cross_user_fails(self):
        mid = mint_message_id("user-a")
        assert verify_message_id(mid, "user-b") is False

    def test_tampered_signature_fails(self):
        mid = mint_message_id("user-a")
        # 마지막 hex 문자 변경
        tampered = mid[:-1] + ("0" if mid[-1] != "0" else "1")
        assert verify_message_id(tampered, "user-a") is False

    def test_tampered_uuid_fails(self):
        mid = mint_message_id("user-a")
        # uuid 부분의 첫 문자 변경
        tampered = ("0" if mid[0] != "0" else "1") + mid[1:]
        assert verify_message_id(tampered, "user-a") is False

    def test_empty_inputs_fail(self):
        assert verify_message_id("", "user-a") is False
        assert verify_message_id("anything", "") is False
        assert verify_message_id("", "") is False

    def test_no_dot_separator_fails(self):
        assert verify_message_id("garbage-no-dot", "user-a") is False

    def test_short_sig_fails(self):
        # sig 길이가 16 hex 가 아니면 거부
        assert verify_message_id("abc.short", "user-a") is False

    def test_empty_uuid_part_fails(self):
        # ``.sigxxxxx`` 형태 — uuid 가 빈 string
        assert verify_message_id(".1234567890abcdef", "user-a") is False

    def test_none_inputs_safe(self):
        assert verify_message_id(None, "user-a") is False  # type: ignore[arg-type]
        assert verify_message_id("abc.def", None) is False  # type: ignore[arg-type]
