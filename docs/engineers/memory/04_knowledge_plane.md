# Knowledge Plane (지식 엔티티)

Last Updated: 2026-03-22

## 1. 개요

대화에서 추출된 메모리에서 명명 개체(entity)를 인식·저장하고, 이를 검색 품질 향상에 활용한다. 기존 fact extraction에 piggyback하여 추가 LLM 비용 없이 동작한다. Glossary 모듈과 연동하여 이미 관리되는 용어의 중복 추출을 방지한다.

## 2. 데이터 모델

### memory_entity 테이블

```python
class MemoryEntity(Base):
    __tablename__ = "memory_entity"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)           # "fastapi", "go", "nate" (소문자 정규화)
    entity_type = Column(String, nullable=False)     # "tech", "project", "person"
    memory_id = Column(String, nullable=False)       # 추출 원본 메모리 ID (upsert 시 갱신)
    user_id = Column(String, nullable=False)
    org_id = Column(String, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    # UNIQUE(name, entity_type, user_id) — 같은 entity는 최신 memory_id로 갱신
```

**Entity name 정규화**: 모든 entity name은 `.lower()`로 정규화하여 저장. 대소문자 무관 매칭 보장.

**UNIQUE 제약**: `(name, entity_type, user_id)` — 동일 사용자에 대해 같은 이름+타입의 entity는 1개만 유지. `upsert_entity()`는 기존 row의 `memory_id`를 최신 추출 메모리로 갱신.

### memory_entity_type 테이블

```python
class MemoryEntityType(Base):
    __tablename__ = "memory_entity_type"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)           # "tech", "project"
    description = Column(String, nullable=True)      # admin 설명
    org_id = Column(String, nullable=True)           # 글로벌 (org별 미지원)
    created_at = Column(BigInteger, nullable=False)
    # UNIQUE(name, org_id)
```

### 기본 Entity Types (시드)

| name | description |
|------|-------------|
| tech | Technologies, frameworks, tools, languages |
| project | Project names and products |
| person | People names |
| organization | Companies, teams, departments |
| concept | Domain concepts and other entities |

### Seeding 시점

두 곳에서 idempotent하게 seed:
1. **Migration** `o6a7b8c9d0e1`: entity 테이블 생성 시 5개 기본 타입 삽입
2. **Lifespan startup** `main.py`: `EntityTypes.seed_defaults()` 호출 — migration 누락 방어용

Admin이 Settings > Memory > Knowledge Entities에서 커스텀 타입 추가/삭제 가능.

## 3. Entity Extraction

### 동작 방식

기존 `memory_extractor.py`의 fact extraction LLM 호출에 entity 추출 지시를 포함. **별도 LLM 호출 없음.**

```
FACT_EXTRACTION_PROMPT_TEMPLATE:
  "Entity types: {entity_types}"  ← DB에서 동적 로드

LLM 출력:
  [{"fact": "...", "confidence": 0.9,
    "entities": [{"name": "Go", "type": "tech"}]}]
```

### Dynamic Entity Type Loading

```python
def _build_extraction_prompt(user_id: str | None = None) -> str:
    types = EntityTypes.get_all_types()   # DB 조회
    type_list = ", ".join(t.name for t in types)
    prompt = FACT_EXTRACTION_PROMPT_TEMPLATE.format(entity_types=type_list)

    # Glossary terms 주입 (§4 참조)
    if user_id:
        glossary_terms = _load_glossary_terms(user_id)
        if glossary_terms:
            prompt += f"\n\nAlready known terms (from glossary, do NOT extract as entities): ..."

    return prompt
```

- 매 extraction 호출마다 DB에서 최신 타입 목록 조회
- Admin이 타입 추가 → 다음 대화부터 바로 반영
- DB 조회 실패 시 기본 5개 타입으로 fallback

### Entity 저장

```python
def _store_entities(fact_data, memory_id, user_id):
    entities = fact_data.get("entities", [])
    for ent in entities:
        MemoryEntities.upsert_entity(
            name=ent["name"],        # 소문자로 정규화
            entity_type=ent["type"],
            memory_id=memory_id,     # 원본 메모리 연결
            user_id=user_id,
        )
```

- `upsert_entity`: name+type+user_id가 이미 있으면 memory_id만 갱신
- 실패 시 `logger.debug`만 — entity 저장 실패가 메모리 저장을 막지 않음

## 4. Glossary Integration

### 목적

용어집(Glossary)에 이미 등록된 term을 entity로 중복 추출하는 것을 방지한다. 예: glossary에 "FastAPI"가 등록되어 있으면 entity로 재추출하지 않음.

### 동작

```python
# memory_extractor.py

_glossary_terms_cache: dict[str, tuple[list[str], float]] = {}
_GLOSSARY_CACHE_TTL = 60  # 60 seconds

def _load_glossary_terms(user_id: str) -> list[str]:
    """Load glossary term names accessible to the user (cached 60s)."""
    # 캐시 히트 → 바로 반환
    # 캐시 미스 → Glossaries.get_glossaries_by_user_id(user_id, "read")
    #   → data.entries[].term 추출
    #   → 캐시 저장 + 반환
```

### 제약

- **Max 50 terms**: prompt 토큰 절약을 위해 최대 50개 term만 주입
- **60초 캐시**: 매 extraction마다 DB 조회 방지 (in-process dict 캐시)
- **실패 무시**: glossary 로드 실패 시 빈 리스트 반환 — extraction은 계속 진행
- **사용자 접근 가능 glossary만**: `"read"` 권한으로 필터링

### Prompt 주입 형태

```
Already known terms (from glossary, do NOT extract as entities): FastAPI, Docker, Kubernetes, ...
```

## 5. Entity Search Boost

### 동작

`_load_selective_memories()`에서 vector search 결과를 entity 매칭으로 재정렬:

```python
# 1. 쿼리에서 entity 매칭
query_entities = MemoryEntities.find_matching_entities(user_id, query_text)

# 2. 전체 entity를 memory_id별로 그룹핑 (N+1 방지)
all_entities = MemoryEntities.get_entities_by_user_id(user_id)
entity_by_memory = {memory_id: {entity_names}}

# 3. 매칭된 entity가 있는 메모리를 상위로
boosted = [mem for mem in memories if entity_match]
rest = [mem for mem in memories if no_match]
memories = boosted + rest
```

### find_matching_entities

단순 substring matching — entity name이 쿼리 텍스트에 포함되는지 확인:

```python
def find_matching_entities(self, user_id, query_text):
    entities = self.get_entities_by_user_id(user_id)
    query_lower = query_text.lower()
    return [e for e in entities if e.name in query_lower]
```

NER 모델 불필요. entity 테이블이 dictionary 역할.

### 안전장치

- 전체 try/except로 감싸 — entity boost 실패 시 기본 vector search 결과 그대로 사용
- entity가 없는 사용자 → boost 스킵 (성능 영향 없음)

## 6. Entity 통계 조회

### 그룹별 집계

```python
MemoryEntities.get_entities_grouped_by_type()
# Returns: [{"entity_type": "tech", "count": 45, "examples": ["fastapi", "docker", ...]}]
```

- entity_type별 count + 상위 5개 examples 반환
- Admin > Memory > Knowledge Entities에서 사용

## 7. Admin API

```
GET    /api/v1/admin/memory/entity-types              → entity type 목록
POST   /api/v1/admin/memory/entity-types              → 타입 추가 {name, description}
DELETE /api/v1/admin/memory/entity-types/{id}          → 타입 삭제
GET    /api/v1/admin/memory/entities?entity_type=tech  → entity 통계 (타입별 count + examples)
```

### entities 응답 예시

```json
[
  {
    "entity_type": "tech",
    "count": 45,
    "examples": ["fastapi", "docker", "go", "postgresql", "python"]
  },
  {
    "entity_type": "project",
    "count": 12,
    "examples": ["cloosphere", "dbsphere", "kbsphere"]
  }
]
```

## 8. 제한사항

- **Entity type은 글로벌**: org별 분리 미지원 (스키마에 org_id 준비됨)
- **LLM 판단 의존**: entity 분류 정확도는 LLM에 의존
- **단순 substring matching**: 쿼리-entity 매칭이 키워드 기반 (NER 없음)
- **관계 없음**: entity 간 관계(uses, belongs_to 등) 미저장
- **Glossary terms max 50**: 대규모 glossary에서 일부만 반영
