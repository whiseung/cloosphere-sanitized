"""``_common.py`` 단위 테스트 — tz validator, audit log writer, tenacity retry,
401 재발급, ``GoogleReauthRequired`` 변환.

T-B19 요구: F3 (IANA tz 강제), tenacity (429/5xx backoff), invalid_grant
(`get_token` None → reauth required), 401 한 번 재발급 후 재시도.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from extension_modules.tools.google.inprocess._common import (
    DEFAULT_WRITE_QUOTA_PER_TURN,
    BatchQuotaExceeded,
    GoogleApiError,
    GoogleReauthRequired,
    call_google_api,
    enforce_write_quota,
    get_token,
    iana_timezone,
    write_audit_log,
)


class TestIanaTimezone:
    def test_valid_iana_passes(self):
        assert iana_timezone("Asia/Seoul") == "Asia/Seoul"
        assert iana_timezone("America/New_York") == "America/New_York"
        assert iana_timezone("Europe/London") == "Europe/London"

    def test_utc_allowed(self):
        # ``UTC`` / ``Etc/UTC`` 는 IANA ID 이고 DST 가 없어 F3 대상 아님 — 허용.
        assert iana_timezone("UTC") == "UTC"
        assert iana_timezone("Etc/UTC") == "Etc/UTC"

    def test_strips_whitespace(self):
        assert iana_timezone("  Asia/Seoul  ") == "Asia/Seoul"

    @pytest.mark.parametrize(
        "bad",
        ["+09:00", "-05:00", "+0900", "GMT+9", "Z", "GMT", "gmt"],
    )
    def test_offset_and_aliases_rejected(self, bad):
        # F3 — DST 사고 회피.  UTC 는 DST 없으므로 허용 (별도 test_utc_allowed).
        with pytest.raises(ValueError):
            iana_timezone(bad)

    def test_unknown_iana_rejected(self):
        with pytest.raises(ValueError):
            iana_timezone("Asia/Atlantis")

    @pytest.mark.parametrize("bad", ["", "   ", None, 123, [], {}])
    def test_invalid_types_rejected(self, bad):
        with pytest.raises((ValueError, TypeError)):
            iana_timezone(bad)


class TestEnforceWriteQuota:
    """T-B21 — in-memory window counter."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from extension_modules.tools.google.inprocess._common import (
            _reset_write_quota_for_test,
        )

        _reset_write_quota_for_test()
        yield
        _reset_write_quota_for_test()

    def test_default_quota_constant(self):
        assert DEFAULT_WRITE_QUOTA_PER_TURN == 3

    def test_under_limit_passes(self):
        for _ in range(3):
            enforce_write_quota(
                user_id="u", conversation_id="c", tool_name="gmail_send"
            )

    def test_over_limit_raises(self):
        for _ in range(3):
            enforce_write_quota(
                user_id="u", conversation_id="c", tool_name="gmail_send"
            )
        with pytest.raises(BatchQuotaExceeded) as exc_info:
            enforce_write_quota(
                user_id="u", conversation_id="c", tool_name="gmail_send"
            )
        assert exc_info.value.user_id == "u"
        assert exc_info.value.limit == 3

    def test_per_user_isolated(self):
        for _ in range(3):
            enforce_write_quota(user_id="user-a", conversation_id="c", tool_name="x")
        # user-b 는 새 카운터
        enforce_write_quota(user_id="user-b", conversation_id="c", tool_name="x")

    def test_per_conversation_isolated(self):
        for _ in range(3):
            enforce_write_quota(user_id="u", conversation_id="conv-1", tool_name="x")
        enforce_write_quota(user_id="u", conversation_id="conv-2", tool_name="x")

    def test_none_conversation_falls_back_to_user_scope(self):
        for _ in range(3):
            enforce_write_quota(user_id="u", conversation_id=None, tool_name="x")
        with pytest.raises(BatchQuotaExceeded):
            enforce_write_quota(user_id="u", conversation_id=None, tool_name="x")

    def test_custom_limit(self):
        enforce_write_quota(user_id="u", conversation_id="c", tool_name="x", limit=1)
        with pytest.raises(BatchQuotaExceeded) as exc_info:
            enforce_write_quota(
                user_id="u", conversation_id="c", tool_name="x", limit=1
            )
        assert exc_info.value.limit == 1

    def test_window_expiry_resets_counter(self, monkeypatch):
        """window 밖 entry 는 제거되어 카운터가 다시 0 부터 시작."""
        from extension_modules.tools.google.inprocess import _common

        now = [0.0]
        monkeypatch.setattr(_common.time, "monotonic", lambda: now[0])

        for _ in range(3):
            enforce_write_quota(user_id="u", conversation_id="c", tool_name="x")
        # window (60s) 초과
        now[0] = 120.0
        enforce_write_quota(user_id="u", conversation_id="c", tool_name="x")


class TestBatchQuotaExceededException:
    def test_attrs(self):
        exc = BatchQuotaExceeded(user_id="u", tool_name="gmail_send", limit=3)
        assert exc.user_id == "u"
        assert exc.tool_name == "gmail_send"
        assert exc.limit == 3
        assert "gmail_send" in str(exc)


class TestGoogleReauthRequired:
    def test_default_reason(self):
        exc = GoogleReauthRequired(user_id="u")
        assert exc.reason == "invalid_grant"
        assert exc.user_id == "u"

    def test_custom_reason(self):
        exc = GoogleReauthRequired(user_id="u", reason="no_token")
        assert exc.reason == "no_token"


class TestGetToken:
    async def test_returns_token_when_valid(self):
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="ya29.abc"),
        ):
            token = await get_token("user-a")
        assert token == "ya29.abc"

    async def test_none_raises_reauth(self):
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(GoogleReauthRequired) as exc_info:
                await get_token("user-a")
        assert exc_info.value.reason == "no_token"
        assert exc_info.value.user_id == "user-a"


class TestWriteAuditLog:
    def test_success_calls_insert(self):
        from open_webui.models.audit_log import AuditAction

        with patch(
            "extension_modules.tools.google.inprocess._common.AuditLogs"
        ) as mock_logs:
            write_audit_log(
                user_id="u",
                action=AuditAction.GMAIL_SEND,
                resource_type="gmail_message",
                after_state={"thread_id": "t1"},
                resource_id="m1",
                conversation_id="c1",
            )
        assert mock_logs.insert_audit_log.called
        form = mock_logs.insert_audit_log.call_args[0][0]
        assert form.user_id == "u"
        assert form.action == "GMAIL_SEND"
        assert form.resource_type == "gmail_message"
        assert form.resource_id == "m1"
        assert form.after_state == {"thread_id": "t1"}
        assert form.meta["conversation_id"] == "c1"

    def test_swallows_exceptions(self):
        """audit 실패는 비즈니스 로직 막지 않음."""
        from open_webui.models.audit_log import AuditAction

        with patch(
            "extension_modules.tools.google.inprocess._common.AuditLogs"
        ) as mock_logs:
            mock_logs.insert_audit_log.side_effect = RuntimeError("DB down")
            # 예외가 외부로 새지 않아야 함
            write_audit_log(
                user_id="u",
                action=AuditAction.GMAIL_SEND,
                resource_type="gmail_message",
                after_state={},
            )

    def test_no_conversation_id_skipped_in_meta(self):
        from open_webui.models.audit_log import AuditAction

        with patch(
            "extension_modules.tools.google.inprocess._common.AuditLogs"
        ) as mock_logs:
            write_audit_log(
                user_id="u",
                action=AuditAction.GMAIL_SEND,
                resource_type="gmail_message",
                after_state={},
            )
        form = mock_logs.insert_audit_log.call_args[0][0]
        assert "conversation_id" not in form.meta


# ---------------------------------------------------------------------------
# call_google_api 통합 — tenacity backoff + 401 재발급 + invalid_grant 변환
# ---------------------------------------------------------------------------


def _make_response(status_code, body=None, json_data=None):
    """httpx.Response 모의 — content + json() 행동."""
    if json_data is not None:
        import json as _json

        content = _json.dumps(json_data).encode("utf-8")
        text = _json.dumps(json_data)
    elif body is not None:
        content = body.encode("utf-8") if isinstance(body, str) else body
        text = body if isinstance(body, str) else body.decode("utf-8", "replace")
    else:
        content = b""
        text = ""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.content = content
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("not json")
    return resp


class TestCallGoogleApiSuccess:
    async def test_200_returns_json(self):
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(
                    return_value=_make_response(200, json_data={"ok": True})
                )
                mock_client_cls.return_value.__aenter__.return_value = client
                result = await call_google_api(
                    method="GET",
                    path="/test",
                    user_id="u",
                    host="api.example.com",
                )
        assert result == {"ok": True}
        # Bearer header 전달 확인
        call_kwargs = client.request.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer tok"

    async def test_empty_204_returns_empty_dict(self):
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(return_value=_make_response(204))
                mock_client_cls.return_value.__aenter__.return_value = client
                result = await call_google_api(
                    method="DELETE",
                    path="/test",
                    user_id="u",
                    host="api.example.com",
                )
        assert result == {}


class TestCallGoogleApiResponseMode:
    """response_mode='text' — drive export / alt=media 가 원문(CSV/plain) 반환.

    drive 경로만 response_mode='text' 를 넘긴다.  gmail/calendar/send 는
    안 넘기므로 기본 'json' → 회귀 게이트 (기존 mock 시그니처 6곳) 안전.
    """

    async def test_text_mode_returns_text_dict(self):
        # body 는 비-JSON 원문 — _make_response 가 resp.json() 에 ValueError side_effect 를
        # 설정하므로, 성공 라인이 잘못 response.json() 을 부르면 이 테스트가 깨진다.
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(
                    return_value=_make_response(200, body="col1,col2\n1,2\n")
                )
                mock_client_cls.return_value.__aenter__.return_value = client
                result = await call_google_api(
                    method="GET",
                    path="/test/export",
                    user_id="u",
                    host="www.googleapis.com",
                    response_mode="text",
                )
        assert result == {"text": "col1,col2\n1,2\n"}

    async def test_text_mode_empty_content_returns_empty_dict(self):
        # 검증된 함정 (spec §4.2): content 가드가 mode 분기보다 앞 — 빈 본문은
        # text 모드에서도 {} 반환.  drive.py 는 반드시 resp.get("text", "") 사용.
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(return_value=_make_response(200))
                mock_client_cls.return_value.__aenter__.return_value = client
                result = await call_google_api(
                    method="GET",
                    path="/test/export",
                    user_id="u",
                    host="www.googleapis.com",
                    response_mode="text",
                )
        assert result == {}

    async def test_json_mode_default_unchanged(self):
        # 기본값 'json' — response_mode 미지정 시 기존 동작 byte-for-byte 동일.
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(
                    return_value=_make_response(200, json_data={"ok": True})
                )
                mock_client_cls.return_value.__aenter__.return_value = client
                result = await call_google_api(
                    method="GET", path="/t", user_id="u", host="h"
                )
        assert result == {"ok": True}


class TestCallGoogleApi4xx:
    async def test_403_raises_google_api_error(self):
        # scope 거절 시나리오 — 403
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(
                    return_value=_make_response(
                        403,
                        json_data={"error": {"message": "Insufficient scope"}},
                    )
                )
                mock_client_cls.return_value.__aenter__.return_value = client
                with pytest.raises(GoogleApiError) as exc_info:
                    await call_google_api(
                        method="POST", path="/x", user_id="u", host="h"
                    )
        assert exc_info.value.status_code == 403
        assert "Insufficient scope" in str(exc_info.value.message)

    async def test_400_raises_google_api_error(self):
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                client.request = AsyncMock(
                    return_value=_make_response(400, body="bad request")
                )
                mock_client_cls.return_value.__aenter__.return_value = client
                with pytest.raises(GoogleApiError) as exc_info:
                    await call_google_api(
                        method="POST", path="/x", user_id="u", host="h"
                    )
        assert exc_info.value.status_code == 400


class TestCallGoogleApi401Retry:
    async def test_401_then_200_succeeds(self):
        """첫 호출 401 → 토큰 재발급 후 200 OK."""
        tokens = iter(["tok-old", "tok-new"])

        async def get_token_mock(*_args, **_kwargs):
            return next(tokens)

        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(side_effect=get_token_mock),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
            ) as mock_client_cls:
                client = AsyncMock()
                responses = iter(
                    [
                        _make_response(401, body="unauthorized"),
                        _make_response(200, json_data={"ok": True}),
                    ]
                )

                async def request_mock(*_a, **_k):
                    return next(responses)

                client.request = AsyncMock(side_effect=request_mock)
                mock_client_cls.return_value.__aenter__.return_value = client
                result = await call_google_api(
                    method="GET", path="/x", user_id="u", host="h"
                )
        assert result == {"ok": True}
        # 두 번 호출됨 (첫 번 401, 두 번째 OK)
        assert client.request.call_count == 2

    async def test_401_twice_raises_reauth_required(self):
        """첫 호출 401 → 재발급 → 또 401 → invalid_grant 류 영구 실패."""
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common._purge_invalid_google_token"
            ):
                with patch(
                    "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
                ) as mock_client_cls:
                    client = AsyncMock()
                    client.request = AsyncMock(
                        return_value=_make_response(401, body="still unauthorized")
                    )
                    mock_client_cls.return_value.__aenter__.return_value = client
                    with pytest.raises(GoogleReauthRequired) as exc_info:
                        await call_google_api(
                            method="GET", path="/x", user_id="u", host="h"
                        )
        assert exc_info.value.reason == "auth_failed_after_refresh"

    async def test_401_twice_purges_token_row(self):
        """T-B20: invalid_grant 확정 시 ``UserOAuthTokens(provider='google')`` row 삭제."""
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            with patch(
                "extension_modules.tools.google.inprocess._common._purge_invalid_google_token"
            ) as purge_mock:
                with patch(
                    "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
                ) as mock_client_cls:
                    client = AsyncMock()
                    client.request = AsyncMock(
                        return_value=_make_response(401, body="invalid_grant")
                    )
                    mock_client_cls.return_value.__aenter__.return_value = client
                    with pytest.raises(GoogleReauthRequired):
                        await call_google_api(
                            method="GET", path="/x", user_id="user-a", host="h"
                        )
                purge_mock.assert_called_once_with("user-a")

    async def test_purge_invalid_google_token_swallows_exceptions(self):
        """row 삭제 실패가 비즈니스 흐름 막지 않음 (audit 와 동일 정책)."""
        from unittest.mock import MagicMock

        from extension_modules.tools.google.inprocess._common import (
            _purge_invalid_google_token,
        )

        with patch(
            "open_webui.models.user_oauth_tokens.UserOAuthTokens"
        ) as mock_tokens:
            mock_tokens.delete = MagicMock(side_effect=RuntimeError("DB down"))
            # 예외가 외부로 새지 않아야 함
            _purge_invalid_google_token("user-a")

    async def test_token_none_raises_reauth_immediately(self):
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(GoogleReauthRequired) as exc_info:
                await call_google_api(method="GET", path="/x", user_id="u", host="h")
        assert exc_info.value.reason == "no_token"


class TestCallGoogleApiRetry:
    """tenacity backoff — 429 / 5xx / network 는 transient 로 재시도."""

    async def test_429_then_200_succeeds(self):
        # 429 → 429 → 200 (총 3회).  tenacity 가 transient retry.
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            # wait 를 0으로 줄여 테스트 속도 ↑
            from extension_modules.tools.google.inprocess import _common

            with patch.object(
                _common._call_google_api_with_retry.retry, "wait", lambda *a, **k: 0
            ):
                with patch(
                    "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
                ) as mock_client_cls:
                    client = AsyncMock()
                    responses = iter(
                        [
                            _make_response(429, body="rate limited"),
                            _make_response(429, body="rate limited"),
                            _make_response(200, json_data={"ok": True}),
                        ]
                    )

                    async def request_mock(*_a, **_k):
                        return next(responses)

                    client.request = AsyncMock(side_effect=request_mock)
                    mock_client_cls.return_value.__aenter__.return_value = client
                    result = await call_google_api(
                        method="GET", path="/x", user_id="u", host="h"
                    )
        assert result == {"ok": True}
        assert client.request.call_count == 3

    async def test_500_eventually_gives_up(self):
        # 영구 500 — tenacity 가 4회 시도 후 포기 → _Retryable 가 reraise
        with patch(
            "extension_modules.tools.google.inprocess._common.get_valid_access_token",
            new=AsyncMock(return_value="tok"),
        ):
            from extension_modules.tools.google.inprocess import _common

            with patch.object(
                _common._call_google_api_with_retry.retry, "wait", lambda *a, **k: 0
            ):
                with patch(
                    "extension_modules.tools.google.inprocess._common.httpx.AsyncClient"
                ) as mock_client_cls:
                    client = AsyncMock()
                    client.request = AsyncMock(
                        return_value=_make_response(500, body="server error")
                    )
                    mock_client_cls.return_value.__aenter__.return_value = client
                    with pytest.raises(Exception):  # _Retryable propagates
                        await call_google_api(
                            method="GET", path="/x", user_id="u", host="h"
                        )
        assert client.request.call_count == 4  # stop_after_attempt(4)


class TestParseResponseBytesMode:
    """T0.1 — bytes response_mode (Drive/Gmail 첨부 바이너리 다운로드용)."""

    def test_bytes_mode_returns_raw_content(self):
        from extension_modules.tools.google.inprocess._common import _parse_response

        response = httpx.Response(200, content=b"%PDF-1.4 binary\x00bytes")
        parsed = _parse_response(response, response_mode="bytes")
        assert parsed == {"content_bytes": b"%PDF-1.4 binary\x00bytes"}

    def test_bytes_mode_empty_returns_empty_dict(self):
        # 빈 본문은 text 모드와 동일하게 {} — caller 는 .get("content_bytes", b"") 로 회피.
        from extension_modules.tools.google.inprocess._common import _parse_response

        response = httpx.Response(200, content=b"")
        assert _parse_response(response, response_mode="bytes") == {}

    def test_bytes_mode_4xx_still_raises_google_api_error(self):
        from extension_modules.tools.google.inprocess._common import _parse_response

        response = httpx.Response(404, json={"error": "not found"})
        with pytest.raises(GoogleApiError):
            _parse_response(response, response_mode="bytes")
