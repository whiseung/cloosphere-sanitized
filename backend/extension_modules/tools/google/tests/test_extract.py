"""``_extract.py`` 단위 테스트 — 바이너리(PDF/Office) 본문 추출 헬퍼.

T0.2: drive_get_content/gmail_get 의 바이너리 분기가 기존 RAG ``Loader`` 로
PDF/Office 텍스트를 추출하기 위한 공통 헬퍼.  실 Loader(unstructured/pypdf +
외부 엔진) 는 무겁고 외부 의존이므로 동기 로더(`_load_text_sync`)를 patch 해
오케스트레이션(temp 기록·cap·정리·에러 graceful)을 검증한다.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import extension_modules.tools.google.inprocess._extract as ex


class TestIsExtractable:
    def test_pdf_office_true(self):
        assert ex.is_extractable("application/pdf")
        assert ex.is_extractable(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )  # docx
        assert ex.is_extractable(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )  # xlsx
        assert ex.is_extractable(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )  # pptx

    def test_image_and_native_false(self):
        assert not ex.is_extractable("image/png")
        assert not ex.is_extractable("image/jpeg")
        assert not ex.is_extractable("application/vnd.google-apps.folder")
        assert not ex.is_extractable("")


class TestResolveExtractionConfig:
    def test_reads_engine_and_kwargs(self):
        cfg = SimpleNamespace(
            CONTENT_EXTRACTION_ENGINE="tika",
            TIKA_SERVER_URL="http://tika:9998",
            DOCLING_SERVER_URL="",
            PDF_EXTRACT_IMAGES=False,
            DOCUMENT_INTELLIGENCE_ENDPOINT="",
            DOCUMENT_INTELLIGENCE_KEY="",
            MISTRAL_OCR_API_KEY="",
        )
        resolved = ex.resolve_extraction_config(cfg)
        assert resolved["engine"] == "tika"
        assert resolved["loader_kwargs"]["TIKA_SERVER_URL"] == "http://tika:9998"

    def test_none_config_returns_none(self):
        assert ex.resolve_extraction_config(None) is None

    def test_missing_attrs_default_gracefully(self):
        # 일부 키가 없는 config 객체여도 예외 없이 빈 값으로.
        resolved = ex.resolve_extraction_config(SimpleNamespace())
        assert resolved["engine"] == ""
        assert isinstance(resolved["loader_kwargs"], dict)


_CFG = {"engine": "", "loader_kwargs": {}}


class TestExtractTextFromBytes:
    async def test_returns_extracted_text(self, monkeypatch):
        monkeypatch.setattr(
            ex, "_load_text_sync", lambda filename, mime, path, cfg: "hello world"
        )
        result = await ex.extract_text_from_bytes(
            b"%PDF-1.4 data", "doc.pdf", "application/pdf", extraction_config=_CFG
        )
        assert result["content"] == "hello world"
        assert result["truncated"] is False

    async def test_caps_long_text(self, monkeypatch):
        monkeypatch.setattr(
            ex, "_load_text_sync", lambda *a, **k: "x" * (ex.MAX_EXTRACT_CHARS + 5000)
        )
        result = await ex.extract_text_from_bytes(
            b"data", "big.pdf", "application/pdf", extraction_config=_CFG
        )
        assert len(result["content"]) == ex.MAX_EXTRACT_CHARS
        assert result["truncated"] is True

    async def test_cleans_temp_file(self, monkeypatch):
        captured = {}

        def fake_load(filename, mime, path, cfg):
            captured["path"] = path
            assert os.path.exists(path)  # 로드 중엔 temp 존재
            return "ok"

        monkeypatch.setattr(ex, "_load_text_sync", fake_load)
        await ex.extract_text_from_bytes(
            b"data", "f.pdf", "application/pdf", extraction_config=_CFG
        )
        assert not os.path.exists(captured["path"])  # 호출 후 정리됨

    async def test_loader_error_is_graceful(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("unstructured boom")

        monkeypatch.setattr(ex, "_load_text_sync", boom)
        result = await ex.extract_text_from_bytes(
            b"data", "f.pdf", "application/pdf", extraction_config=_CFG
        )
        assert result["content"] == ""
        assert result["truncated"] is False
        assert result.get("error")  # graceful note, 예외 전파 X

    async def test_empty_bytes_returns_empty(self, monkeypatch):
        # 빈 바이트는 추출 시도 없이 빈 결과.
        called = {"n": 0}

        def should_not_call(*a, **k):
            called["n"] += 1
            return ""

        monkeypatch.setattr(ex, "_load_text_sync", should_not_call)
        result = await ex.extract_text_from_bytes(
            b"", "f.pdf", "application/pdf", extraction_config=_CFG
        )
        assert result["content"] == ""
        assert called["n"] == 0

    async def test_none_config_disables_extraction(self, monkeypatch):
        monkeypatch.setattr(ex, "_load_text_sync", lambda *a, **k: "should not reach")
        result = await ex.extract_text_from_bytes(
            b"data", "f.pdf", "application/pdf", extraction_config=None
        )
        assert result["content"] == ""
        assert result.get("error")
