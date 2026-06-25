"""chunker.chunk_document 단위 테스트."""

from __future__ import annotations

from extension_modules.guide_agent.chunker import (
    HARD_MAX_TOKENS,
    MAX_TOKENS,
    chunk_document,
)


def _kwargs(**overrides):
    base = {
        "title": "테스트",
        "category": "test/page",
        "lang": "ko",
        "audience": "user",
        "file_path": "guide/docs/ko/test/page.mdx",
    }
    base.update(overrides)
    return base


def test_empty_content_returns_empty_list():
    assert chunk_document(content="", **_kwargs()) == []
    assert chunk_document(content="   \n  \n", **_kwargs()) == []


def test_no_h2_treats_whole_doc_as_one_chunk():
    chunks = chunk_document(content="짧은 본문 텍스트.", **_kwargs())
    assert len(chunks) == 1
    assert chunks[0].heading_path == "[테스트]"
    assert chunks[0].content == "짧은 본문 텍스트."
    assert chunks[0].category == "test/page"
    assert chunks[0].lang == "ko"


def test_h2_sections_become_separate_chunks():
    content = """## 섹션 A

본문 A 내용.

## 섹션 B

본문 B 내용."""
    chunks = chunk_document(content=content, **_kwargs())
    assert len(chunks) == 2
    paths = [c.heading_path for c in chunks]
    assert paths == ["[테스트] 섹션 A", "[테스트] 섹션 B"]
    assert "본문 A 내용" in chunks[0].content
    assert "본문 B 내용" in chunks[1].content


def test_prefix_before_first_h2_kept_as_chunk():
    content = """프리픽스 본문.

## 섹션 A

A 내용."""
    chunks = chunk_document(content=content, **_kwargs())
    assert len(chunks) == 2
    assert chunks[0].heading_path == "[테스트]"
    assert "프리픽스 본문" in chunks[0].content
    assert chunks[1].heading_path == "[테스트] 섹션 A"


def test_large_h2_split_by_h3():
    big_body = "x " * (MAX_TOKENS + 200)  # ~1700 tokens
    content = f"""## 큰 섹션

{big_body}

### 하위 A

A 본문 짧음.

### 하위 B

B 본문 짧음."""
    chunks = chunk_document(content=content, **_kwargs())
    assert len(chunks) >= 2
    paths = [c.heading_path for c in chunks]
    assert any("하위 A" in p for p in paths)
    assert any("하위 B" in p for p in paths)
    assert all(c.token_count <= HARD_MAX_TOKENS for c in chunks)


def test_oversized_h2_without_h3_uses_window_split():
    big = "단어 " * (MAX_TOKENS + 500)
    content = f"## 거대 섹션\n\n{big}"
    chunks = chunk_document(content=content, **_kwargs())
    assert len(chunks) >= 2
    assert all(c.token_count <= HARD_MAX_TOKENS for c in chunks)
    assert all(c.heading_path == "[테스트] 거대 섹션" for c in chunks)
    assert all("window_idx" in c.extra for c in chunks)


def test_code_fence_hashes_not_treated_as_headings():
    content = """## 실제 H2

```python
## 이것은 코드 안 주석
def foo():
    pass
```

다음 본문."""
    chunks = chunk_document(content=content, **_kwargs())
    assert len(chunks) == 1
    assert chunks[0].heading_path == "[테스트] 실제 H2"
    assert "## 이것은 코드 안 주석" in chunks[0].content


def test_metadata_propagation():
    chunks = chunk_document(
        content="## A\n본문",
        **_kwargs(audience="admin", lang="en", category="admin/users"),
    )
    assert len(chunks) == 1
    c = chunks[0]
    assert c.audience == "admin"
    assert c.lang == "en"
    assert c.category == "admin/users"
    assert c.file_path == "guide/docs/ko/test/page.mdx"
    assert c.token_count > 0


def test_token_count_accuracy():
    chunks = chunk_document(content="hello world", **_kwargs())
    assert chunks[0].token_count == 2  # "hello world" → 2 tokens in cl100k_base
