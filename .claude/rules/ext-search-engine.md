---
paths:
  - "backend/extension_modules/search_engine/**/*.py"
  - "backend/open_webui/retrieval/knowledge_service.py"
---

# 검색 엔진 추상화 규칙

## SearchEngineBase(ABC)
- async context manager (`__aenter__`, `__aexit__`)
- 메서드: `create_index`, `delete_index`, `insert`, `get`, `update`, `delete`,
  `search`, `vector_search`, `hybrid_search`, `multi_vector_search`, `count`

## EngineType
```python
EngineType = Literal["azure_search", "pgvector", "elasticsearch", "vertex_search"]
```

## 팩토리 함수

### get_configured_search_engine (권장)
```python
from extension_modules.search_engine import get_configured_search_engine, create_knowledge_config

index_config = create_knowledge_config()  # "default_knowledge" 인덱스
engine = get_configured_search_engine(app, index_config)  # app.state.config 기반
async with engine:
    results = await engine.hybrid_search(text=query, vector=vec, top_k=10)
```

### get_engine_config_from_app
```python
from extension_modules.search_engine.connector import get_engine_config_from_app

engine_type, engine_config = get_engine_config_from_app(app)
# app.state.config.SEARCH_ENGINE_TYPE에서 엔진 타입 결정
```

## 임베딩 설정 (EmbeddingConfig)
```python
from extension_modules.search_engine import (
    EmbeddingConfig,
    get_embedding_config_from_app,
    generate_embedding_async,
    get_embedding_dimension,
)

# app 기반 설정 추출 (관리자 페이지 설정 값)
embedding_config = get_embedding_config_from_app(app)

# 비동기 임베딩 생성
vector = await generate_embedding_async(text="query", config=embedding_config)

# 모델명에서 벡터 차원 추출
dim = get_embedding_dimension("text-embedding-3-large")  # 3072
```

## 스키마 프리셋 (schemas.py)
- `create_knowledge_config()`: 지식베이스 인덱스 (기본: `default_knowledge`)
- `create_glossary_config()`: 용어집 인덱스
- `create_dbsphere_memory_config()`: DbSphere 메모리 인덱스 (`dbsphere_memory`)
- 벡터 차원 기본값: 3072 (text-embedding-3-large)
- `enable_question_vector`: 멀티벡터 검색 지원 (질의예시 벡터 필드 추가)

## 구현체 (dbs/)
- `azure_search.py`: Azure AI Search
- `elasticsearch.py`: Elasticsearch
- `pgvector.py`: PostgreSQL pgvector
- `vertex_search.py`: Google Vertex AI Search

## SearchEngineKnowledge (knowledge_service.py)
`retrieval/knowledge_service.py` — VECTOR_DB_CLIENT 대체 knowledge 서비스.
```python
from open_webui.retrieval.knowledge_service import SearchEngineKnowledge

knowledge = SearchEngineKnowledge(app=app, collection_name=knowledge_id)
await knowledge.save_chunks(chunks, vectors)           # 청크 저장
results = await knowledge.search(query, query_vector)  # 검색
await knowledge.delete_by_collection()                  # 컬렉션 삭제
count = await knowledge.count()                         # 문서 수
has_docs = await knowledge.has_documents()              # 문서 존재 확인
```
- 인덱스: `default_knowledge` 고정, `collection` 필드로 지식기반(knowledge_id) 구분

## metadata → 개별 필드 매핑
- `config.column_info` 기반으로 메타데이터를 검색 엔진 필드에 매핑
- `_to_azure_doc()`: Azure Search 문서 변환

## 참조 파일
- `search_engine/__init__.py`: SearchEngineBase, 공개 API
- `search_engine/connector.py`: 팩토리, get_configured_search_engine
- `search_engine/schemas.py`: 스키마 프리셋, DBSPHERE_MEMORY_COLUMNS
- `search_engine/embedding.py`: EmbeddingConfig, generate_embedding_async
- `search_engine/dbs/`: DB별 구현
- `retrieval/knowledge_service.py`: SearchEngineKnowledge
