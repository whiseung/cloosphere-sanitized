"""KG 시맨틱 메모리 데이터 모델.

5개 메모리 타입의 in-memory shape (저장된 검색 인덱스 row 와 1:1 대응 아님 —
인덱스는 collection / entity_type 으로만 구분되고 나머지는 metadata JSON 으로
나가지만, 호출 코드 측에서는 타입별 dataclass 로 받는 게 안전).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryType(str, Enum):
    """KG 메모리 인덱스의 entity_type 값."""

    CYPHER_EXAMPLE = "cypher_example"  # Question-Cypher 쌍 (positive)
    KG_SCHEMA_DOC = "kg_schema_doc"  # 노드/엣지 타입 LLM 설명
    KG_DOMAIN_DOC = "kg_domain_doc"  # KG-level 비즈니스 규칙 / AGE caveat
    CYPHER_PATTERN = "cypher_pattern"  # 정형 트래버설 템플릿
    CYPHER_NEGATIVE = "cypher_negative"  # AGE 에러 + 수정 페어 (negative learning)


class DomainDocType(str, Enum):
    """kg_domain_doc 의 doc_type 분류."""

    RULE = "rule"
    CONVENTION = "convention"
    CAVEAT = "caveat"


class SchemaRole(str, Enum):
    """kg_schema_doc 의 schema_role 분류."""

    NODE = "node"
    EDGE = "edge"


# ── Cypher Example ────────────────────────────────────────────────────────


@dataclass
class CypherExampleMemory:
    """Question + 성공 Cypher 페어 (사용할수록 정확도 향상의 핵심)."""

    memory_id: str
    question: str
    cypher: str
    confidence: float = 0.0
    hit_count: int = 1
    last_used: Optional[str] = None
    normalized_question: Optional[str] = None
    referenced_node_types: List[str] = field(default_factory=list)
    referenced_edge_types: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None
    stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CypherExampleSearchResult:
    memory: CypherExampleMemory
    similarity_score: float
    final_score: float  # 0.6*sim + 0.25*confidence + 0.15*log(1+hit_count)
    rank: int


# ── KG Schema Doc ─────────────────────────────────────────────────────────


@dataclass
class KGSchemaDocMemory:
    """노드/엣지 타입에 대한 LLM 생성 설명 (DbSphere ddl_schema 대응)."""

    memory_id: str
    type_name: str  # 예: "term", "has_active_ingredient"
    schema_role: str  # SchemaRole.NODE | EDGE
    description: str
    sample_labels: List[str] = field(default_factory=list)
    sample_props: List[str] = field(default_factory=list)
    degree_stats: Dict[str, Any] = field(default_factory=dict)
    source_hash: Optional[str] = None  # 재생성 dedup 키
    timestamp: Optional[str] = None
    stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KGSchemaDocSearchResult:
    memory: KGSchemaDocMemory
    similarity_score: float
    rank: int


# ── KG Domain Doc ─────────────────────────────────────────────────────────


@dataclass
class KGDomainDocMemory:
    """비즈니스 규칙 / 컨벤션 / AGE caveat 등 KG-level 텍스트 (관리자 큐레이션 + 자동 시드)."""

    memory_id: str
    title: str
    content: str
    doc_type: str  # DomainDocType
    related_node_types: List[str] = field(default_factory=list)
    related_edge_types: List[str] = field(default_factory=list)
    author: Optional[str] = None  # "system" | user_id
    timestamp: Optional[str] = None
    stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KGDomainDocSearchResult:
    memory: KGDomainDocMemory
    similarity_score: float
    rank: int


# ── Cypher Pattern ────────────────────────────────────────────────────────


@dataclass
class CypherPatternMemory:
    """정형 트래버설 템플릿 — cypher_example 클러스터에서 승격된 재사용 패턴."""

    memory_id: str
    name: str
    description: str
    template_cypher: str
    slots: List[str] = field(default_factory=list)
    use_case: Optional[str] = None
    candidate_id: Optional[str] = None  # KGCandidate.id (승격 trace)
    promoted_from_examples: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None
    stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CypherPatternSearchResult:
    memory: CypherPatternMemory
    similarity_score: float
    rank: int


# ── Cypher Negative ───────────────────────────────────────────────────────


@dataclass
class CypherNegativeMemory:
    """LLM 이 첫 시도에 실패한 Cypher + 친절한 fix (다음 호출 시 LLM 학습 신호)."""

    memory_id: str
    question: str
    bad_cypher: str
    error_excerpt: str
    fix_cypher: str
    fix_explanation: Optional[str] = None
    chat_id: Optional[str] = None
    timestamp: Optional[str] = None
    stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CypherNegativeSearchResult:
    memory: CypherNegativeMemory
    similarity_score: float
    rank: int


# ── Unified ───────────────────────────────────────────────────────────────


@dataclass
class KGUnifiedSearchResult:
    """search_all_context 의 통합 반환."""

    cypher_examples: List[CypherExampleSearchResult] = field(default_factory=list)
    schema_docs: List[KGSchemaDocSearchResult] = field(default_factory=list)
    domain_docs: List[KGDomainDocSearchResult] = field(default_factory=list)
    patterns: List[CypherPatternSearchResult] = field(default_factory=list)
    negatives: List[CypherNegativeSearchResult] = field(default_factory=list)
