"""Regression: AzureStorageProvider._extract_blob_name 의 nested-path 보존.

이전 구현은 ``urlparse(url).path.split("/")[-1]`` 로 마지막 segment 만 남겨
``document-templates/pptx/foo.pptx`` 같은 nested 키로 업로드된 blob 을 download/delete
에서 다시 찾지 못했다 (silent ResourceNotFoundError → caller fallback).

여기서는 SDK / 네트워크 의존성 없이 helper 만 단위 테스트한다.
"""

from open_webui.storage.provider import AzureStorageProvider


def _make_provider(container: str = "media") -> AzureStorageProvider:
    """SDK 초기화를 우회한 instance — _extract_blob_name 만 테스트하므로 안전."""
    instance = AzureStorageProvider.__new__(AzureStorageProvider)
    instance.container_name = container
    return instance


class TestExtractBlobName:
    def test_flat_url(self):
        """기존 동작 — flat key 는 그대로 마지막 segment 반환."""
        p = _make_provider("media")
        url = "https://acct.blob.core.windows.net/media/foo.pptx?sp=rw&sig=xxx"
        assert p._extract_blob_name(url) == "foo.pptx"

    def test_nested_url(self):
        """document_templates 라우터의 nested key 가 보존돼야 한다."""
        p = _make_provider("media")
        url = (
            "https://acct.blob.core.windows.net/media/"
            "document-templates/pptx/6fa197b4.pptx?sp=rw&sig=xxx"
        )
        assert p._extract_blob_name(url) == "document-templates/pptx/6fa197b4.pptx"

    def test_url_with_url_encoded_unicode(self):
        """unicode/공백 포함 키 — urldecode 가 적용돼 원본 키 복원."""
        p = _make_provider("media")
        url = "https://acct.blob.core.windows.net/media/foo%20bar.xlsx?sp=rw"
        assert p._extract_blob_name(url) == "foo bar.xlsx"

    def test_url_unrelated_container_returns_full_path(self):
        """URL 의 container 가 self.container_name 과 다르면 prefix 제거 skip — 안전 default."""
        p = _make_provider("media")
        url = "https://acct.blob.core.windows.net/other/foo.pptx?sp=rw"
        assert p._extract_blob_name(url) == "other/foo.pptx"

    def test_plain_filename(self):
        """URL 아닌 plain key — SAS '?' 제거 후 그대로."""
        p = _make_provider("media")
        assert p._extract_blob_name("foo.pptx") == "foo.pptx"
        assert p._extract_blob_name("foo.pptx?sig=xxx") == "foo.pptx"

    def test_plain_nested_key(self):
        """nested plain key 도 nested 그대로 유지 (이전엔 ['-1'] 만 남겼음)."""
        p = _make_provider("media")
        assert (
            p._extract_blob_name("document-templates/pptx/foo.pptx")
            == "document-templates/pptx/foo.pptx"
        )
