"""
Data models for DbSphere V2 Memory system.

Supports multiple memory types following Vanna.ai's learning approach:
- SQL Memory: Question-SQL pairs (existing)
- DDL Schema: Table/column definitions
- Documentation: Business rules, terms, context
- SQL Example: Annotated SQL examples
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MemoryType(str, Enum):
    """Types of memory stored in DbSphere memory system."""

    SQL_MEMORY = "sql_memory"  # Question-SQL pairs (existing)
    DDL_SCHEMA = "ddl_schema"  # Table/column definitions
    DOCUMENTATION = "documentation"  # Business rules, terms, context
    SQL_EXAMPLE = "sql_example"  # Annotated SQL examples


class MemoryOrigin(str, Enum):
    """few-shot(sql_memory)이 어떻게 생성됐는지 — 생성자 구분 배지/분석용.

    metadata['source'](tenant 격리 — schema_extraction 식별)와는 별개의 additive 필드.
    embed short-circuit 으로 origin 은 '최초 producer 기준'으로 고정된다(writer-wins).
    """

    LLM_AUTO = "llm_auto"  # 에이전트가 성공 쿼리를 자동저장 (운영 지배 경로)
    USER_MANUAL = "user_manual"  # 사용자가 메모리 탭에서 수동등록
    SCHEMA_EXTRACTION = "schema_extraction"  # 스키마 추출 시 생성된 공유 Q&A
    UNKNOWN = "unknown"  # legacy(origin 미기록) — 표시용 폴백


class DocumentationType(str, Enum):
    """Types of documentation memory."""

    TERM = "term"  # Business term definition
    RULE = "rule"  # Business rule or constraint
    CONTEXT = "context"  # General context about the data


@dataclass
class ColumnDetail:
    """Detailed information about a database column."""

    name: str
    data_type: str
    description: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_table: Optional[str] = None
    foreign_column: Optional[str] = None
    is_nullable: bool = True
    default_value: Optional[str] = None


@dataclass
class DDLMemory:
    """Memory for DDL/Schema information with LLM-generated descriptions."""

    memory_id: str
    ddl_statement: str
    table_name: str
    schema_name: Optional[str] = None
    columns: List[ColumnDetail] = field(default_factory=list)
    table_description: Optional[str] = None  # LLM-generated description
    relationships: List[str] = field(default_factory=list)  # Related tables
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DDLMemorySearchResult:
    """Search result for DDL memory."""

    memory: DDLMemory
    similarity_score: float
    rank: int


@dataclass
class DocumentationMemory:
    """Memory for business documentation and context."""

    memory_id: str
    content: str
    doc_type: str  # 'term', 'rule', 'context'
    title: Optional[str] = None
    related_tables: List[str] = field(default_factory=list)
    related_columns: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentationSearchResult:
    """Search result for documentation memory."""

    memory: DocumentationMemory
    similarity_score: float
    rank: int


@dataclass
class SqlExampleMemory:
    """Memory for annotated SQL examples."""

    memory_id: str
    sql: str
    description: str
    use_case: Optional[str] = None
    related_tables: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SqlExampleSearchResult:
    """Search result for SQL example memory."""

    memory: SqlExampleMemory
    similarity_score: float
    rank: int


@dataclass
class UnifiedSearchResult:
    """Combined search results from all memory types."""

    sql_memories: List["SqlMemorySearchResult"] = field(default_factory=list)
    ddl_memories: List[DDLMemorySearchResult] = field(default_factory=list)
    documentation: List[DocumentationSearchResult] = field(default_factory=list)
    sql_examples: List[SqlExampleSearchResult] = field(default_factory=list)


# Re-export SqlMemory and SqlMemorySearchResult from search_memory for convenience
# These are kept in search_memory.py for backward compatibility
@dataclass
class SqlMemory:
    """Represents a stored SQL query memory."""

    memory_id: str
    question: str
    sql: str
    timestamp: Optional[str] = None
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SqlMemorySearchResult:
    """Search result containing a memory and its similarity score."""

    memory: SqlMemory
    similarity_score: float
    rank: int


@dataclass
class TableDetails:
    """LLM-extracted table details for schema enrichment."""

    table_name: str
    ddl: str
    description: str
    columns: List[ColumnDetail]
    sample_data_summary: Optional[str] = None
    data_patterns: List[str] = field(default_factory=list)
    related_tables: List[str] = field(default_factory=list)


@dataclass
class InferredJoin:
    """A candidate fact→dimension JOIN inferred from column semantics.

    검증된 FK 가 아니라 구조 신호(PK set + 컬럼명 동일성)로 *추론*한 후보다.
    verified FK 와 엄격히 분리해 2차 라벨(candidate) 섹션으로만 렌더된다 —
    약한 모델이 추론을 권위적 FK 로 오인해 환각 JOIN 을 내지 않도록.

    ``column_pairs`` 는 ``[(source_col, target_col), ...]`` — 단일 컬럼 후보는
    1쌍, 복합 PK 대상(G5)은 PK 전체를 cover 하는 N쌍을 한 InferredJoin 에 담아
    verified 의 단일 ``ON a.c1=b.c1 AND a.c2=b.c2`` 렌더(1:1-pair/cartesian
    fallback)를 그대로 재사용한다.
    """

    source_table: str
    target_table: str
    column_pairs: List[Tuple[str, str]]
    confidence: str = "candidate"
    reason: str = ""
