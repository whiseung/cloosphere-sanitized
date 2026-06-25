> Last Updated: 2026-04-08

# 검색 엔진 (Search Engine) 모듈

Cloosphere의 벡터 검색 엔진 추상화 레이어에 대한 기술 문서입니다.

> **구현 현황 (2026-04-08)**: **실제 구현된 엔진은 4종** — Azure AI Search, pgvector, Elasticsearch, Vertex AI Search. **Milvus는 문서에는 언급되나 `dbs/__init__.py`에서 export되지 않은 상태** (향후 추가 예정). 아래 "주요 기능" 표의 Milvus 행은 참고용으로 남겨두되, 현재는 사용 불가.
>
> **신규 모듈 (2026-02~03 추가)**: `embedding.py` (auto-vectorizer helpers), `filter_builder.py` / `filter_translator.py` (OData/SQL 필터 변환), `reranker/` (Vertex Ranker 포함) — 아래 "모듈 구조" 참조.

## 목차

1. [개요](#개요)
2. [주요 기능](#주요-기능)
3. [상세 문서](#상세-문서)
4. [퀵 스타트](#퀵-스타트)

---

## 개요

검색 엔진 모듈은 다양한 벡터 데이터베이스(Azure AI Search, pgvector, Milvus, Elasticsearch, Vertex AI Search)를 통일된 인터페이스로 사용할 수 있게 해주는 추상화 레이어입니다.

### 주요 개념

| 개념 | 설명 |
|------|------|
| **SearchEngineBase** | 모든 검색 엔진의 추상 베이스 클래스 |
| **EngineConfig** | 엔진별 연결 설정 (AzureSearchConfig, PgVectorConfig 등) |
| **IndexConfig** | 인덱스 스키마 설정 (컬럼 정의, 벡터 차원 등) |
| **DocumentItem** | 검색 엔진에 저장되는 문서 |
| **SearchQuery** | 검색 쿼리 파라미터 |

### 데이터 흐름

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  관리자 설정     │────▶│  app.state      │────▶│  Search Engine  │
│  (프론트엔드)    │     │  .config        │     │  Instance       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │  API 호출             │  설정 저장             │  검색/색인
        │                       │                       │
        ▼                       ▼                       ▼
   SearchEngine.svelte    PersistentConfig        Azure/pgvector/
   /api/retrieval/        SEARCH_ENGINE_*         Milvus/ES/Vertex
   search-engine/config
```

### 임베딩 전략

**중요**: 이 모듈은 **자동 벡터기(Auto-Vectorizer)를 사용하지 않습니다**.

- 임베딩은 **외부에서 생성**하여 검색 엔진에 전달
- 임베딩 설정은 **관리자 > 설정 > 문서** 페이지에서 구성
- 검색 시 `query_vector` 파라미터로 사전 계산된 임베딩 전달

---

## 주요 기능

### 1. 다중 벡터 DB 지원

| 엔진 | 클래스 | 파일 | 상태 |
|------|--------|---|---|
| Azure AI Search | `AzureSearchEngine` | `dbs/azure_search.py` | ✅ 구현 |
| PostgreSQL pgvector | `PgVectorEngine` | `dbs/pgvector.py` | ✅ 구현 |
| Elasticsearch | `ElasticsearchEngine` | `dbs/elasticsearch.py` | ✅ 구현 |
| Vertex AI Search | `VertexSearchEngine` | `dbs/vertex_search.py` | ✅ 구현 |
| Milvus | `MilvusEngine` | (없음) | ⚠️ 문서화되어 있으나 미구현 — 2026-04-08 기준 `dbs/__init__.py`에 export 안 됨 |

### 2. 통일된 인터페이스

```python
# 모든 엔진이 동일한 메서드 제공
async with engine:
    await engine.create_index()
    await engine.insert(documents)
    results = await engine.search(query, query_vector=embedding)
    await engine.delete(ids)
```

### 3. 관리자 설정 UI

- **관리자 > 설정 > 검색 엔진** 페이지에서 연결 정보 설정
- 엔진 타입별 동적 폼 렌더링
- 민감한 정보(API Key, Password)는 마스킹 처리

### 4. 스키마 프리셋

| 프리셋 | 함수 | 용도 |
|--------|------|------|
| Knowledge | `create_knowledge_config()` | 지식 베이스 (문서 RAG) |
| Glossary | `create_glossary_config()` | 용어집 (용어/약어) |
| DbSphere | `create_dbsphere_config()` | DB 메모리 (Q-SQL, DDL, 문서, 예제) |

### 5. Embedding Helpers (`embedding.py`)

`backend/extension_modules/search_engine/embedding.py` 에 auto-vectorizer 통합 헬퍼가 있다.

| 함수/클래스 | 역할 |
|---|---|
| `EmbeddingConfig` | 임베딩 엔진 설정 (engine, model, dimensions, api_key, api_base_url) |
| `get_embedding_config_from_app(app)` | `app.state.config`에서 `RAG_EMBEDDING_*` 읽어 `EmbeddingConfig` 생성 |
| `generate_embedding_async(text, config)` | 비동기 임베딩 생성 (OpenAI/Ollama/Azure OpenAI 지원) |
| `get_embedding_dimension(config)` | 모델별 차원 수 조회 (인덱스 생성 시 사용) |

**주의**: 이 helper는 검색 엔진에 임베딩을 "자동 생성해주는" 것이 아니라, **사용자가 search_engine을 쓰기 전에 임베딩을 생성할 때 공유하는 설정 레이어**다. 실제 검색 엔진 자체는 여전히 외부에서 생성된 벡터를 받아서 저장/검색만 한다.

### 6. Filter Builder / Translator

Panel/Knowledge 쿼리에서 사용자가 입력하는 filter 조건을 각 엔진의 query 언어로 변환한다.

| 파일 | 역할 |
|---|---|
| `filter_builder.py` | 공통 필터 AST 빌더 (`eq`, `neq`, `in`, `range`, `and`, `or`, `not`) |
| `filter_translator.py` | AST → 엔진별 쿼리 변환 (Azure OData, pgvector SQL, ES DSL, Vertex filter expression) |

**사용 예**:
```python
from extension_modules.search_engine.filter_builder import eq, range_, and_
from extension_modules.search_engine.filter_translator import translate_to_odata

flt = and_(eq("category", "AI"), range_("created_at", gte=1700000000))
odata_expr = translate_to_odata(flt)
# → "category eq 'AI' and created_at ge 1700000000"
```

### 7. Reranker (`reranker/`)

검색 결과의 재랭킹을 담당. 기본은 noop (검색 엔진 결과 그대로), 선택적으로 Vertex AI Ranker 사용 가능.

| 파일 | 역할 |
|---|---|
| `reranker/base.py` | `RerankerBase` 추상 클래스 (`rerank(query, documents) -> reranked_documents`) |
| `reranker/noop_ranker.py` | 아무것도 안 하는 기본 구현 |
| `reranker/vertex_ranker.py` | Vertex AI Ranker API 호출 (BGE cross-encoder 기반) |

**통합 지점**: `search_engine.search()` 호출 시 reranker 인자를 넘기면 검색 후 재랭킹 적용. 기본은 noop.

## 모듈 구조

```
backend/extension_modules/search_engine/
├── __init__.py                  # public export (get_configured_search_engine, create_*_config, ...)
├── base.py                       # SearchEngineBase (ABC)
├── connector.py                  # get_configured_search_engine() — app.state 기반 factory
├── models.py                     # EngineConfig, IndexConfig, DocumentItem, SearchQuery
├── schemas.py                    # create_knowledge_config, create_glossary_config, create_dbsphere_config
├── embedding.py                  # EmbeddingConfig, generate_embedding_async, get_embedding_dimension
├── filter_builder.py             # 공통 필터 AST
├── filter_translator.py          # 엔진별 쿼리 변환
├── dbs/                          # DB별 구현체
│   ├── __init__.py               # export 4종
│   ├── azure_search.py           # AzureSearchEngine
│   ├── pgvector.py               # PgVectorEngine
│   ├── elasticsearch.py          # ElasticsearchEngine
│   └── vertex_search.py          # VertexSearchEngine
└── reranker/                     # 재랭킹
    ├── base.py                   # RerankerBase
    ├── noop_ranker.py            # 기본 (no-op)
    └── vertex_ranker.py          # Vertex AI Ranker
```

---

## 상세 문서

| 문서 | 설명 |
|------|------|
| [01_overview.md](./01_overview.md) | 기능 상세 설명 및 사용 시나리오 |
| [02_architecture.md](./02_architecture.md) | 기술 아키텍처, 모델, API |
| [03_admin_settings.md](./03_admin_settings.md) | 관리자 설정 페이지 |
| [04_usage.md](./04_usage.md) | 코드에서 사용하는 방법 |

---

## 퀵 스타트

### 1. 관리자 설정

1. **관리자 > 설정 > 검색 엔진** 이동
2. Engine Type 선택 (예: Azure AI Search)
3. 연결 정보 입력:
   - Endpoint: `https://your-search.search.windows.net`
   - API Key: `your-api-key`
   - API Version: `2024-07-01`
4. **저장** 클릭

### 2. 코드에서 사용

```python
from extension_modules.search_engine import (
    get_configured_search_engine,
    create_knowledge_config,
    SearchQuery,
)

# 인덱스 설정
index_config = create_knowledge_config("kb_user123_knowledge456")

# 관리자 설정 기반 엔진 생성
engine = get_configured_search_engine(request.app, index_config)

if engine:
    async with engine:
        # 인덱스 생성
        await engine.create_index()

        # 문서 삽입 (임베딩 포함)
        await engine.insert([
            DocumentItem(
                id="doc1",
                content="Hello World",
                vector=embedding_vector,  # 외부에서 생성한 임베딩
            )
        ])

        # 검색 (임베딩 벡터 전달)
        query = SearchQuery(query="Hello", top_k=10)
        results = await engine.search(query, query_vector=query_embedding)
```

---

## 환경 변수 (총 18개)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_TYPE` | 검색 엔진 타입 (`azure_search` / `pgvector` / `elasticsearch` / `vertex_search` / `milvus` 미구현) | `""` |
| **Azure Search (3개)** | | |
| `SEARCH_ENGINE_AZURE_ENDPOINT` | Azure Search 엔드포인트 | `""` |
| `SEARCH_ENGINE_AZURE_API_KEY` | Azure Search API 키 | `""` |
| `SEARCH_ENGINE_AZURE_API_VERSION` | Azure Search API 버전 | `2024-07-01` |
| **pgvector (5개)** | | |
| `SEARCH_ENGINE_PGVECTOR_HOST` | PostgreSQL 호스트 | `""` |
| `SEARCH_ENGINE_PGVECTOR_PORT` | PostgreSQL 포트 | `5432` |
| `SEARCH_ENGINE_PGVECTOR_DATABASE` | 데이터베이스 이름 | `""` |
| `SEARCH_ENGINE_PGVECTOR_USER` | 사용자명 | `""` |
| `SEARCH_ENGINE_PGVECTOR_PASSWORD` | 비밀번호 | `""` |
| **Milvus (4개, 미구현)** | *config.py에는 정의되어 있으나 실제 엔진 사용 불가* | |
| `SEARCH_ENGINE_MILVUS_HOST` | Milvus 호스트 | `""` |
| `SEARCH_ENGINE_MILVUS_PORT` | Milvus 포트 | `19530` |
| `SEARCH_ENGINE_MILVUS_USER` | 사용자명 | `""` |
| `SEARCH_ENGINE_MILVUS_PASSWORD` | 비밀번호 | `""` |
| **Elasticsearch (5개)** | | |
| `SEARCH_ENGINE_ELASTICSEARCH_URL` | Elasticsearch URL | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_USERNAME` | 사용자명 | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_PASSWORD` | 비밀번호 | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_INDEX_NAME` | 기본 인덱스 이름 | `""` |
| `SEARCH_ENGINE_ELASTICSEARCH_VERIFY_CERTS` | TLS 검증 | `true` |
| **Vertex AI Search (3개)** | | |
| `SEARCH_ENGINE_VERTEX_PROJECT_ID` | GCP 프로젝트 ID | `""` |
| `SEARCH_ENGINE_VERTEX_LOCATION` | GCP 리전 | `global` |
| `SEARCH_ENGINE_VERTEX_SEARCH_ENGINE_ID` | Vertex Search Engine ID | `""` |

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `SEARCH_ENGINE_TYPE=milvus`로 설정했는데 엔진 로드 실패 | Milvus 엔진이 아직 미구현 | 현재는 Azure/pgvector/ES/Vertex 중 하나 선택 |
| `get_configured_search_engine` 이 `None` 반환 | `SEARCH_ENGINE_TYPE`이 빈 문자열 또는 오타 | Admin Settings → Search Engine에서 타입 설정 재확인 |
| 임베딩 차원 mismatch 오류 | 기존 인덱스는 모델 A (1536 dim)로 생성됐으나 현재 모델 B (768 dim)로 변경 | 인덱스 drop 후 재생성 (`POST /knowledge/{id}/sync`, `POST /glossary/{id}/sync` 등) |
| pgvector 연결 실패 | `SEARCH_ENGINE_PGVECTOR_HOST` 가 배포 환경 내부 네트워크 이름과 불일치 | 컨테이너 환경에서는 service name 사용 (`postgres` 등) |
| Azure Search 응답 지연 | API version이 구버전 | `SEARCH_ENGINE_AZURE_API_VERSION`을 `2024-07-01` 이상으로 |
| Vertex Ranker가 호출되지 않음 | `reranker=None` 또는 `NoopReranker` 기본 사용 | `search()` 호출 시 `reranker=VertexRanker(...)` 명시적 전달 |
| `SEARCH_ENGINE_PGVECTOR_HOST` | pgvector 호스트 | `localhost` |
| `SEARCH_ENGINE_PGVECTOR_PORT` | pgvector 포트 | `5432` |
| ... | (다른 엔진 설정) | ... |

> 전체 환경 변수 목록은 [02_architecture.md](./02_architecture.md#환경-변수) 참조

---

## 관련 파일

### Backend

- `backend/extension_modules/search_engine/` - 검색 엔진 모듈
  - `base.py` - 추상 베이스 클래스
  - `connector.py` - 팩토리 함수
  - `models.py` - Pydantic 모델
  - `schemas.py` - 스키마 프리셋
  - `dbs/` - 엔진별 구현체
- `backend/open_webui/config.py` - PersistentConfig 정의
- `backend/open_webui/routers/retrieval.py` - API 엔드포인트

### Frontend

- `src/lib/apis/retrieval/index.ts` - API 클라이언트
- `src/lib/components/admin/Settings/SearchEngine.svelte` - 설정 페이지
