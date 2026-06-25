"""KG 시맨틱 메모리 — kg_cypher 도구의 self-improving 레이어.

DbSphere 의 `extension_modules/dbsphere/memory/` 와 사이블링 구조. 5개 메모리
타입 (cypher_example, kg_schema_doc, kg_domain_doc, cypher_pattern,
cypher_negative) 을 단일 인덱스 (`kg_memory`) + `entity_type` 디스크리미네이터
로 운영한다. 사용량이 누적될수록 retrieval 이 prior 성공 cypher_example 을
surfacing → LLM 의 첫 시도 정확도와 토큰 효율이 함께 올라간다.
"""

from extension_modules.knowledge_graph.memory.judge import (
    JudgeVerdict,
    judge_cypher_result,
)
from extension_modules.knowledge_graph.memory.models import (
    CypherExampleMemory,
    CypherExampleSearchResult,
    CypherNegativeMemory,
    CypherNegativeSearchResult,
    CypherPatternMemory,
    CypherPatternSearchResult,
    KGDomainDocMemory,
    KGDomainDocSearchResult,
    KGSchemaDocMemory,
    KGSchemaDocSearchResult,
    KGUnifiedSearchResult,
    MemoryType,
)
from extension_modules.knowledge_graph.memory.schema_extractor import (
    KGSchemaExtractor,
    run_after_sync,
)
from extension_modules.knowledge_graph.memory.search_memory import SearchEngineKGMemory

__all__ = [
    "CypherExampleMemory",
    "CypherExampleSearchResult",
    "CypherNegativeMemory",
    "CypherNegativeSearchResult",
    "CypherPatternMemory",
    "CypherPatternSearchResult",
    "JudgeVerdict",
    "KGDomainDocMemory",
    "KGDomainDocSearchResult",
    "KGSchemaDocMemory",
    "KGSchemaDocSearchResult",
    "KGSchemaExtractor",
    "KGUnifiedSearchResult",
    "MemoryType",
    "SearchEngineKGMemory",
    "judge_cypher_result",
    "run_after_sync",
]
