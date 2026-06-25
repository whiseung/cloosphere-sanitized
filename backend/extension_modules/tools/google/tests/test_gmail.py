"""Gmail tool builder 단위 테스트.

T-B14: mock httpx, base64url 검증, F1 회귀, 401/invalid_grant/429/scope 오류,
batch quota.  base64url 과 401/429 는 ``test_send.py`` / ``test_common.py`` 에서
다루고, 본 파일은 tool 외부 인터페이스 (HITL payload, search/get 결과 형식)에 집중.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from extension_modules.tools.google.inprocess._common import (
    BatchQuotaExceeded,
    GoogleApiError,
    GoogleReauthRequired,
)
from extension_modules.tools.google.inprocess._message_id import verify_message_id
from extension_modules.tools.google.inprocess.gmail import (
    GMAIL_CONFIRM_MARKER,
    GMAIL_QUOTA_MARKER,
    GmailGetArgs,
    GmailSearchArgs,
    GmailSendArgs,
    _decode_b64url,
    _extract_message_body,
    _pick_headers,
    _strip_html,
    make_gmail_tools,
)

# ---------------------------------------------------------------------------
# Pydantic args
# ---------------------------------------------------------------------------


class TestGmailSendArgs:
    def test_minimum_valid(self):
        args = GmailSendArgs(to=["a@b.com"], subject="hi", body="hello")
        assert args.to == ["a@b.com"]
        assert args.cc is None
        assert args.bcc is None
        assert args.in_reply_to is None

    def test_empty_to_allowed_at_tool_stage(self):
        # tool 단계는 빈 수신자 허용 — 수신자 미상이면 모델이 빈 to 로 호출해 확인
        # 카드를 띄우고 사용자가 채운다.  실제 발송(GmailConfirmBody)에서만 ≥1 강제.
        args = GmailSendArgs(to=[], subject="s", body="b")
        assert args.to == []
        # to 생략도 빈 리스트로 기본값 처리.
        assert GmailSendArgs(subject="s", body="b").to == []


class TestGmailSearchArgs:
    def test_defaults(self):
        args = GmailSearchArgs(q="from:alice")
        assert args.max_results == 10
        assert args.page_token is None

    @pytest.mark.parametrize("bad_q", ["", "   ", "\n\t"])
    def test_blank_query_rejects(self, bad_q):
        with pytest.raises(Exception):
            GmailSearchArgs(q=bad_q)

    @pytest.mark.parametrize("bad_max", [0, -1, 26, 1000])
    def test_max_results_out_of_range_rejects(self, bad_max):
        with pytest.raises(Exception):
            GmailSearchArgs(q="x", max_results=bad_max)


class TestGmailGetArgs:
    def test_valid(self):
        args = GmailGetArgs(message_id="abc")
        assert args.message_id == "abc"

    def test_empty_rejects(self):
        with pytest.raises(Exception):
            GmailGetArgs(message_id="")


# ---------------------------------------------------------------------------
# make_gmail_tools factory
# ---------------------------------------------------------------------------


class TestMakeGmailTools:
    def test_returns_four_tools(self):
        tools = make_gmail_tools("user-x")
        assert [t.name for t in tools] == [
            "gmail_send",
            "gmail_search",
            "gmail_get",
            "gmail_get_batch",
        ]

    def test_send_is_sync_search_get_async(self):
        tools = {t.name: t for t in make_gmail_tools("u")}
        # send: HITL preview only — sync
        assert tools["gmail_send"].coroutine is None
        # search/get/batch: external API — async
        assert tools["gmail_search"].coroutine is not None
        assert tools["gmail_get"].coroutine is not None
        assert tools["gmail_get_batch"].coroutine is not None


# ---------------------------------------------------------------------------
# gmail_send HITL output
# ---------------------------------------------------------------------------


class TestGmailSendTool:
    @pytest.fixture(autouse=True)
    def _reset_quota(self):
        from extension_modules.tools.google.inprocess._common import (
            _reset_write_quota_for_test,
        )

        _reset_write_quota_for_test()
        yield
        _reset_write_quota_for_test()

    def _send(self, user_id="u", **kwargs):
        tool = [t for t in make_gmail_tools(user_id) if t.name == "gmail_send"][0]
        defaults = {"to": ["a@example.com"], "subject": "hi", "body": "hello"}
        defaults.update(kwargs)
        return tool.func(**defaults)

    def test_returns_marker_plus_json(self, with_internal_domain):
        result = self._send()
        assert result.startswith(GMAIL_CONFIRM_MARKER)
        # ```json``` 블록 추출
        json_part = result.split("json\n", 1)[1].rsplit("\n", 2)[0]
        payload = json.loads(json_part)
        assert payload["confirmation_required"] is True

    def test_message_id_hmac_bound_to_user(self, with_internal_domain):
        result = self._send(user_id="user-x")
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        # verify_message_id 는 user-x 로만 통과
        assert verify_message_id(payload["message_id"], "user-x") is True
        assert verify_message_id(payload["message_id"], "user-y") is False

    def test_external_recipient_high_risk(self, with_internal_domain):
        result = self._send(to=["alice@external.com"])
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["risk_level"] == "high"

    def test_internal_single_short_low_risk(self, with_internal_domain):
        result = self._send(to=["alice@cloocus.com"], body="short")
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["risk_level"] == "low"

    def test_tool_does_not_call_external_api(self, with_internal_domain):
        """gmail_send 는 HITL preview 만 — 외부 API 호출 절대 안 함."""
        # call_google_api 가 호출되면 patch.assert_not_called 가 잡음
        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api"
        ) as mock_api:
            self._send()
            mock_api.assert_not_called()

    def test_quota_exceeded_returns_quota_marker(self, with_internal_domain):
        with patch(
            "extension_modules.tools.google.inprocess.gmail.enforce_write_quota",
            side_effect=BatchQuotaExceeded(
                user_id="u", tool_name="gmail_send", limit=3
            ),
        ):
            result = self._send()
        assert result.startswith(GMAIL_QUOTA_MARKER)
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["error"] == "batch_quota_exceeded"
        assert payload["limit"] == 3

    def test_conversation_id_threaded_to_quota(self, with_internal_domain):
        """T-B21 quota scope — make_gmail_send 가 conversation_id 를
        enforce_write_quota 로 전달."""
        from extension_modules.tools.google.inprocess.gmail import make_gmail_send

        tool = make_gmail_send("user-x", conversation_id="conv-abc")
        with patch(
            "extension_modules.tools.google.inprocess.gmail.enforce_write_quota"
        ) as quota_mock:
            tool.func(to=["a@example.com"], subject="s", body="b")
        quota_mock.assert_called_once()
        kwargs = quota_mock.call_args.kwargs
        assert kwargs["user_id"] == "user-x"
        assert kwargs["conversation_id"] == "conv-abc"
        assert kwargs["tool_name"] == "gmail_send"


# ---------------------------------------------------------------------------
# gmail_search tool — mocked httpx
# ---------------------------------------------------------------------------


class TestGmailSearchTool:
    def _tool(self, user_id="u"):
        return [t for t in make_gmail_tools(user_id) if t.name == "gmail_search"][0]

    async def test_aggregates_list_and_metadata(self):
        async def mock_call(
            method, path, *, user_id, host, json=None, params=None, timeout=30.0
        ):
            if path == "/gmail/v1/users/me/messages":
                return {
                    "messages": [
                        {"id": "m1", "threadId": "t1"},
                        {"id": "m2", "threadId": "t2"},
                    ],
                    "nextPageToken": "next-page",
                    "resultSizeEstimate": 2,
                }
            if path == "/gmail/v1/users/me/messages/m1":
                return {
                    "id": "m1",
                    "threadId": "t1",
                    "snippet": "snippet 1",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "S1"},
                            {"name": "From", "value": "a@b.com"},
                        ]
                    },
                }
            if path == "/gmail/v1/users/me/messages/m2":
                return {
                    "id": "m2",
                    "threadId": "t2",
                    "snippet": "snippet 2",
                    "labelIds": [],
                    "payload": {"headers": [{"name": "Subject", "value": "S2"}]},
                }
            raise ValueError(f"unexpected path {path}")

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="subject:test", max_results=10)
        data = json.loads(result)
        assert len(data["results"]) == 2
        assert data["results"][0]["id"] == "m1"
        assert data["results"][0]["snippet"] == "snippet 1"
        assert data["results"][0]["headers"]["Subject"] == "S1"
        assert data["next_page_token"] == "next-page"
        assert data["result_size_estimate"] == 2

    async def test_per_message_failure_skipped(self):
        async def mock_call(
            method, path, *, user_id, host, json=None, params=None, timeout=30.0
        ):
            if path == "/gmail/v1/users/me/messages":
                return {"messages": [{"id": "m1"}, {"id": "m2"}]}
            if path.endswith("/m1"):
                raise GoogleApiError(404, "deleted")
            return {
                "id": "m2",
                "threadId": "t2",
                "snippet": "ok",
                "labelIds": [],
                "payload": {"headers": [{"name": "Subject", "value": "S2"}]},
            }

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="x")
        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == "m2"

    async def test_reauth_required_aborts(self):
        async def mock_call(*_args, **_kwargs):
            raise GoogleReauthRequired(user_id="u", reason="invalid_grant")

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="from:a")
        data = json.loads(result)
        assert data["error"] == "google_reauth_required"
        assert data["reason"] == "invalid_grant"
        assert "hint" in data

    async def test_list_api_error_aborts(self):
        async def mock_call(*_args, **_kwargs):
            raise GoogleApiError(403, "insufficient scope")

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="x")
        data = json.loads(result)
        assert data["error"] == "gmail_api_error_403"

    async def test_page_token_propagates(self):
        captured = {}

        async def mock_call(
            method, path, *, user_id, host, json=None, params=None, timeout=30.0
        ):
            captured["params"] = params
            return {"messages": []}

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await self._tool().coroutine(q="x", page_token="abc123")
        assert captured["params"]["pageToken"] == "abc123"


# ---------------------------------------------------------------------------
# gmail_get tool
# ---------------------------------------------------------------------------


class TestGmailGetTool:
    def _tool(self, user_id="u"):
        return [t for t in make_gmail_tools(user_id) if t.name == "gmail_get"][0]

    async def test_extracts_text_plain_body(self):
        plain = (
            base64.urlsafe_b64encode(b"plain body content").rstrip(b"=").decode("ascii")
        )
        html = (
            base64.urlsafe_b64encode(b"<p>html body</p>").rstrip(b"=").decode("ascii")
        )

        async def mock_call(*_args, **_kwargs):
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "preview",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [{"name": "Subject", "value": "Subj"}],
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": plain}},
                        {"mimeType": "text/html", "body": {"data": html}},
                    ],
                },
            }

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(message_id="m1")
        data = json.loads(result)
        assert data["id"] == "m1"
        assert data["body"] == "plain body content"
        assert data["body_is_html_fallback"] is False
        assert data["headers"]["Subject"] == "Subj"
        assert data["label_ids"] == ["INBOX"]

    async def test_html_only_falls_back_with_flag(self):
        html = (
            base64.urlsafe_b64encode(b"<p>html only</p>").rstrip(b"=").decode("ascii")
        )

        async def mock_call(*_args, **_kwargs):
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "",
                "labelIds": [],
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [],
                    "parts": [
                        {"mimeType": "text/html", "body": {"data": html}},
                    ],
                },
            }

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(message_id="m1")
        data = json.loads(result)
        assert data["body"] == "html only"  # HTML tags stripped
        assert data["body_is_html_fallback"] is True

    async def test_reauth_error_returns_json(self):
        async def mock_call(*_args, **_kwargs):
            raise GoogleReauthRequired(user_id="u")

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(message_id="m1")
        data = json.loads(result)
        assert data["error"] == "google_reauth_required"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestPickHeaders:
    def test_whitelist_only(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hello"},
                    {"name": "From", "value": "a@b.com"},
                    {"name": "X-Spam-Flag", "value": "YES"},
                    {"name": "Authentication-Results", "value": "spf=pass"},
                    {"name": "Date", "value": "Mon, 20 May 2026 10:00:00 +0000"},
                ]
            }
        }
        out = _pick_headers(msg)
        assert "Subject" in out
        assert "From" in out
        assert "Date" in out
        assert "X-Spam-Flag" not in out
        assert "Authentication-Results" not in out

    def test_missing_payload_safe(self):
        assert _pick_headers({}) == {}
        assert _pick_headers({"payload": None}) == {}


class TestDecodeB64Url:
    def test_empty_returns_empty(self):
        assert _decode_b64url("") == ""

    def test_roundtrip_ascii(self):
        encoded = base64.urlsafe_b64encode(b"Hello World").rstrip(b"=").decode("ascii")
        assert _decode_b64url(encoded) == "Hello World"

    def test_roundtrip_korean(self):
        encoded = (
            base64.urlsafe_b64encode("한글 텍스트".encode("utf-8"))
            .rstrip(b"=")
            .decode("ascii")
        )
        assert _decode_b64url(encoded) == "한글 텍스트"


class TestStripHtml:
    def test_basic_strip(self):
        assert _strip_html("<p>hello <b>world</b></p>") == "hello world"

    def test_empty(self):
        assert _strip_html("") == ""

    def test_nested(self):
        assert _strip_html("<div><p>A</p><p>B</p></div>") == "A B"


class TestExtractMessageBody:
    def _b64(self, text):
        return (
            base64.urlsafe_b64encode(text.encode("utf-8")).rstrip(b"=").decode("ascii")
        )

    def test_plain_wins_over_html(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": self._b64("plain")}},
                {"mimeType": "text/html", "body": {"data": self._b64("<p>html</p>")}},
            ],
        }
        body, is_html = _extract_message_body(payload)
        assert body == "plain"
        assert is_html is False

    def test_html_only_fallback(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": self._b64("<p>only html</p>")},
                },
            ],
        }
        body, is_html = _extract_message_body(payload)
        assert body == "only html"
        assert is_html is True

    def test_nested_multipart(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": self._b64("nested plain")},
                        },
                    ],
                },
                {"mimeType": "application/pdf", "body": {"data": "x"}},
            ],
        }
        body, is_html = _extract_message_body(payload)
        assert body == "nested plain"
        assert is_html is False

    def test_single_part(self):
        payload = {"mimeType": "text/plain", "body": {"data": self._b64("simple")}}
        body, is_html = _extract_message_body(payload)
        assert body == "simple"
        assert is_html is False

    def test_empty_payload(self):
        body, is_html = _extract_message_body({})
        assert body == ""
        assert is_html is False


# ---------------------------------------------------------------------------
# T2 — gmail_get 첨부(PDF/Office) 본문 추출
# ---------------------------------------------------------------------------

_XCFG = {"engine": "", "loader_kwargs": {}}


class TestGmailGetAttachments:
    """T2 — gmail_get 가 첨부 바이너리를 RAG Loader 로 추출."""

    def _tool(self, extraction_config=_XCFG, user_id="u"):
        return [
            t
            for t in make_gmail_tools(user_id, extraction_config=extraction_config)
            if t.name == "gmail_get"
        ][0]

    def _msg_with_pdf(self):
        plain = base64.urlsafe_b64encode(b"body text").rstrip(b"=").decode("ascii")
        return {
            "id": "m1",
            "threadId": "t1",
            "snippet": "p",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [{"name": "Subject", "value": "MPCI"}],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": plain}},
                    {
                        "mimeType": "application/pdf",
                        "filename": "invoice.pdf",
                        "body": {"attachmentId": "att1", "size": 2048},
                    },
                ],
            },
        }

    async def test_pdf_attachment_extracted(self):
        att_b64 = base64.urlsafe_b64encode(b"%PDF fake").rstrip(b"=").decode("ascii")

        async def mock_call(method, path, **kwargs):
            if "/attachments/att1" in path:
                return {"data": att_b64, "size": 8}
            return self._msg_with_pdf()

        with (
            patch(
                "extension_modules.tools.google.inprocess.gmail.call_google_api",
                new=AsyncMock(side_effect=mock_call),
            ),
            patch(
                "extension_modules.tools.google.inprocess.gmail.extract_text_from_bytes",
                new=AsyncMock(
                    return_value={"content": "INVOICE TEXT", "truncated": False}
                ),
            ),
        ):
            result = await self._tool().coroutine(message_id="m1")
        data = json.loads(result)
        assert data["body"] == "body text"
        assert len(data["attachments"]) == 1
        assert data["attachments"][0]["filename"] == "invoice.pdf"
        assert data["attachments"][0]["content"] == "INVOICE TEXT"

    async def test_image_attachment_note_only(self):
        async def mock_call(method, path, **kwargs):
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "",
                "labelIds": [],
                "payload": {
                    "mimeType": "multipart/mixed",
                    "headers": [],
                    "parts": [
                        {
                            "mimeType": "image/png",
                            "filename": "photo.png",
                            "body": {"attachmentId": "att2", "size": 100},
                        }
                    ],
                },
            }

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(message_id="m1")
        data = json.loads(result)
        assert len(data["attachments"]) == 1
        assert "content" not in data["attachments"][0]
        assert data["attachments"][0].get("note")

    async def test_no_attachments_empty_list(self):
        plain = base64.urlsafe_b64encode(b"just body").rstrip(b"=").decode("ascii")

        async def mock_call(method, path, **kwargs):
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "",
                "labelIds": [],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [],
                    "body": {"data": plain},
                },
            }

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(message_id="m1")
        data = json.loads(result)
        assert data["body"] == "just body"
        assert data["attachments"] == []

    async def test_extraction_disabled_no_attachment_fetch(self):
        fetched: list[str] = []

        async def mock_call(method, path, **kwargs):
            if "/attachments/" in path:
                fetched.append(path)
            return self._msg_with_pdf()

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool(extraction_config=None).coroutine(message_id="m1")
        data = json.loads(result)
        assert fetched == []  # 첨부 본문 fetch 안 함
        # 첨부 존재는 메타로 노출(note), 본문은 없음.
        assert len(data["attachments"]) == 1
        assert "content" not in data["attachments"][0]


async def test_gmail_get_caps_long_body():
    # T5/M2 — 장문 본문은 per-message cap (컨텍스트 폭증 방지).
    big = base64.urlsafe_b64encode(("y" * 60000).encode()).rstrip(b"=").decode("ascii")
    tool = [t for t in make_gmail_tools("u") if t.name == "gmail_get"][0]

    async def mock_call(*_a, **_k):
        return {
            "id": "m1",
            "threadId": "t1",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": big},
            },
        }

    with patch(
        "extension_modules.tools.google.inprocess.gmail.call_google_api",
        new=AsyncMock(side_effect=mock_call),
    ):
        result = await tool.coroutine(message_id="m1")
    data = json.loads(result)
    assert len(data["body"]) == 50000
    assert data["body_truncated"] is True


class TestGmailGetBatch:
    """T4 — gmail_get_batch 배치 읽기 (도구 호출 budget 절약)."""

    def _tool(self, extraction_config=_XCFG, user_id="u"):
        return [
            t
            for t in make_gmail_tools(user_id, extraction_config=extraction_config)
            if t.name == "gmail_get_batch"
        ][0]

    async def test_reads_multiple_in_one_call(self):
        async def mock_call(method, path, **_kwargs):
            mid = path.rsplit("/", 1)[-1]
            plain = (
                base64.urlsafe_b64encode(f"body-{mid}".encode())
                .rstrip(b"=")
                .decode("ascii")
            )
            return {
                "id": mid,
                "threadId": "t",
                "snippet": "",
                "labelIds": [],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [],
                    "body": {"data": plain},
                },
            }

        with patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(message_ids=["m1", "m2"])
        data = json.loads(result)
        assert "error" not in data  # 최상위 results — 집계 누락 방지
        assert len(data["results"]) == 2
        bodies = {r["body"] for r in data["results"]}
        assert bodies == {"body-m1", "body-m2"}


async def test_attachment_combined_budget_capped():
    # T5/M2 — 한 메시지의 첨부 본문 합산이 cap(MAX_EXTRACT_CHARS)을 넘지 않는다.
    from extension_modules.tools.google.inprocess._extract import MAX_EXTRACT_CHARS

    big = "z" * 40000  # 각 첨부 40k → 합산 80k 시도, cap 으로 절단

    async def mock_call(method, path, **_kwargs):
        if "/attachments/" in path:
            return {"data": "QUFB", "size": 100}
        return {
            "id": "m1",
            "threadId": "t1",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [],
                "parts": [
                    {
                        "mimeType": "application/pdf",
                        "filename": "a.pdf",
                        "body": {"attachmentId": "a1", "size": 100},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "b.pdf",
                        "body": {"attachmentId": "a2", "size": 100},
                    },
                ],
            },
        }

    tool = [
        t
        for t in make_gmail_tools(
            "u", extraction_config={"engine": "", "loader_kwargs": {}}
        )
        if t.name == "gmail_get"
    ][0]
    with (
        patch(
            "extension_modules.tools.google.inprocess.gmail.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ),
        patch(
            "extension_modules.tools.google.inprocess.gmail.extract_text_from_bytes",
            new=AsyncMock(return_value={"content": big, "truncated": False}),
        ),
    ):
        result = await tool.coroutine(message_id="m1")
    data = json.loads(result)
    total = sum(len(a.get("content", "")) for a in data["attachments"])
    assert total <= MAX_EXTRACT_CHARS
