"""
Glossary - 용어집 검색 엔진 연동 모듈

워크스페이스 > 용어집에서 입력된 용어를 검색 엔진에 색인합니다.

- 검색 엔진: 관리자 > 설정 > 검색 엔진 설정 사용
- 임베딩: 관리자 > 설정 > 문서의 RAG 임베딩 설정 사용
- 인덱스명: default_glossary (고정)
- collection: glossary_id로 용어집별 구분

Usage - 색인:
    >>> from extension_modules.glossary import GlossaryIndexService, GlossaryEntryInput
    >>>
    >>> service = GlossaryIndexService(request.app)
    >>> entry = GlossaryEntryInput(
    ...     id="entry_123",
    ...     glossary_id="glossary_456",
    ...     term="EBITDA",
    ...     synonyms=["에비타", "에비다"],
    ...     definition="세전·이자지급전·감가상각전 영업이익",
    ...     examples=["이번 분기 EBITDA는 전년 대비 15% 증가했다."],
    ...     category="재무",
    ... )
    >>> await service.index_entry(entry)

Usage - LangChain Tool:
    >>> from extension_modules.glossary import create_glossary_lookup_tool
    >>>
    >>> tool = create_glossary_lookup_tool(request.app)
    >>> result = await tool.ainvoke({"query": "RAG", "top_k": 3})
"""

from .models import GlossaryEntryInput, GlossarySearchResult
from .service import GlossaryIndexService
from .tools import GlossaryLookupInput, GlossaryTools, create_glossary_lookup_tool

__all__ = [
    # Models
    "GlossaryEntryInput",
    "GlossarySearchResult",
    "GlossaryLookupInput",
    # Services
    "GlossaryIndexService",
    # Tools
    "GlossaryTools",
    "create_glossary_lookup_tool",
]
