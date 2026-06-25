"""``send.py`` 단위 테스트 — MIME 작성 (F1 base64url), Gmail send 호출,
Calendar event create 호출.

F1 회귀: ``urlsafe_b64encode`` 사용, ``b64encode`` X.  base64url 알파벳은
``A-Z a-z 0-9 - _`` (+ 패딩 ``=``) — 디코드 가능해야 함.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest
from extension_modules.tools.google.inprocess.send import (
    compose_gmail_mime,
    create_calendar_event_now,
    create_drive_doc_now,
    send_gmail_now,
)

# ---------------------------------------------------------------------------
# compose_gmail_mime (F1 회귀)
# ---------------------------------------------------------------------------


class TestComposeGmailMime:
    def test_base64url_alphabet_only(self):
        """F1: urlsafe_b64encode 만 사용 — '+' / '/' 가 결과에 없어야 함."""
        raw = compose_gmail_mime(
            to=["alice@example.com"],
            subject="hi",
            body="hello",
        )
        # base64url = A-Z a-z 0-9 - _ (padding 제거된 상태)
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        invalid_chars = [c for c in raw if c not in allowed]
        assert not invalid_chars, f"non-base64url chars: {invalid_chars}"

    def test_roundtrip_basic(self):
        raw = compose_gmail_mime(
            to=["alice@example.com"],
            subject="hello",
            body="world",
        )
        # 패딩 추가 후 디코드
        decoded = base64.urlsafe_b64decode(raw + "===").decode("utf-8")
        assert "To: alice@example.com" in decoded
        assert "Subject: hello" in decoded
        assert "world" in decoded

    def test_korean_utf8_roundtrip(self):
        raw = compose_gmail_mime(
            to=["alice@example.com"],
            subject="안녕",
            body="한글 본문",
        )
        decoded_bytes = base64.urlsafe_b64decode(raw + "===")
        # MIME 인코딩 (RFC 2047) — 본문은 base64 인코드된 채로 있을 수 있음 → 단순
        # bytes 길이만 확인
        assert len(decoded_bytes) > 50  # MIME 헤더 + 본문 + 빈 줄

    def test_cc_bcc_in_headers(self):
        raw = compose_gmail_mime(
            to=["a@x.com"],
            subject="s",
            body="b",
            cc=["c@x.com"],
            bcc=["d@x.com"],
        )
        decoded = base64.urlsafe_b64decode(raw + "===").decode("utf-8")
        assert "Cc: c@x.com" in decoded
        assert "Bcc: d@x.com" in decoded

    def test_in_reply_to_headers(self):
        raw = compose_gmail_mime(
            to=["a@x.com"],
            subject="re: hi",
            body="ok",
            in_reply_to="<msg-123@example>",
        )
        decoded = base64.urlsafe_b64decode(raw + "===").decode("utf-8")
        assert "In-Reply-To: <msg-123@example>" in decoded
        assert "References: <msg-123@example>" in decoded

    def test_multiple_to_recipients(self):
        raw = compose_gmail_mime(
            to=["a@x.com", "b@x.com", "c@x.com"],
            subject="s",
            body="b",
        )
        decoded = base64.urlsafe_b64decode(raw + "===").decode("utf-8")
        assert "a@x.com, b@x.com, c@x.com" in decoded


# ---------------------------------------------------------------------------
# send_gmail_now (외부 호출 mocked)
# ---------------------------------------------------------------------------


class TestSendGmailNow:
    async def test_calls_correct_endpoint(self):
        captured = {}

        async def mock_call(
            method, path, *, user_id, host, json=None, params=None, timeout=30.0
        ):
            captured.update(
                method=method,
                path=path,
                host=host,
                user_id=user_id,
                json=json,
                params=params,
            )
            return {"id": "gmail-1", "threadId": "thr-1", "labelIds": ["SENT"]}

        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            resp = await send_gmail_now(
                user_id="u",
                to=["alice@example.com"],
                subject="hi",
                body="hello",
            )
        assert resp["id"] == "gmail-1"
        assert captured["method"] == "POST"
        assert captured["path"] == "/gmail/v1/users/me/messages/send"
        assert captured["host"] == "gmail.googleapis.com"
        assert "raw" in captured["json"]
        # raw 가 base64url string 인지 확인
        raw = captured["json"]["raw"]
        decoded = base64.urlsafe_b64decode(raw + "===").decode("utf-8")
        assert "Subject: hi" in decoded


# ---------------------------------------------------------------------------
# create_calendar_event_now
# ---------------------------------------------------------------------------


class TestCreateCalendarEventNow:
    @pytest.fixture
    def mock_capture(self):
        captured = {}

        async def mock_call(
            method, path, *, user_id, host, json=None, params=None, timeout=30.0
        ):
            captured.update(
                method=method,
                path=path,
                host=host,
                user_id=user_id,
                json=json,
                params=params,
            )
            return {
                "id": "evt-1",
                "htmlLink": "https://cal.google.com/evt-1",
                "hangoutLink": None,
            }

        return captured, mock_call

    async def test_calls_correct_endpoint(self, mock_capture):
        captured, mock_call = mock_capture
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            resp = await create_calendar_event_now(
                user_id="u",
                title="Sync",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
                attendees=["a@x.com", "b@x.com"],
                send_updates="all",
            )
        assert resp["id"] == "evt-1"
        assert captured["method"] == "POST"
        assert captured["path"] == "/calendar/v3/calendars/primary/events"
        assert captured["host"] == "www.googleapis.com"
        # F2 — sendUpdates 명시
        assert captured["params"]["sendUpdates"] == "all"
        # F3 — start/end 가 dateTime+timeZone 분리
        assert captured["json"]["start"] == {
            "dateTime": "2026-05-20T10:00:00",
            "timeZone": "Asia/Seoul",
        }
        assert captured["json"]["end"] == {
            "dateTime": "2026-05-20T11:00:00",
            "timeZone": "Asia/Seoul",
        }
        # attendees list[str] → list[dict]
        assert captured["json"]["attendees"] == [
            {"email": "a@x.com"},
            {"email": "b@x.com"},
        ]
        # MVP 기본 — Meet 없음
        assert "conferenceData" not in captured["json"]
        assert "conferenceDataVersion" not in captured["params"]

    async def test_create_meet_adds_conference_data(self, mock_capture):
        captured, mock_call = mock_capture
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await create_calendar_event_now(
                user_id="u",
                title="Sync",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
                create_meet=True,
            )
        assert captured["params"]["conferenceDataVersion"] == 1
        cd = captured["json"]["conferenceData"]
        assert cd["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"
        # requestId 는 unique uuid (str)
        assert isinstance(cd["createRequest"]["requestId"], str)
        assert len(cd["createRequest"]["requestId"]) > 8

    async def test_no_attendees_no_attendees_key(self, mock_capture):
        captured, mock_call = mock_capture
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await create_calendar_event_now(
                user_id="u",
                title="Solo",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
            )
        assert "attendees" not in captured["json"]

    async def test_description_optional(self, mock_capture):
        captured, mock_call = mock_capture
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            await create_calendar_event_now(
                user_id="u",
                title="t",
                start="2026-05-20T10:00:00",
                end="2026-05-20T11:00:00",
                timezone="Asia/Seoul",
                description="agenda details",
            )
        assert captured["json"]["description"] == "agenda details"


# ---------------------------------------------------------------------------
# _md_to_prose (stdlib re only — preserves newlines/bullets)
# ---------------------------------------------------------------------------


class TestMdToProse:
    def test_strips_heading_markers(self):
        from extension_modules.tools.google.inprocess.send import _md_to_prose

        out = _md_to_prose("# Title\n## Sub\nbody")
        assert out == "Title\nSub\nbody"

    def test_list_markers_become_bullets(self):
        from extension_modules.tools.google.inprocess.send import _md_to_prose

        out = _md_to_prose("- a\n* b\n+ c")
        assert out == "• a\n• b\n• c"

    def test_strips_bold_italic_code(self):
        from extension_modules.tools.google.inprocess.send import _md_to_prose

        out = _md_to_prose("**bold** and _italic_ and `code` and __x__ and *y*")
        assert out == "bold and italic and code and x and y"

    def test_link_becomes_text_with_url(self):
        from extension_modules.tools.google.inprocess.send import _md_to_prose

        out = _md_to_prose("see [docs](https://example.com) now")
        assert out == "see docs (https://example.com) now"

    def test_preserves_newlines_and_blank_lines(self):
        from extension_modules.tools.google.inprocess.send import _md_to_prose

        out = _md_to_prose("line1\n\nline2")
        assert out == "line1\n\nline2"


# ---------------------------------------------------------------------------
# create_drive_doc_now (2-call: Drive files.create + Docs batchUpdate)
# ---------------------------------------------------------------------------


class TestCreateDriveDocNow:
    def _kwargs_capture_mock(self, calls, *, fail_step2=False):
        # explicit-signature mock 재사용 금지 — **kwargs 캡처로 2-call 의 서로 다른
        # 시그니처를 모두 수용하고 호출 순서를 list 로 보존.
        from extension_modules.tools.google.inprocess._common import GoogleApiError

        async def mock_call(method, path, **kwargs):
            calls.append({"method": method, "path": path, **kwargs})
            if path == "/drive/v3/files":
                return {
                    "id": "doc-1",
                    "name": kwargs["json"]["name"],
                    "webViewLink": "https://docs.google.com/document/d/doc-1/edit",
                }
            # Step 2 — Docs batchUpdate
            if fail_step2:
                raise GoogleApiError(400, "INVALID_ARGUMENT")
            return {}

        return mock_call

    async def test_two_call_flow_and_endpoints(self):
        calls: list[dict] = []
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=self._kwargs_capture_mock(calls)),
        ):
            resp = await create_drive_doc_now(
                user_id="u", name="Q2 Report", content="# Heading\n\nbody"
            )
        assert len(calls) == 2
        # Step 1 — Drive files.create
        assert calls[0]["method"] == "POST"
        assert calls[0]["path"] == "/drive/v3/files"
        assert calls[0]["host"] == "www.googleapis.com"
        assert calls[0]["json"]["name"] == "Q2 Report"
        assert calls[0]["json"]["mimeType"] == "application/vnd.google-apps.document"
        assert "parents" not in calls[0]["json"]
        # webViewLink-fields gotcha — 기본 응답엔 webViewLink 가 없어 명시 필수.
        assert calls[0]["params"]["fields"] == "id,name,webViewLink"
        # Step 2 — Docs batchUpdate
        assert calls[1]["method"] == "POST"
        assert calls[1]["path"] == "/v1/documents/doc-1:batchUpdate"
        assert calls[1]["host"] == "docs.googleapis.com"
        req = calls[1]["json"]["requests"][0]["insertText"]
        # index=1 gotcha — index=0 은 초기 sectionBreak 에 닿아 400.
        assert req["location"]["index"] == 1
        assert "segmentId" not in req["location"]
        # 마크다운이 _md_to_prose 로 stripped (## 제거).
        assert req["text"] == "Heading\n\nbody"
        # 반환 구조
        assert resp["id"] == "doc-1"
        assert resp["name"] == "Q2 Report"
        assert resp["web_view_link"] == "https://docs.google.com/document/d/doc-1/edit"

    async def test_folder_id_adds_parents(self):
        calls: list[dict] = []
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(side_effect=self._kwargs_capture_mock(calls)),
        ):
            await create_drive_doc_now(
                user_id="u", name="n", content="c", folder_id="folder-9"
            )
        assert calls[0]["json"]["parents"] == ["folder-9"]

    async def test_step2_failure_surfaces_orphan_doc_id(self):
        # orphan 문서 (spec §4.1): Step1 성공 후 Step2 실패 시 빈 문서가 남음.
        # 자동삭제 안 함 — 예외에 doc_id + web_view_link 를 실어 confirm endpoint 가
        # DRIVE_CREATE_DOC_FAILED.after_state 에 기록 가능하게 한다.
        from extension_modules.tools.google.inprocess._common import GoogleApiError

        calls: list[dict] = []
        with patch(
            "extension_modules.tools.google.inprocess.send.call_google_api",
            new=AsyncMock(
                side_effect=self._kwargs_capture_mock(calls, fail_step2=True)
            ),
        ):
            with pytest.raises(GoogleApiError) as exc_info:
                await create_drive_doc_now(user_id="u", name="n", content="c")
        # Step1 은 성공했으므로 빈 문서가 남았고, 그 doc_id 를 추적 가능해야 함.
        assert exc_info.value.partial == {
            "id": "doc-1",
            "web_view_link": "https://docs.google.com/document/d/doc-1/edit",
            "name": "n",
        }


# ---------------------------------------------------------------------------
# compose_gmail_mime — markdown → HTML alternative + 깔끔한 평문 (개선)
# ---------------------------------------------------------------------------


class TestComposeGmailMimeMarkdown:
    def _parse(self, body: str):
        import email as _email
        from email import policy as _policy

        raw = compose_gmail_mime(to=["a@x.com"], subject="s", body=body)
        msg = _email.message_from_bytes(
            base64.urlsafe_b64decode(raw + "==="), policy=_policy.default
        )
        parts = {
            p.get_content_type(): p.get_content()
            for p in msg.walk()
            if not p.is_multipart()
        }
        return msg, parts

    def test_multipart_alternative_with_html(self):
        msg, parts = self._parse("**굵게** 그리고 일반")
        assert msg.is_multipart()
        assert "text/plain" in parts
        assert "text/html" in parts
        # HTML 대체본은 마크다운을 렌더 (** → <strong>)
        assert "<strong>굵게</strong>" in parts["text/html"]

    def test_plain_part_strips_markdown(self):
        _, parts = self._parse("# 제목\n- 항목1\n- 항목2")
        plain = parts["text/plain"]
        assert "#" not in plain  # heading 마커 제거
        assert "제목" in plain
        assert "•" in plain  # 리스트 → 불릿
        assert "- 항목1" not in plain  # raw 리스트 마커 제거

    def test_html_preserves_line_breaks(self):
        # 개행이 메일에서 살아있어야 (nl2br → <br>).
        _, parts = self._parse("첫째 줄\n둘째 줄")
        assert "<br" in parts["text/html"]
