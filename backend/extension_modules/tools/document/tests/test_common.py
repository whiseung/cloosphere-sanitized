"""Document generation common helpers tests."""

from extension_modules.tools.document._common import DocumentToolOutput


class TestDocumentToolOutput:
    def test_required_fields(self):
        out = DocumentToolOutput(
            file_id="abc123",
            filename="report.pptx",
            download_url="/api/v1/files/abc123/content",
            size_bytes=1024,
        )
        assert out.file_id == "abc123"
        assert out.filename == "report.pptx"
        assert out.download_url == "/api/v1/files/abc123/content"
        assert out.size_bytes == 1024


from extension_modules.tools.document._common import sanitize_filename


class TestSanitizeFilename:
    def test_passes_simple_name(self):
        assert sanitize_filename("report") == "report"

    def test_strips_path_traversal(self):
        assert sanitize_filename("../../etc/passwd") == ".._.._etc_passwd"

    def test_replaces_special_chars(self):
        assert sanitize_filename("a/b\\c:d*e?f") == "a_b_c_d_e_f"

    def test_keeps_korean(self):
        assert sanitize_filename("월간보고서") == "월간보고서"

    def test_keeps_underscores_and_dashes_and_dots(self):
        assert sanitize_filename("report_v1-final.draft") == "report_v1-final.draft"

    def test_truncates_to_max_length(self):
        result = sanitize_filename("a" * 200)
        assert len(result) == 100

    def test_empty_input_falls_back(self):
        assert sanitize_filename("") == "document"

    def test_only_invalid_chars_become_underscores(self):
        assert sanitize_filename("///***") == "______"


from io import BytesIO
from unittest.mock import MagicMock, patch

from extension_modules.tools.document._common import save_to_files


class TestSaveToFiles:
    def _patches(self, file_id="file-uuid-123", user_email="hong@cloocus.com"):
        """공통 patch 헬퍼 — Storage / Files / Users 를 모두 mocking."""
        fake_file_model = MagicMock(id=file_id)
        fake_user = MagicMock(email=user_email)
        return (
            patch("extension_modules.tools.document._common.Storage"),
            patch("extension_modules.tools.document._common.Files"),
            patch("extension_modules.tools.document._common.Users"),
            fake_file_model,
            fake_user,
        )

    def test_saves_with_canonical_filename(self):
        buffer = BytesIO(b"FAKE_PPTX_CONTENT")
        p_storage, p_files, p_users, fake_file, fake_user = self._patches()
        with p_storage as MockStorage, p_files as MockFiles, p_users as MockUsers:
            MockStorage.upload_file.return_value = (
                b"FAKE_PPTX_CONTENT",
                "/data/uploads/canonical.pptx",
            )
            MockFiles.insert_new_file.return_value = fake_file
            MockUsers.get_user_by_id.return_value = fake_user

            result = save_to_files(
                user_id="user-1",
                filename="report.pptx",
                buffer=buffer,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )

            # Canonical filename: {base}_{email}_{yymmddhhmmss}.{ext}
            import re

            assert re.match(
                r"^report_hong_cloocus\.com_\d{12}\.pptx$", result.filename
            ), f"got {result.filename!r}"
            assert result.file_id == "file-uuid-123"
            assert "/api/v1/files/file-uuid-123/public?" in result.download_url
            assert result.size_bytes == len(b"FAKE_PPTX_CONTENT")

            # Storage.upload_file 와 Files.insert_new_file 이 받은 filename 도
            # canonical (DB filename = storage key 일치)
            storage_args, _ = MockStorage.upload_file.call_args
            assert storage_args[1] == result.filename

            form = MockFiles.insert_new_file.call_args[0][1]
            assert form.filename == result.filename
            MockUsers.get_user_by_id.assert_called_once_with("user-1")

    def test_unknown_user_falls_back_to_user_id_then_anonymous(self):
        buffer = BytesIO(b"X")
        p_storage, p_files, p_users, fake_file, _ = self._patches()
        with p_storage as MockStorage, p_files as MockFiles, p_users as MockUsers:
            MockStorage.upload_file.return_value = (b"X", "/data/uploads/x.xlsx")
            MockFiles.insert_new_file.return_value = fake_file
            MockUsers.get_user_by_id.return_value = None  # user lookup fail

            result = save_to_files(
                user_id="ghost-user-id",
                filename="x.xlsx",
                buffer=buffer,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # email 없으면 user_id 가 그 자리에 들어감 (sanitize 후)
            assert "ghost-user-id" in result.filename
            assert result.filename.endswith(".xlsx")

    def test_dangerous_filename_is_sanitized(self):
        buffer = BytesIO(b"X")
        p_storage, p_files, p_users, fake_file, fake_user = self._patches(
            user_email="u@x.kr"
        )
        with p_storage as MockStorage, p_files as MockFiles, p_users as MockUsers:
            MockStorage.upload_file.return_value = (b"X", "/data/uploads/canonical")
            MockFiles.insert_new_file.return_value = fake_file
            MockUsers.get_user_by_id.return_value = fake_user

            result = save_to_files(
                user_id="user-1",
                filename="../../etc/passwd.docx",
                buffer=buffer,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

            # path traversal 슬래시는 _ 로, dots 는 유지, 이메일+ts 추가
            assert result.filename.startswith(".._.._etc_passwd_u_x.kr_")
            assert result.filename.endswith(".docx")

    def test_files_insert_failure_raises(self):
        buffer = BytesIO(b"X")
        p_storage, p_files, p_users, _, fake_user = self._patches()
        with p_storage as MockStorage, p_files as MockFiles, p_users as MockUsers:
            MockStorage.upload_file.return_value = (b"X", "/data/uploads/x.xlsx")
            MockFiles.insert_new_file.return_value = None  # DB 실패 시뮬
            MockUsers.get_user_by_id.return_value = fake_user

            import pytest

            with pytest.raises(RuntimeError, match="Files 테이블 저장 실패"):
                save_to_files(
                    user_id="user-1",
                    filename="x.xlsx",
                    buffer=buffer,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


from extension_modules.tools.document._common import format_tool_response


class TestFormatToolResponse:
    def test_returns_markdown_with_link_and_filename(self):
        out = DocumentToolOutput(
            file_id="abc",
            filename="report.xlsx",
            download_url="/api/v1/files/abc/content",
            size_bytes=2048,
        )
        text = format_tool_response(out)
        assert isinstance(text, str)
        assert "report.xlsx" in text
        assert "/api/v1/files/abc/content" in text
        # 마크다운 링크 형식 — LLM 이 그대로 인용 가능
        assert "[report.xlsx](/api/v1/files/abc/content)" in text

    def test_includes_size_in_kb(self):
        out = DocumentToolOutput(
            file_id="x",
            filename="d.docx",
            download_url="/api/v1/files/x/content",
            size_bytes=1536,  # 1.5 KB
        )
        text = format_tool_response(out)
        assert "1.5 KB" in text

    def test_starts_with_marker_for_stream_detection(self):
        # UnifiedAgent 가 ToolMessage 첫 줄의 마커로 detection 하여 SSE yield
        out = DocumentToolOutput(
            file_id="x",
            filename="d.pptx",
            download_url="/api/v1/files/x/content",
            size_bytes=100,
        )
        text = format_tool_response(out)
        assert text.startswith("[document_tool] 파일 생성 완료")
