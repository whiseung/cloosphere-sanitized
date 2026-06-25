"""Drive tool builder 단위 테스트.

템플릿 = test_gmail (검색/읽기 다분기).  drive_create_doc 은 test_calendar 의
tool_does_not_call_external_api 패턴.  drive_get_content 가 response_mode='text'
를 넘기므로 모든 read-tool mock 은 **kwargs 캡처 (explicit-signature 금지).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from extension_modules.tools.google.inprocess._common import (
    BatchQuotaExceeded,
    GoogleApiError,
    GoogleReauthRequired,
)
from extension_modules.tools.google.inprocess._message_id import verify_message_id
from extension_modules.tools.google.inprocess.drive import (
    DRIVE_CONFIRM_MARKER,
    DRIVE_QUOTA_MARKER,
    DriveCreateDocArgs,
    DriveGetContentArgs,
    DriveSearchArgs,
    make_drive_tools,
)

# ---------------------------------------------------------------------------
# Pydantic args
# ---------------------------------------------------------------------------


class TestDriveArgs:
    def test_search_defaults(self):
        args = DriveSearchArgs(q="name contains 'report'")
        assert args.max_results == 10

    @pytest.mark.parametrize("bad_q", ["", "   "])
    def test_search_blank_q_rejects(self, bad_q):
        with pytest.raises(Exception):
            DriveSearchArgs(q=bad_q)

    @pytest.mark.parametrize("bad_max", [0, -1, 51, 1000])
    def test_search_max_out_of_range_rejects(self, bad_max):
        with pytest.raises(Exception):
            DriveSearchArgs(q="x", max_results=bad_max)

    def test_get_content_valid(self):
        args = DriveGetContentArgs(file_id="abc")
        assert args.file_id == "abc"

    def test_get_content_empty_rejects(self):
        with pytest.raises(Exception):
            DriveGetContentArgs(file_id="")

    def test_create_doc_valid(self):
        args = DriveCreateDocArgs(name="n", content="c")
        assert args.folder_id is None

    def test_create_doc_empty_name_rejects(self):
        with pytest.raises(Exception):
            DriveCreateDocArgs(name="", content="c")


# ---------------------------------------------------------------------------
# make_drive_tools factory
# ---------------------------------------------------------------------------


class TestMakeDriveTools:
    def test_returns_four_tools(self):
        tools = make_drive_tools("user-x")
        assert [t.name for t in tools] == [
            "drive_search",
            "drive_get_content",
            "drive_get_contents",
            "drive_create_doc",
        ]

    def test_search_get_async_create_sync(self):
        tools = {t.name: t for t in make_drive_tools("u")}
        assert tools["drive_search"].coroutine is not None
        assert tools["drive_get_content"].coroutine is not None
        assert tools["drive_get_contents"].coroutine is not None
        # create_doc: HITL preview only — sync
        assert tools["drive_create_doc"].coroutine is None


# ---------------------------------------------------------------------------
# drive_search
# ---------------------------------------------------------------------------


class TestDriveSearchTool:
    def _tool(self, user_id="u"):
        return [t for t in make_drive_tools(user_id) if t.name == "drive_search"][0]

    async def test_returns_files_with_mimetype(self):
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            calls.append(kwargs.get("params") or {})
            return {
                "files": [
                    {
                        "id": "f1",
                        "name": "Report",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                    {"id": "f2", "name": "data.csv", "mimeType": "text/csv"},
                ],
                "nextPageToken": "np",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(
                q="name contains 'report'", max_results=5
            )
        data = json.loads(result)
        # 두 패스가 같은 결과 반환 → dedupe 로 2개.
        assert len(data["results"]) == 2
        assert data["results"][0]["mimeType"] == (
            "application/vnd.google-apps.document"
        )
        assert data["results"][0]["id"] == "f1"
        assert data["results"][0]["name"] == "Report"
        assert data["next_page_token"] == "np"
        # Pass 1(첫 호출) = 사용자 q 그대로 + pageSize.
        assert calls[0]["q"] == "name contains 'report'"
        assert calls[0]["pageSize"] == 5
        assert calls[0]["corpora"] == "allDrives"

    async def test_reauth_required_aborts(self):
        async def mock_call(method, path, **kwargs):
            raise GoogleReauthRequired(user_id="u", reason="invalid_grant")

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="x")
        data = json.loads(result)
        assert data["error"] == "google_reauth_required"
        assert "hint" in data

    async def test_api_error_aborts(self):
        async def mock_call(method, path, **kwargs):
            raise GoogleApiError(403, "insufficient scope")

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="x")
        data = json.loads(result)
        assert data["error"] == "drive_api_error_403"


# ---------------------------------------------------------------------------
# drive_get_content — native export / text alt=media / binary metadata
# ---------------------------------------------------------------------------


class TestDriveGetContentTool:
    def _tool(self, user_id="u"):
        return [t for t in make_drive_tools(user_id) if t.name == "drive_get_content"][
            0
        ]

    async def test_native_doc_exports_text(self):
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            calls.append(
                {
                    "path": path,
                    "params": kwargs.get("params"),
                    "response_mode": kwargs.get("response_mode", "json"),
                }
            )
            if path == "/drive/v3/files/f1" and "export" not in path:
                return {
                    "id": "f1",
                    "name": "Doc",
                    "mimeType": "application/vnd.google-apps.document",
                }
            # export 경로 — response_mode='text' 로 호출돼야 함.
            return {"text": "exported plain text body"}

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="f1")
        data = json.loads(result)
        assert data["content"] == "exported plain text body"
        assert data["truncated"] is False
        # export 호출이 text 모드 + text/plain mimeType.
        export_call = calls[-1]
        assert export_call["path"] == "/drive/v3/files/f1/export"
        assert export_call["response_mode"] == "text"
        assert export_call["params"]["mimeType"] == "text/plain"

    async def test_native_spreadsheet_exports_csv(self):
        async def mock_call(method, path, **kwargs):
            if path == "/drive/v3/files/f2":
                return {
                    "id": "f2",
                    "name": "Sheet",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
            assert kwargs["params"]["mimeType"] == "text/csv"
            return {"text": "a,b\n1,2"}

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="f2")
        data = json.loads(result)
        assert data["content"] == "a,b\n1,2"

    async def test_text_like_uses_alt_media(self):
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            calls.append(
                {
                    "params": kwargs.get("params"),
                    "response_mode": kwargs.get("response_mode", "json"),
                }
            )
            if kwargs.get("params", {}).get("alt") != "media" and "export" not in path:
                # metadata 호출 (alt!=media)
                if kwargs.get("response_mode", "json") == "json":
                    return {
                        "id": "t1",
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                    }
            return {"text": "raw file text"}

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="t1")
        data = json.loads(result)
        assert data["content"] == "raw file text"
        # alt=media 호출이 text 모드.
        media_call = calls[-1]
        assert media_call["params"]["alt"] == "media"
        assert media_call["response_mode"] == "text"

    async def test_binary_returns_metadata_note_no_download(self):
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            calls.append(path)
            return {
                "id": "img1",
                "name": "photo.png",
                "mimeType": "image/png",
                "size": "123456",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="img1")
        data = json.loads(result)
        # 다운로드 없이 메타데이터 + note 만 — 호출은 metadata 1회.
        assert len(calls) == 1
        assert data["mimeType"] == "image/png"
        assert data["name"] == "photo.png"
        assert "binary" in data["note"].lower()
        assert "content" not in data

    async def test_native_outside_allowlist_falls_through_to_binary(self):
        # drawing/form/folder/shortcut 등 화이트리스트 밖 native → export 안 함, 4번 분기.
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            calls.append(path)
            return {
                "id": "d1",
                "name": "Diagram",
                "mimeType": "application/vnd.google-apps.drawing",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="d1")
        data = json.loads(result)
        assert len(calls) == 1  # metadata only, no export
        assert "note" in data
        assert "content" not in data

    async def test_empty_export_uses_get_text_default(self):
        # 검증된 함정: 빈 export 는 text 모드에서도 {} → resp.get("text","") 로 KeyError 회피.
        async def mock_call(method, path, **kwargs):
            if path == "/drive/v3/files/e1":
                return {
                    "id": "e1",
                    "name": "Empty",
                    "mimeType": "application/vnd.google-apps.document",
                }
            return {}  # 빈 export — text 키 없음

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="e1")
        data = json.loads(result)
        assert data["content"] == ""  # KeyError 안 남

    async def test_export_too_large_friendly_note(self):
        # native 파일은 size 가 없어 사전 캡 불가 → export 403 을 친화적 노트로 변환.
        async def mock_call(method, path, **kwargs):
            if path == "/drive/v3/files/big":
                return {
                    "id": "big",
                    "name": "Huge",
                    "mimeType": "application/vnd.google-apps.document",
                }
            raise GoogleApiError(403, "exportSizeLimitExceeded")

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="big")
        data = json.loads(result)
        assert data["error"] == "drive_export_too_large"

    async def test_output_cap_truncates(self):
        big = "x" * 60000

        async def mock_call(method, path, **kwargs):
            if path == "/drive/v3/files/c1":
                return {
                    "id": "c1",
                    "name": "Big",
                    "mimeType": "application/vnd.google-apps.document",
                }
            return {"text": big}

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="c1")
        data = json.loads(result)
        assert data["truncated"] is True
        assert len(data["content"]) == 50000


# ---------------------------------------------------------------------------
# drive_create_doc — HITL only, no external call
# ---------------------------------------------------------------------------


class TestDriveCreateDocTool:
    @pytest.fixture(autouse=True)
    def _reset_quota(self):
        from extension_modules.tools.google.inprocess._common import (
            _reset_write_quota_for_test,
        )

        _reset_write_quota_for_test()
        yield
        _reset_write_quota_for_test()

    def _create(self, user_id="u", **kwargs):
        tool = [t for t in make_drive_tools(user_id) if t.name == "drive_create_doc"][0]
        defaults = {"name": "Q2 Report", "content": "# Heading\n\nbody"}
        defaults.update(kwargs)
        return tool.func(**defaults)

    def test_returns_marker_plus_json(self):
        result = self._create()
        assert result.startswith(DRIVE_CONFIRM_MARKER)
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["confirmation_required"] is True
        assert payload["tool"] == "drive_create_doc"
        assert payload["risk_level"] == "low"

    def test_message_id_hmac_bound_to_user(self):
        result = self._create(user_id="user-x")
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert verify_message_id(payload["message_id"], "user-x") is True
        assert verify_message_id(payload["message_id"], "user-y") is False

    def test_tool_does_not_call_external_api(self):
        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api"
        ) as mock_api:
            self._create()
            mock_api.assert_not_called()

    def test_quota_exceeded_returns_quota_marker(self):
        with patch(
            "extension_modules.tools.google.inprocess.drive.enforce_write_quota",
            side_effect=BatchQuotaExceeded(
                user_id="u", tool_name="drive_create_doc", limit=3
            ),
        ):
            result = self._create()
        assert result.startswith(DRIVE_QUOTA_MARKER)
        payload = json.loads(result.split("json\n", 1)[1].rsplit("\n", 2)[0])
        assert payload["error"] == "batch_quota_exceeded"
        assert payload["limit"] == 3

    def test_conversation_id_threaded_to_quota(self):
        from extension_modules.tools.google.inprocess.drive import make_drive_tools

        tool = [
            t
            for t in make_drive_tools("user-x", conversation_id="conv-abc")
            if t.name == "drive_create_doc"
        ][0]
        with patch(
            "extension_modules.tools.google.inprocess.drive.enforce_write_quota"
        ) as quota_mock:
            tool.func(name="n", content="c")
        kwargs = quota_mock.call_args.kwargs
        assert kwargs["user_id"] == "user-x"
        assert kwargs["conversation_id"] == "conv-abc"
        assert kwargs["tool_name"] == "drive_create_doc"


# ---------------------------------------------------------------------------
# Package wiring — inprocess + google package re-exports + make_google_tools
# ---------------------------------------------------------------------------


class TestDriveWiring:
    def test_inprocess_reexports(self):
        from extension_modules.tools.google.inprocess import (
            create_drive_doc_now,
            make_drive_tools,
        )

        assert callable(create_drive_doc_now)
        assert callable(make_drive_tools)

    def test_google_package_reexports(self):
        from extension_modules.tools.google import make_drive_tools

        assert callable(make_drive_tools)

    def test_make_google_tools_drive_branch(self):
        from extension_modules.tools.google import make_google_tools

        tools = make_google_tools("u", {"drive"})
        assert [t.name for t in tools] == [
            "drive_search",
            "drive_get_content",
            "drive_get_contents",
            "drive_create_doc",
        ]

    def test_make_google_tools_drive_combined_with_gmail(self):
        from extension_modules.tools.google import make_google_tools

        names = [t.name for t in make_google_tools("u", {"gmail", "drive"})]
        assert "gmail_send" in names
        assert "drive_search" in names

    def test_make_google_tools_empty_excludes_drive(self):
        from extension_modules.tools.google import make_google_tools

        assert make_google_tools("u", set()) == []


# ---------------------------------------------------------------------------
# T1 — drive_get_content 바이너리(PDF/Office) 본문 추출
# ---------------------------------------------------------------------------

_XCFG = {"engine": "", "loader_kwargs": {}}


class TestDriveGetContentExtraction:
    """T1 — 바이너리 분기에서 PDF/Office 를 RAG Loader 로 추출."""

    def _tool(self, extraction_config=_XCFG, user_id="u"):
        return [
            t
            for t in make_drive_tools(user_id, extraction_config=extraction_config)
            if t.name == "drive_get_content"
        ][0]

    async def test_pdf_extracts_content(self):
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            calls.append(
                {
                    "mode": kwargs.get("response_mode", "json"),
                    "params": kwargs.get("params"),
                }
            )
            if kwargs.get("response_mode") == "bytes":
                return {"content_bytes": b"%PDF-1.4 fake binary"}
            return {
                "id": "p1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "size": "2048",
            }

        with (
            patch(
                "extension_modules.tools.google.inprocess.drive.call_google_api",
                new=AsyncMock(side_effect=mock_call),
            ),
            patch(
                "extension_modules.tools.google.inprocess.drive.extract_text_from_bytes",
                new=AsyncMock(
                    return_value={"content": "EXTRACTED PDF TEXT", "truncated": False}
                ),
            ),
        ):
            result = await self._tool().coroutine(file_id="p1")
        data = json.loads(result)
        assert data["content"] == "EXTRACTED PDF TEXT"
        assert data["truncated"] is False
        # 다운로드가 alt=media + bytes 모드로 1회 일어났는지.
        byte_calls = [c for c in calls if c["mode"] == "bytes"]
        assert len(byte_calls) == 1
        assert byte_calls[0]["params"]["alt"] == "media"

    async def test_oversized_binary_skips_download(self):
        modes: list[str] = []

        async def mock_call(method, path, **kwargs):
            modes.append(kwargs.get("response_mode", "json"))
            return {
                "id": "big",
                "name": "huge.pdf",
                "mimeType": "application/pdf",
                "size": str(50 * 1024 * 1024),  # 50MB > 20MB 임계
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_id="big")
        data = json.loads(result)
        assert "bytes" not in modes  # 다운로드 skip (메타데이터만)
        assert "content" not in data
        assert "note" in data

    async def test_extraction_disabled_returns_note(self):
        modes: list[str] = []

        async def mock_call(method, path, **kwargs):
            modes.append(kwargs.get("response_mode", "json"))
            return {
                "id": "p1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "size": "2048",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool(extraction_config=None).coroutine(file_id="p1")
        data = json.loads(result)
        assert "bytes" not in modes  # 추출 비활성 → 다운로드 안 함
        assert "content" not in data
        assert "note" in data


# ---------------------------------------------------------------------------
# T0/P2 — make_google_tools 가 extraction_config 를 drive/gmail builder 로 전달
# ---------------------------------------------------------------------------


class TestMakeGoogleToolsExtractionConfig:
    def test_threads_extraction_config_to_builders(self):
        from unittest.mock import patch as _patch

        cfg = {"engine": "tika", "loader_kwargs": {}}
        with (
            _patch(
                "extension_modules.tools.google.make_drive_tools", return_value=[]
            ) as mdt,
            _patch(
                "extension_modules.tools.google.make_gmail_tools", return_value=[]
            ) as mgt,
        ):
            from extension_modules.tools.google import make_google_tools

            make_google_tools("u", {"drive", "gmail"}, extraction_config=cfg)
        assert mdt.call_args.kwargs["extraction_config"] is cfg
        assert mgt.call_args.kwargs["extraction_config"] is cfg

    def test_default_none_extraction_config(self):
        # 미전달 시 builder 는 None 을 받아 추출 비활성 (하위호환).
        from unittest.mock import patch as _patch

        with _patch(
            "extension_modules.tools.google.make_drive_tools", return_value=[]
        ) as mdt:
            from extension_modules.tools.google import make_google_tools

            make_google_tools("u", {"drive"})
        assert mdt.call_args.kwargs.get("extraction_config") is None


# ---------------------------------------------------------------------------
# T3 — drive_search description 이 fullText(내용) 검색을 안내
# ---------------------------------------------------------------------------


def test_search_description_mentions_fulltext():
    from extension_modules.tools.google.inprocess.drive import (
        _DRIVE_SEARCH_DESCRIPTION,
    )

    assert "fullText contains" in _DRIVE_SEARCH_DESCRIPTION


# ---------------------------------------------------------------------------
# T4 — drive_get_contents 배치 읽기 (10-도구 한도 우회)
# ---------------------------------------------------------------------------


class TestDriveGetContentsBatch:
    def _tool(self, extraction_config=_XCFG, user_id="u"):
        return [
            t
            for t in make_drive_tools(user_id, extraction_config=extraction_config)
            if t.name == "drive_get_contents"
        ][0]

    async def test_reads_multiple_native_docs_in_one_call(self):
        async def mock_call(method, path, **kwargs):
            if path.endswith("/export"):
                fid = path.rsplit("/", 2)[-2]
                return {"text": f"BODY-{fid}"}
            fid = path.rsplit("/", 1)[-1]
            return {
                "id": fid,
                "name": f"{fid}.doc",
                "mimeType": "application/vnd.google-apps.document",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_ids=["a", "b", "c"])
        data = json.loads(result)
        assert len(data["results"]) == 3
        ids = {r["id"] for r in data["results"]}
        assert ids == {"a", "b", "c"}
        assert any(r.get("content") == "BODY-a" for r in data["results"])

    async def test_partial_failure_isolated(self):
        async def mock_call(method, path, **kwargs):
            if path.endswith("/files/bad"):
                raise GoogleApiError(404, "not found")
            if path.endswith("/export"):
                return {"text": "ok body"}
            fid = path.rsplit("/", 1)[-1]
            return {
                "id": fid,
                "name": f"{fid}.doc",
                "mimeType": "application/vnd.google-apps.document",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(file_ids=["good", "bad"])
        data = json.loads(result)
        # 최상위는 results — error 키 없음(집계 누락 방지).
        assert "error" not in data
        assert len(data["results"]) == 2


# ---------------------------------------------------------------------------
# T8 — drive_get_content 실 docx end-to-end (실제 Loader, extract mock 아님)
# ---------------------------------------------------------------------------


class TestDriveGetContentRealExtraction:
    async def test_real_docx_extracted_through_tool(self):
        docx = pytest.importorskip("docx")
        import io

        d = docx.Document()
        d.add_paragraph("Quarterly MPCI summary for overseas notice 해외 공지")
        buf = io.BytesIO()
        d.save(buf)
        docx_bytes = buf.getvalue()
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        async def mock_call(method, path, **kwargs):
            if kwargs.get("response_mode") == "bytes":
                return {"content_bytes": docx_bytes}
            return {
                "id": "d1",
                "name": "report.docx",
                "mimeType": mime,
                "size": str(len(docx_bytes)),
            }

        tool = [
            t
            for t in make_drive_tools(
                "u", extraction_config={"engine": "", "loader_kwargs": {}}
            )
            if t.name == "drive_get_content"
        ][0]
        # extract_text_from_bytes 는 patch 하지 않음 — 실제 RAG Loader 경로 검증.
        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await tool.coroutine(file_id="d1")
        data = json.loads(result)
        assert "MPCI" in data["content"]
        assert data["truncated"] is False


async def test_drive_get_contents_batch_total_budget():
    # T5/Fix C — 배치 총 출력이 cap 으로 bound (큰 항목 다수여도).
    from extension_modules.tools.google import make_drive_tools as _mdt

    big_text = "w" * 50000

    async def mock_call(method, path, **kwargs):
        if path.endswith("/export"):
            return {"text": big_text}
        fid = path.rsplit("/", 1)[-1]
        return {
            "id": fid,
            "name": f"{fid}.doc",
            "mimeType": "application/vnd.google-apps.document",
        }

    tool = [
        t
        for t in _mdt("u", extraction_config={"engine": "", "loader_kwargs": {}})
        if t.name == "drive_get_contents"
    ][0]
    with patch(
        "extension_modules.tools.google.inprocess.drive.call_google_api",
        new=AsyncMock(side_effect=mock_call),
    ):
        result = await tool.coroutine(file_ids=[str(i) for i in range(10)])
    data = json.loads(result)
    assert len(data["results"]) == 10
    noted = [r for r in data["results"] if "budget" in str(r.get("note", ""))]
    assert len(noted) > 0  # 일부는 budget 도달로 미읽음


# ---------------------------------------------------------------------------
# 버그수정 — drive_search 가 '나와 공유됨'(sharedWithMe) + 공유 드라이브 포함
# ---------------------------------------------------------------------------


class TestDriveSearchSharedScope:
    def _tool(self, user_id="u"):
        return [t for t in make_drive_tools(user_id) if t.name == "drive_search"][0]

    async def test_includes_shared_with_me_and_all_drives(self):
        calls: list[dict] = []

        async def mock_call(method, path, **kwargs):
            params = kwargs.get("params") or {}
            calls.append({"params": params})
            q = params.get("q", "")
            if "sharedWithMe" in q:
                # 공유받은 파일은 sharedWithMe 패스에서만 나온다.
                return {
                    "files": [
                        {
                            "id": "shared1",
                            "name": "동방 평택터미널 MSDS",
                            "mimeType": "application/pdf",
                        }
                    ]
                }
            return {
                "files": [
                    {"id": "own1", "name": "내 보고서", "mimeType": "text/plain"}
                ],
                "nextPageToken": "np",
            }

        with patch(
            "extension_modules.tools.google.inprocess.drive.call_google_api",
            new=AsyncMock(side_effect=mock_call),
        ):
            result = await self._tool().coroutine(q="fullText contains 'MSDS'")
        data = json.loads(result)
        ids = {r["id"] for r in data["results"]}
        # 공유받은 파일이 결과에 포함돼야 한다 (이번 버그의 핵심).
        assert "shared1" in ids
        assert "own1" in ids  # 소유 파일도 merge
        # 두 패스: allDrives(소유+공유드라이브) + sharedWithMe(공유받음).
        assert any((c["params"].get("corpora") == "allDrives") for c in calls)
        assert any("sharedWithMe" in (c["params"].get("q") or "") for c in calls)
        # 공유 드라이브 항목 접근에 필요한 플래그.
        assert all(
            c["params"].get("supportsAllDrives") in (True, "true") for c in calls
        )
