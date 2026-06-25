# Core Memory (핵심 메모리 시스템)

Last Updated: 2026-03-22

## 1. 개요

장기/단기 메모리를 통해 사용자별 개인화된 대화 경험을 제공한다. 대화에서 핵심 사실을 자동 추출하고, 이후 대화에 자동으로 반영한다.

## 2. 장기 메모리

### 데이터 모델

```python
# backend/open_webui/models/memories.py
class Memory(Base):
    __tablename__ = "memory"
    id = Column(String, primary_key=True)       # UUID
    user_id = Column(String)                     # 소유자
    content = Column(Text)                       # fact 또는 profile 문서
    source = Column(String, default="manual")    # "manual" | "auto" | "profile"
    scope = Column(String, server_default="user") # "user" | "org"
    org_id = Column(String, nullable=True)
    retention_class = Column(String, server_default="standard")
    deleted_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### 메모리 유형

| source | 생성 방식 | 예시 | retention_class |
|--------|----------|------|----------------|
| `manual` | 사용자가 Manage에서 직접 추가 | "나는 Python 개발자다" | standard (180일) |
| `auto` | LLM이 대화에서 자동 추출 | "사용자는 Go를 배우기 시작했다" | temporary (30일) |
| `profile` | consolidation으로 자동 생성 | 구조화된 프로필 문서 | permanent |

## 3. 자동 추출 파이프라인

```python
# backend/extension_modules/agent/memory_extractor.py

async def auto_extract_memories(user_id, messages, chat_id, llm_config, app):
    """대화 완료 후 background task로 실행."""
```

### 흐름

```
대화 완료 → asyncio.create_task(auto_extract_memories())
  → Debounce 체크:
      Redis SET NX EX (multi-worker safe, atomic)
      Redis 없으면 in-process dict fallback
      같은 chat_id 5분 내 skip
  → LLM fact extraction:
      마지막 20개 메시지 (messages[-20:])
      User 메시지: 500자, Assistant 메시지: 200자로 truncate
      confidence ≥ threshold (기본 0.8, Admin에서 변경 가능)
  → Extraction prompt 구성:
      Entity types: DB에서 동적 로드 (fallback 5종)
      Glossary terms: 사용자 접근 가능한 용어집 terms 주입 (max 50, 60초 캐시)
        → "Already known terms (from glossary, do NOT extract as entities)"
  → Entity extraction (piggyback, 추가 호출 없음)
  → Vector dedup:
      distance < 0.10 → skip (너무 유사)
      distance < 0.15 → update 기존
      distance ≥ 0.15 → add 신규
  → DB + Vector DB 저장 (source="auto", max 100/user)
  → AuditLogger.log_create/log_update (공통 audit_log 테이블)
  → Entity upsert
  → [stored > 0] → maybe_consolidate_profile()
```

**`stored > 0` guard**: 모든 fact가 dedup skip되어 아무것도 저장되지 않으면 consolidation도 skip. 24h 조건은 실제 저장이 발생한 경우에만 평가된다.

### Extraction Model Config

Admin > Settings > Memory에서 추출 모델과 confidence threshold를 설정할 수 있다:
- **MEMORY_EXTRACTION_MODEL**: 추출에 사용할 모델. 미설정 시 Task Model → Chat Model 순으로 fallback.
- **MEMORY_EXTRACTION_CONFIDENCE**: confidence threshold (0.0~1.0, 기본 0.8). 이 값 미만의 fact는 필터링됨.

```
GET  /api/v1/memories/config        → 현재 설정 조회
POST /api/v1/memories/config        → 설정 변경 (AuditLogger.log_settings_change 기록)
```

### Extraction Prompt

entity type 목록은 DB에서 동적으로 로드하여 prompt에 주입. 추가로 glossary terms를 주입하여 이미 관리되는 용어의 중복 추출을 방지한다:

```python
def _build_extraction_prompt(user_id: str | None = None) -> str:
    types = EntityTypes.get_all_types()
    type_list = ", ".join(t.name for t in types)  # "tech, project, person, ..."
    prompt = FACT_EXTRACTION_PROMPT_TEMPLATE.format(entity_types=type_list)

    # Glossary terms 주입 (60초 캐시, max 50 terms)
    if user_id:
        glossary_terms = _load_glossary_terms(user_id)
        if glossary_terms:
            prompt += f"\n\nAlready known terms (from glossary, do NOT extract as entities): ..."
    return prompt
```

### Debounce (Multi-worker Safe)

```python
_DEBOUNCE_SECONDS = 300  # 5분

def _check_debounce(chat_id: str) -> bool:
    redis = _get_redis_client()
    if redis:
        # Atomic SET NX EX: 첫 caller만 통과 (TOCTOU race 없음)
        was_set = redis.set(f"memory:debounce:{chat_id}", "1", ex=300, nx=True)
        return not was_set
    # Fallback: in-process dict
    ...
```

### LLM 출력 형식

```json
[
  {
    "fact": "사용자는 Go 언어를 배우기 시작했다",
    "category": "tech_preference",
    "confidence": 0.9,
    "entities": [{"name": "Go", "type": "tech"}]
  }
]
```

JSON 파싱은 3단계 fallback: direct parse → bracket extraction → trailing comma fix.

## 4. Profile Consolidation

```python
# backend/extension_modules/agent/memory_consolidator.py

async def consolidate_user_profile(user_id, llm_config, app):
    """전체 facts → LLM → 구조화된 Profile 문서."""
```

### 트리거 조건 (OR, `stored > 0`일 때만 평가)

- 신규 facts ≥ 5개
- 마지막 consolidation 후 24시간 + 신규 facts ≥ 1개

### Profile 구조

```markdown
## Role & Work
- Cloocus 소속 Nate, 데이터팀 근무

## Tech Preferences
- Python/FastAPI, Docker/Kubernetes

## Current Projects
- Azure DevOps CI/CD 파이프라인

## Constraints & Requirements
- SQLAlchemy 2.0 async 패턴

## Communication Style
- 한국어/영어 능숙

## Personal
- LangChain/LangGraph 에이전트 개발
```

### Profile Upsert

`Memories.upsert_profile()`은 기존 profile 유무에 따라 CREATE 또는 UPDATE:
- 신규 생성: `AuditLogger.log_create("memory", ...)`
- 업데이트: `AuditLogger.log_update("memory", ...)`
- 판별 기준: `abs(result.created_at - result.updated_at) < 2` (2초 이내면 신규)

## 5. Selective Retrieval

```python
# backend/extension_modules/agent/unified_agent.py

MEMORY_SELECTIVE_THRESHOLD = 20
MEMORY_SEARCH_TOP_K = 10
```

### 동작

```
memory_count = get_memory_count_by_user_id(user_id)

[count < 20]                        [count ≥ 20]
    ↓                                    ↓
full dump (전체 로드)             Profile 로드 + vector search top-10
    ↓                                    ↓
_format_memories()               source="profile" 제외 (중복 방지)
    ↓                                    ↓
                                  Entity boost (매칭 메모리 우선)
    ↓                                    ↓
              user_memory_context
                      ↓
           ### Profile + ### Relevant Context + ### Organization Context
                      ↓
           get_unified_final_answer_prompt(user_memory_context=...)
```

### Profile 중복 방지

Selective retrieval 시 vector search 결과에서 `source="profile"`인 메모리를 필터링한다. Profile은 `get_profile_by_user_id()`로 별도 로드되어 `### Profile` 섹션에 이미 주입되므로, facts에도 포함되면 중복이 된다.

### Entity Search Boost

```python
# 쿼리에서 entity 매칭 → 해당 메모리를 상위로
query_entities = MemoryEntities.find_matching_entities(user_id, query_text)
entity_by_memory = {e.memory_id: {names} for e in all_entities}
boosted = [mem for mem in memories if entity_by_memory.get(mem.id) & query_entity_names]
rest = [mem for mem in memories if mem not in boosted]
memories = boosted + rest
```

## 6. 단기 메모리

- `MAX_HISTORY_MESSAGES = 20` — 최근 20턴 자동 포함 **(모든 모델)**
- `get_recent_history(n=30, search_query=None)` — 20턴 이전 대화를 DB에서 조회 **(에이전트만)**
  - `n`: 조회 메시지 수 (기본 30, 최대 50)
  - `search_query`: 선택적 키워드 필터링
  - 결과는 `user_memory_context`에 `## Retrieved Conversation History` 섹션으로 merge

**참고**: 장기 메모리(Profile, Selective Retrieval, 자동 추출, org memory)는 모든 모델에서 동작한다. `UnifiedAgent._run_stream()`을 모든 모델이 경유하기 때문.

## 7. 조직 메모리 (Org Memory)

- Admin이 생성, `scope="org"`, `retention_class="permanent"`
- **memory_enabled 토글과 무관하게 항상 주입**: 조직 메모리는 관리자가 주입하는 컨텍스트이므로 개인 설정으로 비활성화할 수 없음
- Vector DB 미사용 — SQL full dump로 로드

```python
# unified_agent.py — 개인 메모리와 별개 블록
if user_id:  # memory_enabled 체크 없음
    org_memories = Memories.get_org_memories(unit.organization_id)
```

## 8. 프론트엔드

### ManageModal (사용자)

- Settings > Personalization > Manage
- 메모리 목록 (Auto 뱃지 표시, 날짜 dayjs 포맷)
- Profile Summary 접이식 섹션 (Auto-generated 뱃지)
- 수동 추가/수정/삭제
- "Clear All Memories" 버튼 + 확인 다이얼로그

### 메모리 토글

- `settings.memory == true` 체크 후 개인 메모리 로드
- OFF 시 개인 메모리 미주입 (org memory는 여전히 주입)
- "Experimental" 뱃지 표시
