"""Guide Q&A Agent Tools (BM25 in-memory + cleaned MDX).

3개 도구:
- `list_guide_categories` — YAML 카탈로그 기반, 사용자 role 따라 admin 카테고리 필터
- `get_guide_section` — 특정 카테고리의 cleaned MDX 전문 반환
- `search_guides` — BM25 in-memory 검색 + lang/audience 필터 + 카테고리 다양성

벡터 DB·임베딩 호출 없음. startup 시 자동 인덱스 빌드, 콘텐츠 hash 변경 시 자동 재빌드.
"""

from __future__ import annotations

import logging
from typing import Any, List

from extension_modules.guide_agent.bm25_retriever import search as bm25_search
from extension_modules.guide_agent.catalog import (
    accessible_entries,
    entry_by_id,
    resolve_doc_path,
)
from extension_modules.guide_agent.mdx_cleaner import clean_mdx
from langchain_core.tools import StructuredTool
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

DEFAULT_TOP_K = 8


def _detect_lang_code(text: str) -> str:
    """ko/en 판정 (langdetect). 그 외/실패 시 ko 기본."""
    if not text or not text.strip():
        return "ko"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(text.strip()[:500])
        return code if code in {"ko", "en"} else "ko"
    except Exception:
        return "ko"


def _read_section(file_path: str) -> str:
    """카탈로그의 file_ko 또는 file_en 경로 → cleaned plaintext.

    `resolve_doc_path` 가 guide/docs/ 외부 경로를 차단한다.
    """
    abs_path = resolve_doc_path(file_path)
    if abs_path is None:
        return ""
    text = abs_path.read_text(encoding="utf-8")
    cleaned = clean_mdx(text, source=str(abs_path), strict=False)
    return cleaned.content


def list_guide_categories_for(role: str) -> str:
    """role 별 가이드 카테고리 목록 (Markdown)."""
    entries = accessible_entries(role)
    if not entries:
        return "사용 가능한 가이드 카테고리가 없습니다."
    lines = []
    for entry in entries:
        title = entry.get("title_ko") or entry.get("title_en") or entry["id"]
        desc = entry.get("description_ko") or entry.get("description_en") or ""
        lines.append(f"- **{entry['id']}**: {title} — {desc}")
    return "## 가이드 카테고리\n\n" + "\n".join(lines)


def get_guide_section_for(category: str, role: str, lang: str = "ko") -> str:
    """category 의 ko 또는 en MDX 전문(cleaned).

    role 이 admin 이 아닌 경우 admin/* + monitoring/* 카테고리는 차단.
    """
    entry = entry_by_id(category, role)
    if not entry:
        return f"카테고리 '{category}' 를 찾을 수 없거나 접근 권한이 없습니다."
    file_path = (
        entry.get(f"file_{lang}") or entry.get("file_ko") or entry.get("file_en")
    )
    if not file_path:
        return f"카테고리 '{category}' 의 콘텐츠 파일을 찾을 수 없습니다."
    body = _read_section(file_path)
    if not body:
        return f"카테고리 '{category}' 본문을 읽지 못했습니다."
    return body


def _format_search_results(results: list) -> str:
    if not results:
        return "검색 결과가 없습니다. 더 구체적인 키워드로 재시도하거나 list_guide_categories 로 카테고리를 확인하세요."
    blocks = []
    for chunk, score in results:
        header = f"### {chunk.heading_path}\n> 출처: [{chunk.category}] ({chunk.lang}) · score={score:.2f}"
        blocks.append(f"{header}\n\n{chunk.content}")
    return "\n\n---\n\n".join(blocks)


def search_guides_for(query: str, *, role: str, top_k: int = DEFAULT_TOP_K) -> str:
    """BM25 검색 + audience/lang 필터 + 카테고리 다양성."""
    if not query or not query.strip():
        return "검색어가 비어있습니다."
    lang = _detect_lang_code(query)
    results = bm25_search(query, role=role, lang=lang, top_k=top_k)
    return _format_search_results(results)


# ===== Tool Input Schemas =====


class ListCategoriesInput(BaseModel):
    """가이드 카테고리 목록 조회 (인자 없음)."""


class GetGuideSectionInput(BaseModel):
    """특정 가이드 섹션 전문 조회."""

    category: str = Field(
        description=(
            "가이드 카테고리 ID (canonical path). 예: 'chat/overview', "
            "'workspace/agents', 'admin/users', 'getting-started/first-chat'."
        )
    )


class SearchGuidesInput(BaseModel):
    """가이드 키워드/구문 검색."""

    query: str = Field(description="검색 질문 또는 키워드 구문 (한국어/영어 모두 가능)")


# ===== Tool Factory =====


def create_guide_tools(*, role: str = "user", **_: Any) -> List[StructuredTool]:
    """가이드 Q&A 에이전트용 도구.

    Args:
        role: 사용자 role ('admin' | 'user') — 카테고리/검색 결과 audience 필터링
        **_: 호환성 (이전 시그니처 app/user_id 무시)

    Returns:
        [search_guides, list_guide_categories, get_guide_section]
    """

    def _list_categories() -> str:
        return list_guide_categories_for(role)

    def _get_section(category: str) -> str:
        return get_guide_section_for(category, role)

    def _search(query: str) -> str:
        return search_guides_for(query, role=role)

    return [
        StructuredTool.from_function(
            func=_search,
            name="search_guides",
            description=(
                "가이드를 BM25 키워드 + 한글 bigram 검색합니다 (top_k=8, 카테고리 다양성). "
                "사용자 질문이 들어오면 먼저 이 도구를 호출하세요."
            ),
            args_schema=SearchGuidesInput,
        ),
        StructuredTool.from_function(
            func=_get_section,
            name="get_guide_section",
            description=(
                "특정 카테고리의 가이드 전문을 반환합니다. category ID 는 canonical path "
                "(예: 'chat/overview', 'workspace/agents', 'admin/users') 입니다. "
                "search_guides 결과에서 더 자세한 본문이 필요할 때 사용."
            ),
            args_schema=GetGuideSectionInput,
        ),
        StructuredTool.from_function(
            func=_list_categories,
            name="list_guide_categories",
            description=(
                "사용자가 접근 가능한 가이드 카테고리 목록을 반환합니다. "
                "어떤 카테고리가 있는지 사용자에게 안내할 때 호출."
            ),
            args_schema=ListCategoriesInput,
        ),
    ]


__all__ = [
    "create_guide_tools",
    "search_guides_for",
    "list_guide_categories_for",
    "get_guide_section_for",
]
