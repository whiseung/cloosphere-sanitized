# Glossary 개요

## 1. 소개

Glossary(용어집)는 조직 내에서 사용하는 도메인 특화 용어, 약어, 업무 규칙 등을 체계적으로 관리하는 기능입니다. AI 에이전트가 대화 중 이러한 용어를 자동으로 참조하여 더 정확한 응답을 생성할 수 있습니다.

## 2. 사용 시나리오

### 시나리오 1: 도메인 용어 정의

**문제**: 신입 직원이나 외부 협력사가 조직 내 전문 용어를 이해하지 못함

**해결**: Glossary에 용어를 등록하면 AI가 자동으로 설명

```
사용자: "KPI 리포트에서 ARPU가 낮게 나왔는데 왜 그럴까?"

AI (Glossary 참조 후):
"ARPU(Average Revenue Per User, 사용자당 평균 매출)가 낮아진 원인을
분석해보겠습니다..."
```

### 시나리오 2: 약어 해석

**문제**: 회사 내부에서만 사용하는 약어가 많음

**해결**: 약어와 전체 명칭을 별칭으로 등록

```
용어: CRM
별칭: Customer Relationship Management, 고객 관계 관리
정의: 고객과의 관계를 관리하고 분석하는 시스템...
```

### 시나리오 3: 업무 규칙 참조

**문제**: 업무 처리 규칙이 문서에 분산되어 있음

**해결**: 주요 업무 규칙을 용어로 등록

```
용어: 환불 정책
정의: 구매 후 7일 이내 미사용 상품에 한해 전액 환불 가능.
      사용 후에는 50% 차감 후 환불. 디지털 상품은 환불 불가.
```

## 3. 핵심 기능

### 3.1 용어 구조

각 용어는 다음 필드를 가집니다:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `term` | string | O | 용어명 (예: RAG) |
| `definition` | string | O | 용어 정의 |
| `category` | string | X | 카테고리 (예: AI, 마케팅) |
| `aliases` | string[] | X | 별칭 목록 |

### 3.2 검색 기능

- **키워드 검색**: 용어명, 별칭, 정의 내 키워드 검색
- **벡터 검색**: 임베딩 기반 의미론적 유사 검색
- **카테고리 필터**: 특정 카테고리 용어만 검색

### 3.3 접근 제어

- **소유자**: Glossary 생성자 (전체 권한)
- **읽기 권한**: 그룹/조직 단위별 조회 권한
- **쓰기 권한**: 그룹/조직 단위별 수정 권한

## 4. 검색 엔진 연동

Glossary는 Search Engine 모듈을 사용하여 용어를 벡터화하고 검색합니다.

### 인덱스 스키마

```python
# extension_modules/search_engine/schemas.py

def create_glossary_config(index_name: str) -> IndexConfig:
    return IndexConfig(
        index_name=index_name,
        columns=[
            ColumnDefinition(
                name="term",
                data_type="text",
                searchable=True,
            ),
            ColumnDefinition(
                name="definition",
                data_type="text",
                searchable=True,
            ),
            ColumnDefinition(
                name="category",
                data_type="text",
                filterable=True,
            ),
            ColumnDefinition(
                name="aliases",
                data_type="text",
                searchable=True,
            ),
            ColumnDefinition(
                name="vector",
                data_type="vector",
                vector_dimensions=1536,  # text-embedding-ada-002
            ),
        ],
    )
```

### 색인 흐름

```
용어 추가/수정
    │
    ▼
┌─────────────────┐
│ 임베딩 생성     │ ← OpenAI/Azure Embedding API
│ (term + def)    │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 검색 엔진 색인  │ ← create_glossary_config() 스키마 사용
└─────────────────┘
```

## 5. Agent 연동

### LangChain Tool

```python
# extension_modules/glossary/tools.py

class GlossarySearchTool(BaseTool):
    name = "glossary_search"
    description = "조직 내 용어 정의를 검색합니다"

    async def _arun(self, query: str) -> str:
        # 검색 엔진에서 용어 검색
        results = await search_engine.search(
            SearchQuery(query=query, top_k=5),
            query_vector=embedding
        )

        # 결과 포맷팅
        if results:
            return "\n".join([
                f"- {r.term}: {r.definition}"
                for r in results
            ])
        return "관련 용어를 찾을 수 없습니다."
```

### 에이전트에서 사용

```python
# 에이전트 생성 시 Glossary 도구 추가
tools = [
    GlossarySearchTool(
        glossary_ids=metadata.get("glossary_ids", []),
        search_engine=engine,
    ),
    # ... 다른 도구들
]

agent = create_react_agent(llm, tools)
```

## 6. 일괄 가져오기/내보내기

### CSV 형식

```csv
term,definition,category,aliases
RAG,"Retrieval Augmented Generation의 약자로...",AI,"검색 증강 생성"
LLM,"Large Language Model의 약자로...",AI,"대규모 언어 모델"
```

### JSON 형식

```json
{
  "terms": [
    {
      "term": "RAG",
      "definition": "Retrieval Augmented Generation의 약자로...",
      "category": "AI",
      "aliases": ["검색 증강 생성"]
    }
  ]
}
```

## 7. 모범 사례

### 용어 작성 가이드

1. **명확한 정의**: 전문 지식이 없는 사람도 이해할 수 있게 작성
2. **별칭 활용**: 영문 약어, 한글 번역, 유사어 모두 등록
3. **카테고리 일관성**: 조직 전체에서 동일한 카테고리 체계 사용
4. **정기 업데이트**: 새 용어 추가, 정의 변경 시 즉시 반영

### 성능 최적화

1. **인덱스 분리**: 도메인별로 별도 Glossary 생성
2. **검색 범위 제한**: 에이전트에 필요한 Glossary만 연결
3. **캐싱**: 자주 검색되는 용어는 캐싱 고려
