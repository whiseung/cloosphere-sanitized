# 코드에서 사용하기

## 기본 사용법

### 관리자 설정 기반 (권장)

관리자 페이지에서 설정한 검색 엔진을 사용합니다.

```python
from fastapi import Request
from extension_modules.search_engine import (
    get_configured_search_engine,
    create_knowledge_config,
    SearchQuery,
    DocumentItem,
)

async def search_knowledge(request: Request, query: str, embedding: list[float]):
    # 1. 인덱스 설정 생성
    index_config = create_knowledge_config("kb_user123_knowledge456")

    # 2. 관리자 설정 기반 엔진 생성
    engine = get_configured_search_engine(request.app, index_config)

    if not engine:
        raise ValueError("Search engine not configured")

    # 3. 검색 실행
    async with engine:
        search_query = SearchQuery(query=query, top_k=10)
        results = await engine.search(search_query, query_vector=embedding)

    return results
```

### 직접 설정 사용

특정 엔진을 명시적으로 사용합니다.

```python
from extension_modules.search_engine import (
    get_search_engine,
    IndexConfig,
    AzureSearchConfig,
    SearchQuery,
)

# 인덱스 설정
index_config = IndexConfig(
    index_name="my_custom_index",
    vector_dim=3072,
)

# 엔진 연결 설정
engine_config = AzureSearchConfig(
    endpoint="https://my-search.search.windows.net",
    api_key="my-api-key",
    api_version="2024-07-01",
)

# 엔진 생성
engine = get_search_engine(index_config, engine_config)

async with engine:
    # 인덱스 생성
    await engine.create_index()

    # 문서 색인
    await engine.insert([
        DocumentItem(id="doc1", content="Hello World", vector=[0.1, 0.2, ...]),
    ])

    # 검색
    results = await engine.search(
        SearchQuery(query="Hello"),
        query_vector=[0.1, 0.2, ...]
    )
```

## 주요 메서드

### 인덱스 관리

```python
# 인덱스 생성
created = await engine.create_index()
# Returns: True (생성됨) / False (이미 존재)

# 인덱스 존재 확인
exists = await engine.index_exists()
# Returns: True / False

# 인덱스 삭제
deleted = await engine.delete_index()
# Returns: True (삭제됨) / False (존재하지 않음)
```

### 문서 CRUD

```python
from extension_modules.search_engine import DocumentItem

# 삽입 (bulk)
documents = [
    DocumentItem(
        id="doc1",
        content="문서 내용",
        vector=[0.1, 0.2, ...],  # 임베딩 벡터
        metadata={"source": "file.pdf", "page": 1},
        collection="kb_123",
    ),
    DocumentItem(id="doc2", content="다른 문서", vector=[...]),
]
count = await engine.insert(documents)
# Returns: 삽입된 문서 수

# 조회 (ID로)
docs = await engine.get(["doc1", "doc2"])
# Returns: List[DocumentItem]

# 업데이트 (upsert)
count = await engine.update(documents)
# Returns: 업데이트된 문서 수

# 삭제 (ID로)
count = await engine.delete(["doc1", "doc2"])
# Returns: 삭제된 문서 수

# 필터로 삭제
count = await engine.delete_by_filter("collection eq 'kb_123'")
# Returns: 삭제된 문서 수
```

### 검색

```python
from extension_modules.search_engine import SearchQuery

# 하이브리드 검색 (벡터 + 키워드 + 시맨틱)
query = SearchQuery(
    query="연차 신청 방법",          # 검색 텍스트
    filter="collection eq 'hr_docs'",  # OData 필터
    top_k=10,                         # 반환할 결과 수
    top_k_vector=30,                  # 벡터 검색 k값
    reranker_threshold=2.0,           # 리랭커 점수 임계값
)

results = await engine.search(query, query_vector=embedding)
# Returns: List[SearchResult]

for result in results:
    print(f"ID: {result.id}")
    print(f"Score: {result.score}")
    print(f"Content: {result.content}")
    print(f"Metadata: {result.metadata}")
```

```python
# 벡터 전용 검색 (키워드/리랭킹 없음)
results = await engine.vector_search(
    vector=embedding,
    top_k=10,
    filter_expr="collection eq 'kb_123'",
)
# Returns: List[SearchResult]
```

### 필터링 및 카운트

```python
# 메타데이터 기반 필터링
docs = await engine.filter_by_metadata(
    filter_expr="collection eq 'kb_123' and source eq 'file.pdf'",
    limit=100,
)
# Returns: List[DocumentItem]

# 문서 수 조회
count = await engine.count()
# Returns: 전체 문서 수

count = await engine.count("collection eq 'kb_123'")
# Returns: 필터 조건에 맞는 문서 수
```

## 스키마 프리셋 사용

### Knowledge (지식 베이스)

```python
from extension_modules.search_engine import create_knowledge_config

# 기본 벡터 차원 (3072 = text-embedding-3-large)
config = create_knowledge_config("kb_user123_knowledge456")

# 커스텀 벡터 차원
config = create_knowledge_config("kb_xxx", vector_dim=1536)
```

### Glossary (용어집)

```python
from extension_modules.search_engine import create_glossary_config, DocumentItem

config = create_glossary_config("glossary_company")
engine = get_configured_search_engine(request.app, config)

async with engine:
    await engine.create_index()
    await engine.insert([
        DocumentItem(
            id="term1",
            content="EBITDA",  # 검색용 텍스트
            vector=embedding,
            metadata={
                "term": "EBITDA",
                "definition": "세전·이자지급전·감가상각전 영업이익",
                "category": "재무",
                "synonyms": ["에비타", "에비다"],
            },
        ),
    ])
```

### DbSphere (에이전트 메모리)

```python
from extension_modules.search_engine import create_dbsphere_config

config = create_dbsphere_config("dbsphere_agent_memory")
engine = get_configured_search_engine(request.app, config)

async with engine:
    await engine.create_index()
    await engine.insert([
        DocumentItem(
            id="memory1",
            content="월별 매출 조회하는 쿼리",
            vector=embedding,
            metadata={
                "question": "이번 달 매출이 얼마야?",
                "tool_name": "run_sql",
                "args_json": '{"query": "SELECT SUM(amount) FROM sales WHERE ..."}',
                "success": True,
            },
        ),
    ])
```

## 인덱스 이름 생성

```python
from extension_modules.search_engine import generate_index_name

# 지식 베이스 인덱스 이름
index_name = generate_index_name("knowledge", user_id="user123", resource_id="kb456")
# Returns: "kb_user123_kb456"

# DbSphere 인덱스 이름
index_name = generate_index_name("dbsphere", resource_id="agent_memory")
# Returns: "dbsphere_agent_memory"
```

## DBSphere 에이전트에서 사용

`dbsphere_agent.py`에서 관리자 설정을 사용하는 예시:

```python
class DBSphereAgent:
    def __init__(self, ..., request: Request):
        self.request = request

    def _create_agent_memory(self, memory_type: str = "azure_search"):
        config = self.request.app.state.config
        engine_type = getattr(config, "SEARCH_ENGINE_TYPE", "")

        if memory_type == "azure_search" or engine_type == "azure_search":
            # 검색 엔진 연결 정보 (관리자 설정 > 검색 엔진)
            endpoint = getattr(config, "SEARCH_ENGINE_AZURE_ENDPOINT", "")
            api_key = getattr(config, "SEARCH_ENGINE_AZURE_API_KEY", "")

            # 임베딩 설정 (관리자 설정 > 문서)
            embedding_endpoint = getattr(config, "RAG_AZURE_OPENAI_API_BASE_URL", "")
            embedding_api_key = getattr(config, "RAG_AZURE_OPENAI_API_KEY", "")
            embedding_model = getattr(config, "RAG_EMBEDDING_MODEL", "")

            return AzureAISearchAgentMemory(
                endpoint=endpoint,
                api_key=api_key,
                embedding_endpoint=embedding_endpoint,
                embedding_api_key=embedding_api_key,
                embedding_deployment=embedding_model,
            )
```

## 에러 처리

```python
from extension_modules.search_engine import get_configured_search_engine

try:
    engine = get_configured_search_engine(request.app, index_config)

    if not engine:
        # 검색 엔진이 설정되지 않음
        raise ValueError("Search engine not configured in admin settings")

    async with engine:
        results = await engine.search(query, query_vector=embedding)

except RuntimeError as e:
    # SDK 의존성 누락
    logger.error(f"SDK not installed: {e}")

except Exception as e:
    # 검색 실패
    logger.error(f"Search failed: {e}")
```

## 비동기 컨텍스트 매니저

`async with`를 사용하면 리소스가 자동으로 정리됩니다:

```python
# 권장 - 자동 정리
async with engine:
    await engine.search(...)
# close() 자동 호출

# 수동 정리 (필요한 경우)
engine = get_search_engine(...)
try:
    await engine.search(...)
finally:
    await engine.close()
```

## 필터 표현식 (OData)

Azure AI Search 스타일의 OData 필터를 사용합니다:

```python
# 문자열 비교
filter = "collection eq 'kb_123'"
filter = "source eq 'file.pdf'"

# 숫자 비교
filter = "page gt 5"
filter = "score ge 0.8"

# 논리 연산
filter = "collection eq 'kb_123' and page gt 5"
filter = "source eq 'a.pdf' or source eq 'b.pdf'"

# 컬렉션 검색
filter = "tags/any(t: t eq 'important')"
```

## 배치 처리

대량 문서 처리 시 배치로 나누어 처리:

```python
BATCH_SIZE = 100

async def bulk_insert(engine, documents: list[DocumentItem]):
    total_inserted = 0

    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i:i + BATCH_SIZE]
        count = await engine.insert(batch)
        total_inserted += count
        logger.info(f"Inserted {count} documents ({total_inserted}/{len(documents)})")

    return total_inserted
```
