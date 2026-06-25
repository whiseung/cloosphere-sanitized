# 기술 아키텍처

## 모듈 구조

```
backend/extension_modules/search_engine/
├── __init__.py          # 모듈 export
├── base.py              # SearchEngineBase 추상 클래스
├── connector.py         # 팩토리 함수
├── models.py            # Pydantic 모델
├── schemas.py           # 스키마 프리셋
└── dbs/                 # 엔진별 구현체
    ├── __init__.py
    ├── azure_search.py
    ├── pgvector.py
    ├── milvus.py
    ├── elasticsearch.py
    └── vertex_search.py
```

## 데이터 모델

### DocumentItem

검색 엔진에 저장되는 문서입니다.

```python
# backend/extension_modules/search_engine/models.py

class DocumentItem(BaseModel):
    """검색 엔진에 저장될 문서"""

    id: str                                    # 문서 ID
    content: str                               # 텍스트 내용
    vector: Optional[List[float]] = None       # 임베딩 벡터
    metadata: Optional[Dict[str, Any]] = None  # 추가 메타데이터
    collection: Optional[str] = None           # 컬렉션/파티션 ID
```

### SearchQuery

검색 쿼리 파라미터입니다.

```python
class SearchQuery(BaseModel):
    """검색 쿼리"""

    query: str | List[str]                           # 검색 텍스트
    filter: Optional[str] = None                     # 필터 표현식 (OData)
    top_k: int = Field(default=10, ge=1, le=100)     # 반환할 결과 수
    top_k_vector: int = Field(default=30, ge=1, le=100)  # 벡터 검색 k값
    reranker_threshold: float = Field(default=2.0, ge=0.0)  # 리랭커 점수 임계값
```

### SearchResult

검색 결과입니다.

```python
class SearchResult(BaseModel):
    """검색 결과"""

    id: str                                    # 문서 ID
    content: str                               # 내용
    score: float                               # 관련성 점수
    metadata: Optional[Dict[str, Any]] = None  # 메타데이터
```

### IndexConfig

인덱스 설정입니다.

```python
class IndexConfig(BaseModel):
    """인덱스 설정"""

    index_name: str                            # 인덱스 이름
    column_info: Optional[List[ColumnInfo]] = None  # 추가 컬럼 정의
    vector_dim: int = Field(default=1536, ge=1)     # 벡터 차원
    embedding_model: Optional[str] = None      # 임베딩 모델 이름 (참조용)

class ColumnInfo(BaseModel):
    """인덱스 컬럼 정보"""

    name: str                                  # 컬럼 이름
    type: str                                  # 타입 (string, boolean, int32, ...)
    is_collection: bool = False                # 배열 여부
```

### 엔진별 Config

```python
class AzureSearchConfig(BaseModel):
    """Azure AI Search 연결 설정"""
    endpoint: str
    api_key: str
    api_version: str = "2024-07-01"

class PgVectorConfig(BaseModel):
    """PostgreSQL pgvector 연결 설정"""
    host: str = "localhost"
    port: int = 5432
    database: str = "postgres"
    user: str = "postgres"
    password: str = ""

class MilvusConfig(BaseModel):
    """Milvus 연결 설정"""
    host: str = "localhost"
    port: int = 19530
    user: str = ""
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
    service_account_key: Optional[str] = None  # JSON 형식
```

## 클래스 다이어그램

```
                    ┌─────────────────────┐
                    │  SearchEngineBase   │
                    │      (ABC)          │
                    ├─────────────────────┤
                    │ + create_index()    │
                    │ + delete_index()    │
                    │ + index_exists()    │
                    │ + insert()          │
                    │ + get()             │
                    │ + update()          │
                    │ + delete()          │
                    │ + search()          │
                    │ + vector_search()   │
                    │ + filter_by_meta()  │
                    │ + count()           │
                    │ + close()           │
                    └─────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│AzureSearchEng │   │ PgVectorEng   │   │  MilvusEng    │
└───────────────┘   └───────────────┘   └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│AzureSearchConf│   │ PgVectorConf  │   │  MilvusConf   │
└───────────────┘   └───────────────┘   └───────────────┘
```

## API 구조

### 관리자 설정 API

**Backend**: `backend/open_webui/routers/retrieval.py`

| Method | Endpoint | 설명 | 권한 |
|--------|----------|------|------|
| GET | `/api/retrieval/search-engine/config` | 검색 엔진 설정 조회 | admin |
| POST | `/api/retrieval/search-engine/config/update` | 검색 엔진 설정 업데이트 | admin |

### 요청/응답 예시

#### 설정 조회

```bash
GET /api/retrieval/search-engine/config
Authorization: Bearer {admin_token}
```

```json
{
  "status": true,
  "engine_type": "azure_search",
  "azure_endpoint": "https://my-search.search.windows.net",
  "azure_api_key": "xxxxxxxx",
  "azure_api_version": "2024-07-01",
  "pgvector_host": "localhost",
  "pgvector_port": 5432,
  "pgvector_database": "postgres",
  "pgvector_user": "postgres",
  "pgvector_password": "",
  "milvus_host": "localhost",
  "milvus_port": 19530,
  "milvus_user": "",
  "milvus_password": "",
  "elasticsearch_url": "http://localhost:9200",
  "elasticsearch_api_key": "",
  "elasticsearch_user": "",
  "elasticsearch_password": "",
  "elasticsearch_ca_certs": "",
  "vertex_project_id": "",
  "vertex_location": "us-central1",
  "vertex_service_account_key": ""
}
```

#### 설정 업데이트

```bash
POST /api/retrieval/search-engine/config/update
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "engine_type": "azure_search",
  "azure_endpoint": "https://new-search.search.windows.net",
  "azure_api_key": "new-api-key",
  "azure_api_version": "2024-07-01"
}
```

```json
{
  "status": true,
  "message": "Search engine configuration updated"
}
```

## 팩토리 함수

### get_search_engine

엔진 설정을 받아 검색 엔진 인스턴스를 생성합니다.

```python
from extension_modules.search_engine import (
    get_search_engine,
    IndexConfig,
    AzureSearchConfig,
)

config = IndexConfig(index_name="my_index", vector_dim=3072)
engine_config = AzureSearchConfig(
    endpoint="https://xxx.search.windows.net",
    api_key="xxx",
    api_version="2024-07-01",
)

engine = get_search_engine(config, engine_config)
```

### get_configured_search_engine

app.state.config에서 설정을 읽어 검색 엔진을 생성합니다.

```python
from extension_modules.search_engine import (
    get_configured_search_engine,
    create_knowledge_config,
)

index_config = create_knowledge_config("kb_xxx")
engine = get_configured_search_engine(request.app, index_config)

if engine:
    async with engine:
        results = await engine.search(query, query_vector=embedding)
```

### get_engine_config_from_app

app.state.config에서 엔진 설정만 추출합니다.

```python
from extension_modules.search_engine import get_engine_config_from_app

engine_type, engine_config = get_engine_config_from_app(request.app)

if engine_type == "azure_search":
    print(f"Azure endpoint: {engine_config.endpoint}")
```

## 환경 변수

### 검색 엔진 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_TYPE` | 검색 엔진 타입 | `""` |

### Azure AI Search

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_AZURE_ENDPOINT` | 엔드포인트 URL | `""` |
| `SEARCH_ENGINE_AZURE_API_KEY` | API 키 | `""` |
| `SEARCH_ENGINE_AZURE_API_VERSION` | API 버전 | `2024-07-01` |

### PostgreSQL pgvector

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_PGVECTOR_HOST` | 호스트 | `localhost` |
| `SEARCH_ENGINE_PGVECTOR_PORT` | 포트 | `5432` |
| `SEARCH_ENGINE_PGVECTOR_DATABASE` | 데이터베이스 | `postgres` |
| `SEARCH_ENGINE_PGVECTOR_USER` | 사용자 | `postgres` |
| `SEARCH_ENGINE_PGVECTOR_PASSWORD` | 비밀번호 | `""` |

### Milvus

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_MILVUS_HOST` | 호스트 | `localhost` |
| `SEARCH_ENGINE_MILVUS_PORT` | 포트 | `19530` |
| `SEARCH_ENGINE_MILVUS_USER` | 사용자 | `""` |
| `SEARCH_ENGINE_MILVUS_PASSWORD` | 비밀번호 | `""` |

### Elasticsearch

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_ELASTICSEARCH_URL` | URL | `http://localhost:9200` |
| `SEARCH_ENGINE_ELASTICSEARCH_API_KEY` | API 키 | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_USER` | 사용자 | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_PASSWORD` | 비밀번호 | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_CA_CERTS` | CA 인증서 경로 | `""` |

### Google Vertex AI Search

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_VERTEX_PROJECT_ID` | GCP 프로젝트 ID | `""` |
| `SEARCH_ENGINE_VERTEX_LOCATION` | 리전 | `us-central1` |
| `SEARCH_ENGINE_VERTEX_SERVICE_ACCOUNT_KEY` | 서비스 계정 키 JSON | `""` |

## PersistentConfig

환경 변수와 데이터베이스 저장을 모두 지원합니다.

```python
# backend/open_webui/config.py

SEARCH_ENGINE_TYPE = PersistentConfig(
    "SEARCH_ENGINE_TYPE",
    "search_engine.type",
    os.environ.get("SEARCH_ENGINE_TYPE", ""),
)

SEARCH_ENGINE_AZURE_ENDPOINT = PersistentConfig(
    "SEARCH_ENGINE_AZURE_ENDPOINT",
    "search_engine.azure.endpoint",
    os.environ.get("SEARCH_ENGINE_AZURE_ENDPOINT", ""),
)
# ... 기타 설정
```

**동작 방식:**
1. 환경 변수가 설정되어 있으면 환경 변수 값 사용
2. 환경 변수가 없으면 데이터베이스에서 값 로드
3. 관리자 페이지에서 변경 시 데이터베이스에 저장
4. 앱 재시작 없이 설정 변경 가능

## 검색 흐름

### search() 메서드

```
1. 클라이언트 호출
   engine.search(query, query_vector=embedding)
           │
           ▼
2. 하이브리드 검색 실행
   ┌─────────────────────────────────┐
   │ Azure AI Search                 │
   ├─────────────────────────────────┤
   │ - 벡터 검색 (VectorizedQuery)   │
   │ - 키워드 검색 (search_text)     │
   │ - 시맨틱 리랭킹                 │
   └─────────────────────────────────┘
           │
           ▼
3. 결과 필터링
   - reranker_score >= threshold
   - 중복 제거
   - top_k 개수 제한
           │
           ▼
4. SearchResult 반환
   [SearchResult(id, content, score, metadata), ...]
```

### vector_search() 메서드

벡터 전용 검색 (키워드/시맨틱 리랭킹 없음):

```python
results = await engine.vector_search(
    vector=query_embedding,
    top_k=10,
    filter_expr="collection eq 'kb_123'"
)
```
