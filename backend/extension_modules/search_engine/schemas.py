"""
Search Engine - Schema Presets

각 용도별 인덱스 스키마 프리셋 정의:
- Knowledge (지식기반): 문서 청크 + 벡터 검색
- Glossary (용어집): 용어 정의 + 약어 매핑
- DbSphere Memory (시맨틱 레이어): Vanna-style 학습 메모리

Usage:
    >>> from extension_modules.search_engine import (
    ...     get_search_engine,
    ...     create_knowledge_config,
    ...     AzureSearchConfig,
    ... )
    >>>
    >>> config = create_knowledge_config("my_knowledge_base")
    >>> engine_config = AzureSearchConfig(endpoint="...", api_key="...")
    >>> engine = get_search_engine(config, engine_config)
"""

import os
from typing import List, Optional

from .models import ColumnInfo, IndexConfig

# 인덱스명 접두사 (환경변수로 오버라이드 가능)
# 예: SEARCH_INDEX_PREFIX=demo → demo_knowledge, demo_glossary, demo_dbsphere_memory
_INDEX_PREFIX = os.environ.get("SEARCH_INDEX_PREFIX", "default")

# =============================================================================
# Knowledge (지식기반) - 문서 기반 RAG
# =============================================================================
# 용도: 문서 청크를 벡터화하여 시맨틱 검색
# 인덱스명: {prefix}_knowledge (기본: default_knowledge, SEARCH_INDEX_PREFIX 환경변수로 변경 가능)
# 필드:
#   - id: 문서 청크 ID
#   - content: 청크 텍스트
#   - vector: 임베딩 벡터 (콘텐츠 기반)
#   - vector_question: 질의예시 임베딩 벡터 (질의예시 기반, 선택)
#   - metadata: JSON (기타 정보)
#   - collection: 지식기반 ID (knowledge_id) 또는 파일 ID (file-{file_id})
#   - file_id: 원본 파일 ID
#   - hash: 콘텐츠 해시 (중복 체크용)
#   - sample_questions: LLM 생성 질의예시 텍스트
#   - source_type: 문서 타입 (pdf, docx, txt 등)
#   - created_at: 생성 시간

KNOWLEDGE_INDEX_NAME = f"{_INDEX_PREFIX}_knowledge"

KNOWLEDGE_COLUMNS: List[ColumnInfo] = [
    ColumnInfo(name="source_type", type="string"),
    ColumnInfo(name="source_file", type="string"),
    ColumnInfo(name="page_num", type="int32"),
    ColumnInfo(name="chunk_index", type="int32"),
    ColumnInfo(name="file_id", type="string"),
    ColumnInfo(name="hash", type="string"),
    # 질의예시 생성 필드
    ColumnInfo(name="sample_questions", type="string"),
    ColumnInfo(name="created_at", type="datetimeoffset"),
    # Dynamic filter slots (KB별 사용자 정의 필터 지원)
    # KB meta.filter_schema에서 slot → 실제 필드 매핑 정보 보관
    ColumnInfo(name="f_str_1", type="string"),
    ColumnInfo(name="f_str_2", type="string"),
    ColumnInfo(name="f_str_3", type="string"),
    ColumnInfo(name="f_str_4", type="string"),
    ColumnInfo(name="f_int_1", type="int32"),
    ColumnInfo(name="f_int_2", type="int32"),
    ColumnInfo(name="f_date_1", type="datetimeoffset"),
    ColumnInfo(name="f_date_2", type="datetimeoffset"),
    # Collection (multi-value) filter slots
    ColumnInfo(name="f_col_1", type="string", is_collection=True),
    ColumnInfo(name="f_col_2", type="string", is_collection=True),
    ColumnInfo(name="f_col_3", type="string", is_collection=True),
    ColumnInfo(name="f_col_4", type="string", is_collection=True),
]


def create_knowledge_config(
    index_name: Optional[str] = None,
    vector_dim: int = 3072,
    embedding_model: Optional[str] = None,
    enable_question_vector: bool = False,
    additional_columns: Optional[List[ColumnInfo]] = None,
) -> IndexConfig:
    """
    지식기반용 인덱스 설정 생성.

    인덱스명은 기본적으로 'default_knowledge'로 고정.
    collection 필드에 지식기반 ID 저장하여 구분.

    Args:
        index_name: 인덱스명 (기본값: "default_knowledge")
        vector_dim: 벡터 차원 (기본값: 3072 for text-embedding-3-large)
        embedding_model: 임베딩 모델명
        enable_question_vector: 질의예시 벡터 필드 활성화 여부
        additional_columns: 추가 컬럼 정의

    Returns:
        IndexConfig: 지식기반용 인덱스 설정
    """
    columns = KNOWLEDGE_COLUMNS.copy()
    if additional_columns:
        columns.extend(additional_columns)

    return IndexConfig(
        index_name=index_name or KNOWLEDGE_INDEX_NAME,
        column_info=columns,
        vector_dim=vector_dim,
        embedding_model=embedding_model,
        secondary_vector_field="vector_question" if enable_question_vector else None,
    )


# =============================================================================
# Glossary (용어집) - 용어/약어 정의
# =============================================================================
# 용도: 도메인 용어, 약어, 동의어 관리
# 인덱스명: {prefix}_glossary (기본: default_glossary)
# 필드:
#   - id: 용어 ID
#   - content: 임베딩용 결합 텍스트 (term + synonyms + description + example)
#   - vector: 임베딩 벡터 (시맨틱 검색용)
#   - collection: 용어집 ID (glossary_id)
#   - term: 용어 원문
#   - synonyms: 동의어/유사어 목록 (Collection)
#   - description: 용어 설명
#   - example: 예문
#   - category: 분류 (기술용어, 업무용어 등)

GLOSSARY_INDEX_NAME = f"{_INDEX_PREFIX}_glossary"

GLOSSARY_COLUMNS: List[ColumnInfo] = [
    ColumnInfo(name="term", type="string"),
    ColumnInfo(name="synonyms", type="string", is_collection=True),
    ColumnInfo(name="description", type="string"),
    ColumnInfo(name="example", type="string"),
    ColumnInfo(name="category", type="string"),
    ColumnInfo(name="created_at", type="datetimeoffset"),
    ColumnInfo(name="updated_at", type="datetimeoffset"),
]


def create_glossary_config(
    vector_dim: int = 3072,
    embedding_model: Optional[str] = None,
    additional_columns: Optional[List[ColumnInfo]] = None,
) -> IndexConfig:
    """
    용어집용 인덱스 설정 생성.

    인덱스명은 '{prefix}_glossary'입니다 (SEARCH_INDEX_PREFIX 환경변수로 변경 가능).
    collection 필드에 glossary_id를 저장하여 용어집별로 구분합니다.

    Args:
        vector_dim: 벡터 차원 (기본값: 3072 for text-embedding-3-large)
        embedding_model: 임베딩 모델명
        additional_columns: 추가 컬럼 정의

    Returns:
        IndexConfig: 용어집용 인덱스 설정
    """
    columns = GLOSSARY_COLUMNS.copy()
    if additional_columns:
        columns.extend(additional_columns)

    return IndexConfig(
        index_name=GLOSSARY_INDEX_NAME,
        column_info=columns,
        vector_dim=vector_dim,
        embedding_model=embedding_model,
        # 용어집 시맨틱 설정
        semantic_title_field="term",
        semantic_content_fields=["content", "description", "example"],
        semantic_keywords_fields=["synonyms"],
    )


# =============================================================================
# DbSphere Memory - Vanna-style Learning Memory
# =============================================================================
# 용도: SQL 생성을 위한 다양한 학습 컨텍스트 저장
# 인덱스명: {prefix}_dbsphere_memory (기본: default_dbsphere_memory)
#
# 내장 필드 (모든 인덱스 공통):
#   - id: 레코드 ID (key)
#   - content: 시맨틱 검색용 텍스트
#   - vector: 임베딩 벡터
#   - metadata: JSON (비필터링 데이터 전체)
#   - collection: dbsphere_id (DB별 격리 필터링)
#
# 추가 필터링 컬럼 (OData 필터에서 실제 사용):
#   - entity_type: 메모리 타입 구분 (모든 타입)
#   - table_name: DDL 스키마 필터 + 테이블별 삭제
#   - doc_type: documentation 타입 필터 (term, rule, context)
#   - use_case: sql_example 용도 필터
#
# metadata JSON에 저장되는 데이터 (타입별):
#   - sql_memory:    { sql_query, user_id, chat_id, created_at }
#   - ddl_schema:    { ddl_statement, column_info_json, table_description,
#                      relationships_json, schema_name, created_at }
#   - documentation: { title, related_tables_json, related_columns_json,
#                      user_id, created_at }
#   - sql_example:   { sql_query, description, tags_json,
#                      related_tables_json, created_at }

DBSPHERE_MEMORY_INDEX_NAME = f"{_INDEX_PREFIX}_dbsphere_memory"

DBSPHERE_MEMORY_COLUMNS: List[ColumnInfo] = [
    # Filterable columns (OData filter expressions에서 사용)
    ColumnInfo(
        name="entity_type", type="string"
    ),  # sql_memory | ddl_schema | documentation | sql_example
    ColumnInfo(name="table_name", type="string"),  # ddl_schema 필터 + delete_by_table
    ColumnInfo(name="doc_type", type="string"),  # documentation: term | rule | context
    ColumnInfo(name="use_case", type="string"),  # sql_example 필터
]


def create_dbsphere_memory_config(
    vector_dim: int = 3072,
    embedding_model: Optional[str] = None,
) -> IndexConfig:
    """
    DbSphere Memory용 인덱스 설정 생성.

    인덱스명은 '{prefix}_dbsphere_memory'입니다 (SEARCH_INDEX_PREFIX 환경변수로 변경 가능).
    collection 필드(내장)에 dbsphere_id를 저장하여 DB별 격리.

    Args:
        vector_dim: 벡터 차원
        embedding_model: 임베딩 모델명

    Returns:
        IndexConfig: DbSphere Memory용 인덱스 설정
    """
    return IndexConfig(
        index_name=DBSPHERE_MEMORY_INDEX_NAME,
        column_info=DBSPHERE_MEMORY_COLUMNS.copy(),
        vector_dim=vector_dim,
        embedding_model=embedding_model,
    )


# =============================================================================
# Knowledge Graph Nodes - Semantic node search
# =============================================================================
# 용도: KG의 노드(term/concept/table/column/...)에 대한 시맨틱 검색
# 인덱스명: {prefix}_kg_node (기본: default_kg_node)
#
# 내장 필드:
#   - id: 노드 ID (key) — 결정적 ID (kg_id__source__...)
#   - content: 임베딩용 텍스트 (label + description)
#   - vector: 임베딩 벡터
#   - metadata: JSON (label, description, properties, source_ref 등)
#   - collection: kg_id (KG별 격리 필터)
#
# 추가 필터링 컬럼:
#   - node_type: term | concept | table | column | metric | doc_entity
#   - source_kind: glossary | dbsphere | manual | llm_extract
#   - user_id: 멀티테넌시 필터
#   - created_at: 생성 시각
#
# 검색 패턴:
#   filter_expr = "collection eq '{kg_id}' and node_type eq 'term'"
#   await engine.hybrid_search(text=query, vector=vec, filter_expr=filter_expr)

KG_NODE_INDEX_NAME = f"{_INDEX_PREFIX}_kg_node"

KG_NODE_COLUMNS: List[ColumnInfo] = [
    ColumnInfo(name="node_type", type="string"),
    ColumnInfo(name="source_kind", type="string"),
    ColumnInfo(name="user_id", type="string"),
    ColumnInfo(name="created_at", type="datetimeoffset"),
]


def create_kg_node_config(
    vector_dim: int = 3072,
    embedding_model: Optional[str] = None,
) -> IndexConfig:
    """KG 노드용 인덱스 설정 생성.

    인덱스명: '{prefix}_kg_node' (SEARCH_INDEX_PREFIX 환경변수로 변경 가능).
    collection 필드에 kg_id를 저장하여 KG 인스턴스별로 격리.
    """
    return IndexConfig(
        index_name=KG_NODE_INDEX_NAME,
        column_info=KG_NODE_COLUMNS.copy(),
        vector_dim=vector_dim,
        embedding_model=embedding_model,
        # KG 노드 시맨틱 설정 (Azure 시맨틱 리랭킹 힌트)
        semantic_title_field="content",
        semantic_content_fields=["content"],
    )


# =============================================================================
# KG Memory - Vanna-style 시맨틱 레이어 (kg_cypher 도구용)
# =============================================================================
# 용도: read-only Cypher 생성의 정확도를 사용량과 함께 끌어올리는 학습 메모리.
# 인덱스명: {prefix}_kg_memory (기본: default_kg_memory)
#
# 내장 필드 (모든 인덱스 공통):
#   - id: 레코드 ID
#   - content: 시맨틱 검색용 텍스트 (entity_type 별로 다름)
#   - vector: 임베딩 벡터
#   - metadata: JSON (비필터링 데이터 전체)
#   - collection: kg_id (KG 인스턴스 격리)
#
# 추가 필터링 컬럼:
#   - entity_type: 메모리 타입 구분
#       cypher_example | kg_schema_doc | kg_domain_doc |
#       cypher_pattern | cypher_negative
#   - doc_type: kg_domain_doc 분류 (rule | convention | caveat)
#   - schema_role: kg_schema_doc 분류 (node | edge)
#   - stale: drift 발생 시 마킹되어 retrieval 에서 제외
#
# metadata JSON 에 저장되는 키 (타입별, 자세한 shape 은 memory/models.py):
#   - cypher_example:  { cypher, hit_count, last_used, confidence,
#                        referenced_node_types_json, referenced_edge_types_json,
#                        normalized_question, user_id, chat_id, created_at }
#   - kg_schema_doc:   { type_name, sample_labels_json, sample_props_json,
#                        degree_stats_json, source_hash, created_at }
#   - kg_domain_doc:   { title, related_node_types_json, related_edge_types_json,
#                        author, created_at }
#   - cypher_pattern:  { template_cypher, slots_json, use_case, candidate_id,
#                        promoted_from_examples_json, created_at }
#   - cypher_negative: { bad_cypher, error_excerpt, fix_cypher, fix_explanation,
#                        chat_id, created_at }
#
# 검색 패턴:
#   filter_expr = (
#       "collection eq '{kg_id}' and entity_type eq 'cypher_example' "
#       "and stale eq false"
#   )

KG_MEMORY_INDEX_NAME = f"{_INDEX_PREFIX}_kg_memory"

KG_MEMORY_COLUMNS: List[ColumnInfo] = [
    ColumnInfo(name="entity_type", type="string"),
    ColumnInfo(name="doc_type", type="string"),
    ColumnInfo(name="schema_role", type="string"),
    ColumnInfo(name="stale", type="boolean"),
]


def create_kg_memory_config(
    vector_dim: int = 3072,
    embedding_model: Optional[str] = None,
) -> IndexConfig:
    """KG 시맨틱 메모리용 인덱스 설정.

    인덱스명: '{prefix}_kg_memory'. collection 필드에 kg_id 저장 (KG 격리).
    DbSphere 메모리와 별개 인덱스로 둔다 — 두 모듈은 lifecycle 이 다르고
    collection 필터 의미가 충돌하기 때문 (DbSphere=db_id vs KG=kg_id).
    """
    return IndexConfig(
        index_name=KG_MEMORY_INDEX_NAME,
        column_info=KG_MEMORY_COLUMNS.copy(),
        vector_dim=vector_dim,
        embedding_model=embedding_model,
    )


# =============================================================================
# Index Name Conventions
# =============================================================================
# 인덱스 명명 규칙:
#   - Knowledge: kb_{user_id}_{knowledge_id}
#   - Glossary: glossary_{user_id}_{glossary_id}
#   - DbSphere: dbsphere_{user_id}_{db_id}


def generate_index_name(
    prefix: str,
    user_id: str,
    resource_id: str,
) -> str:
    """
    인덱스명 생성.

    Args:
        prefix: 프리픽스 (kb, glossary, dbsphere)
        user_id: 사용자 ID
        resource_id: 리소스 ID

    Returns:
        str: 인덱스명 (예: "kb_abc123_def456")
    """
    # Azure Search 인덱스명 제약: 소문자, 숫자, 하이픈만 허용
    safe_user = user_id.replace("-", "").lower()[:12]
    safe_resource = resource_id.replace("-", "").lower()[:12]
    return f"{prefix}_{safe_user}_{safe_resource}"
