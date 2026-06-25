# 검색 엔진 모듈 상세

## 기능 설명

검색 엔진 모듈은 다양한 벡터 데이터베이스를 통일된 인터페이스로 추상화하여, 벡터 DB 종류와 관계없이 동일한 코드로 검색 기능을 구현할 수 있게 합니다.

## 지원 엔진

### Azure AI Search

Microsoft Azure의 관리형 검색 서비스입니다.

**특징:**
- 하이브리드 검색 (벡터 + 키워드 + 시맨틱)
- 시맨틱 리랭킹 지원
- 관리형 서비스로 운영 부담 최소화

**설정 항목:**
| 항목 | 설명 | 예시 |
|------|------|------|
| Endpoint | 검색 서비스 URL | `https://my-search.search.windows.net` |
| API Key | Admin 또는 Query 키 | `xxxxxxxx` |
| API Version | REST API 버전 | `2024-07-01` |

### PostgreSQL pgvector

PostgreSQL의 벡터 확장입니다.

**특징:**
- 기존 PostgreSQL 인프라 활용
- 트랜잭션 지원
- 오픈소스

**설정 항목:**
| 항목 | 설명 | 예시 |
|------|------|------|
| Host | DB 호스트 | `localhost` |
| Port | DB 포트 | `5432` |
| Database | 데이터베이스 이름 | `postgres` |
| User | 사용자 이름 | `postgres` |
| Password | 비밀번호 | `****` |

### Milvus

오픈소스 벡터 데이터베이스입니다.

**특징:**
- 대규모 벡터 처리 최적화
- 분산 아키텍처 지원
- GPU 가속 지원

**설정 항목:**
| 항목 | 설명 | 예시 |
|------|------|------|
| Host | Milvus 호스트 | `localhost` |
| Port | Milvus 포트 | `19530` |
| User | 사용자 (선택) | `""` |
| Password | 비밀번호 (선택) | `""` |

### Elasticsearch

Elastic의 벡터 검색 기능입니다.

**특징:**
- 전문 검색 + 벡터 검색 통합
- 기존 Elasticsearch 인프라 활용
- 다양한 분석기 지원

**설정 항목:**
| 항목 | 설명 | 예시 |
|------|------|------|
| URL | Elasticsearch URL | `http://localhost:9200` |
| API Key | API 키 (선택) | `""` |
| User | 사용자 (선택) | `""` |
| Password | 비밀번호 (선택) | `""` |
| CA Certs | CA 인증서 경로 (선택) | `/path/to/ca.crt` |

### Google Vertex AI Search

Google Cloud의 검색 서비스입니다.

**특징:**
- Google Cloud 생태계 통합
- 관리형 서비스
- 서비스 계정 인증

**설정 항목:**
| 항목 | 설명 | 예시 |
|------|------|------|
| Project ID | GCP 프로젝트 ID | `my-project-123` |
| Location | 리전 | `us-central1` |
| Service Account Key | JSON 키 파일 내용 | `{"type": "service_account", ...}` |

## 사용 시나리오

### 시나리오 1: 지식 베이스 검색

```
사용자 질문: "연차 신청 방법이 뭐야?"
        ↓
임베딩 생성 (RAG 설정 사용)
        ↓
검색 엔진 쿼리 (query_vector + 키워드)
        ↓
관련 문서 반환 (연차 규정.pdf, HR 가이드.docx)
        ↓
LLM에 컨텍스트로 전달
        ↓
답변 생성
```

### 시나리오 2: DbSphere 에이전트 메모리

```
사용자 질문: "지난번에 작성한 SQL 쿼리 다시 보여줘"
        ↓
질문 임베딩 생성
        ↓
에이전트 메모리 검색 (과거 도구 사용 기록)
        ↓
유사한 질문/쿼리 반환
        ↓
에이전트가 참고하여 응답
```

### 시나리오 3: 용어집 (Glossary)

```
문서 처리 중 "EBITDA" 용어 발견
        ↓
용어 임베딩 생성
        ↓
용어집 검색
        ↓
정의 반환: "세전·이자지급전·감가상각전 영업이익"
        ↓
문서에 주석 추가
```

## 임베딩 전략

### 왜 자동 벡터기를 사용하지 않나요?

1. **토큰 사용량 모니터링**: 임베딩 토큰을 별도로 추적하여 비용 관리
2. **유연한 임베딩 모델 선택**: 문서 설정에서 임베딩 모델 변경 가능
3. **일관된 임베딩**: 색인과 검색에서 동일한 임베딩 모델 보장

### 임베딩 흐름

```
색인 시:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  문서 청크   │────▶│  임베딩 API  │────▶│  검색 엔진   │
│  (text)     │     │  (RAG 설정)  │     │  (vector)   │
└─────────────┘     └─────────────┘     └─────────────┘

검색 시:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  사용자 쿼리 │────▶│  임베딩 API  │────▶│  검색 엔진   │
│  (text)     │     │  (RAG 설정)  │     │  search()   │
└─────────────┘     └─────────────┘     └─────────────┘
```

### 임베딩 설정 위치

| 설정 | 위치 |
|------|------|
| 임베딩 엔진 | 관리자 > 설정 > 문서 > RAG Embedding Engine |
| 임베딩 모델 | 관리자 > 설정 > 문서 > RAG Embedding Model |
| Azure OpenAI 연결 | 관리자 > 설정 > 문서 > Azure OpenAI URL/Key |

## 스키마 프리셋

각 용도에 맞는 사전 정의된 스키마를 제공합니다.

### Knowledge (지식 베이스)

```python
KNOWLEDGE_COLUMNS = [
    # 기본 필드: id, content, vector, metadata, collection
    # 추가 필드 없음
]

def create_knowledge_config(index_name: str, vector_dim: int = 3072) -> IndexConfig:
    return IndexConfig(
        index_name=index_name,
        column_info=KNOWLEDGE_COLUMNS,
        vector_dim=vector_dim,
    )
```

### Glossary (용어집)

```python
GLOSSARY_COLUMNS = [
    ColumnInfo(name="term", type="string"),
    ColumnInfo(name="definition", type="string"),
    ColumnInfo(name="category", type="string"),
    ColumnInfo(name="synonyms", type="string", is_collection=True),
]

def create_glossary_config(index_name: str, vector_dim: int = 3072) -> IndexConfig:
    return IndexConfig(
        index_name=index_name,
        column_info=GLOSSARY_COLUMNS,
        vector_dim=vector_dim,
    )
```

### DbSphere (DB 메타데이터)

```python
DBSPHERE_COLUMNS = [
    ColumnInfo(name="question", type="string"),
    ColumnInfo(name="tool_name", type="string"),
    ColumnInfo(name="args_json", type="string"),
    ColumnInfo(name="success", type="boolean"),
]

def create_dbsphere_config(index_name: str, vector_dim: int = 3072) -> IndexConfig:
    return IndexConfig(
        index_name=index_name,
        column_info=DBSPHERE_COLUMNS,
        vector_dim=vector_dim,
    )
```

## 제한 사항

1. **동시 연결**: 각 엔진별 최대 연결 수 제한 있음
2. **인덱스 크기**: 엔진별 최대 문서 수/크기 제한
3. **벡터 차원**: 일부 엔진은 특정 차원만 지원
4. **실시간 색인**: 색인 후 검색 가능까지 지연 있을 수 있음 (eventually consistent)

## 성능 고려사항

### 배치 처리

대량 문서 색인 시 배치 처리 권장:

```python
# 좋은 예 - 배치 색인
documents = [doc1, doc2, ..., doc100]
await engine.insert(documents)  # 한 번에 처리

# 나쁜 예 - 개별 색인
for doc in documents:
    await engine.insert([doc])  # 100번 호출
```

### 연결 관리

async context manager 사용으로 리소스 자동 정리:

```python
# 권장
async with engine:
    await engine.search(...)
# 자동으로 close() 호출

# 비권장 (수동 정리 필요)
engine = get_search_engine(...)
try:
    await engine.search(...)
finally:
    await engine.close()
```
