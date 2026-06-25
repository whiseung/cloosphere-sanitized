"""
Search Engine - 공통 모델 정의
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# =============================================================================
# 문서 및 검색 모델
# =============================================================================


class DocumentItem(BaseModel):
    """검색 엔진에 저장될 문서"""

    id: str
    content: str
    vector: Optional[List[float]] = None
    metadata: Optional[Dict[str, Any]] = None
    collection: Optional[str] = None
    # Multi-vector 지원
    secondary_vector: Optional[List[float]] = None  # 예: 질의예시 벡터


class SearchQuery(BaseModel):
    """검색 쿼리"""

    query: str | List[str]
    filter: Optional[str] = None
    top_k: int = Field(default=10, ge=1, le=100)
    top_k_vector: int = Field(default=30, ge=1, le=100)
    reranker_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    """검색 결과"""

    id: str
    content: str
    score: float
    metadata: Optional[Dict[str, Any]] = None
    reranked: bool = False


class ColumnInfo(BaseModel):
    """인덱스 컬럼 정보"""

    name: str
    type: str  # string, boolean, int32, int64, double, datetimeoffset
    is_collection: bool = False


# =============================================================================
# 인덱스 설정
# =============================================================================


class IndexConfig(BaseModel):
    """인덱스 설정"""

    index_name: str
    column_info: Optional[List[ColumnInfo]] = None
    vector_dim: int = Field(default=1536, ge=1)
    embedding_model: Optional[str] = None
    # Multi-vector 검색 지원
    secondary_vector_field: Optional[str] = None  # 예: "vector_question"
    # 시맨틱 검색 설정 (Azure AI Search)
    semantic_config_name: str = "my-semantic-config"
    semantic_title_field: Optional[str] = None
    semantic_content_fields: Optional[List[str]] = None  # 기본: ["content"]
    semantic_keywords_fields: Optional[List[str]] = None


# =============================================================================
# 엔진별 연결 설정
# =============================================================================


class AzureSearchConfig(BaseModel):
    """Azure AI Search 연결 설정 (벡터기 사용 안함 - 외부 임베딩)"""

    endpoint: str
    api_key: str
    api_version: str = "2024-07-01"  # Azure AI Search API 버전


class PgVectorConfig(BaseModel):
    """PostgreSQL pgvector 연결 설정"""

    host: str = "localhost"
    port: int = 5432
    database: str = "postgres"
    user: str = "postgres"
    password: str = ""


class ElasticsearchConfig(BaseModel):
    """Elasticsearch 연결 설정"""

    url: str = "http://localhost:9200"
    api_key: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    ca_certs: Optional[str] = None


class VertexSearchConfig(BaseModel):
    """Google Vertex AI Search 연결 설정"""

    project_id: str
    location: str = "us-central1"
    service_account_key: Optional[str] = None  # JSON 형식 서비스 계정 키


# 엔진 설정 타입 유니온
EngineConfig = (
    AzureSearchConfig | PgVectorConfig | ElasticsearchConfig | VertexSearchConfig
)


# =============================================================================
# Reranker 설정
# =============================================================================


class VertexRankerConfig(BaseModel):
    """Vertex AI Ranking API 설정"""

    project_id: Optional[str] = None  # 미설정 시 서비스 계정 키 또는 ADC에서 자동 감지
    location: str = "global"
    model: str = "semantic-ranker-default@latest"
    service_account_key: Optional[str] = None  # JSON 형식. 미설정 시 ADC 사용.


# 추후 Union[VertexRankerConfig, ...] 확장 가능
RerankerConfig = VertexRankerConfig
