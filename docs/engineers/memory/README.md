> Last Updated: 2026-04-08

# Memory (메모리) 모듈

Cloosphere의 장기/단기 메모리 시스템에 대한 기술 문서입니다.

> **문서 구조 참고**: 이 폴더는 토픽 기반 네이밍 (`01_core_memory`, `02_governance`, `03_admin_ui`, `04_knowledge_plane`)을 사용합니다. Feature의 복잡도가 높아 일반 `01_overview / 02_architecture / ...` 구조보다 토픽별 분리가 적합하기 때문입니다 — README가 overview + quickstart 역할을 대체합니다.

## 목차

1. [개요](#개요)
2. [주요 기능](#주요-기능)
3. [상세 문서](#상세-문서)
4. [퀵 스타트](#퀵-스타트)

---

## 개요

메모리 모듈은 사용자와의 대화에서 핵심 정보를 추출·저장하고, 이후 대화에 자동으로 반영하여 개인화된 응답을 제공합니다. 엔터프라이즈 거버넌스(retention, audit, 조직 메모리)와 Knowledge Plane(entity extraction)을 포함합니다.

### 주요 개념

| 개념 | 설명 |
|------|------|
| **장기 메모리** | 대화에서 추출된 사실(fact) — 사용자 역할, 기술 선호도, 프로젝트 등 |
| **단기 메모리** | 현재 대화의 히스토리 — MAX_HISTORY 20턴 (모든 모델) + get_recent_history tool (에이전트만, 20턴 이전 조회) |
| **Profile** | 개별 facts를 LLM이 구조화 문서로 압축한 요약 (source="profile") |
| **Selective Retrieval** | 메모리 ≥ 20개 시 Profile + vector search top-k만 주입 |
| **Retention Policy** | 클래스별 TTL — temporary(30일), standard(180일), permanent(무기한) |
| **Soft Delete** | 삭제 시 deleted_at 설정, 30일 후 hard delete |
| **Audit Log** | 시스템 공통 `audit_log` 테이블에 `resource_type="memory"` 로 기록 (`AuditLogger`) |
| **Org Memory** | admin이 생성, 조직 전체 사용자 대화에 주입 (memory 토글 무관) |
| **Entity** | 메모리에서 추출된 명명 개체 (tech, project, person 등) |

### 아키텍처

> **주입 지점 (Injection Point)**: 모든 메모리 로딩 + 프롬프트 주입은 `backend/extension_modules/agent/unified_agent.py::_run_stream()` 에서 일어납니다. Tool-based 접근이 아닌 pre-model hook 방식 — LLM 호출 직전에 System Prompt에 `## User Memory` 섹션을 동적으로 추가합니다. 다른 에이전트(DBSphere, KBSphere)는 unified_agent를 거치지 않으므로 이 주입 로직이 적용되지 않습니다.

```
Write Path:
  대화 완료 → auto_extract_memories() (background)
    → Debounce 체크 (Redis SET NX EX, fallback in-process dict, 5분)
    → LLM fact extraction (마지막 20개 메시지, confidence ≥ threshold)
      ├── User message: 500자, Assistant: 200자로 truncate
      └── Glossary terms 주입 (중복 entity 방지, 60초 캐시, max 50 terms)
    → Entity extraction (piggyback, 추가 LLM 호출 없음)
    → Vector dedup (distance: skip < 0.10, update < 0.15, add ≥ 0.15)
    → DB + Vector DB 저장 (retention_class 자동 설정, max 100/user)
    → AuditLogger.log_create/log_update (공통 audit_log 테이블)
    → Entity upsert (memory_entity 테이블)
    → [stored > 0] → maybe_consolidate_profile() 트리거

Read Path:
  _run_stream() 시작
    → 개인 메모리 (memory_enabled=True 일 때만):
      count < 20 → full dump | ≥ 20 → Profile + vector top-k
      Profile은 별도 로드, selective facts에서 source="profile" 제외 (중복 방지)
      Entity boost: 쿼리에 매칭되는 entity가 있는 메모리 우선
    → Org 메모리 (memory_enabled 무관, 항상 로드):
      소속 조직의 org memory full dump
    → "## User Memory" 섹션으로 프롬프트 주입
      ├── ### Profile
      ├── ### Relevant Context
      └── ### Organization Context

Governance:
  Retention Worker (asyncio, 1시간 주기, startup 후 첫 sleep 경과 후 실행)
    → TTL 만료 메모리 soft delete + Vector DB 즉시 삭제
    → 30일 지난 soft-deleted 메모리 hard delete (DB 물리 삭제)
    → AuditLogger.log_delete (actor 미지정 — background task)
```

### 하이브리드 아키텍처 포지셔닝

| 구분 | 접근 방식 | 참고 플랫폼 |
|------|----------|------------|
| Write-time | 실시간 fact + entity extraction | Mem0 |
| Read-time | Profile 항상 주입 + vector top-k 보충 | Claude |
| Injection | pre-model hook (tool 기반 아님) | LangGraph |
| Governance | retention policy + audit log (통합) + soft delete | NIST AI 600-1 |
| Org Memory | admin 수동 생성, 전체 조직 주입 (토글 무관) | MS Copilot |
| Entity | prompt 기반 extraction, 정규화 테이블, glossary 연동 | Zep + Mem0 하이브리드 |

---

## 주요 기능

### 1. 자동 메모리 추출 (Phase 2)

- **LLM fact extraction**: 대화에서 핵심 사실 자동 추출 (confidence ≥ threshold, 기본 0.8)
- **Extraction Model Config**: Admin에서 모델 선택 + confidence threshold 조정 가능
- **Vector dedup**: 기존 메모리와 유사도 비교하여 중복 방지
- **자동 메모리 상한**: 사용자당 최대 100개
- **Debounce**: 같은 채팅 5분 내 재추출 방지 (Redis 또는 in-process)
- **Glossary 연동**: 용어집에 등록된 term은 entity 추출에서 제외 (60초 in-memory 캐시, max 50 terms). **Fallback**: Glossary API 실패 시 cache miss로 취급되어 extraction은 정상 진행됨 (단, 중복 entity 제외 효과만 일시적으로 손실) — `memory_extractor.py::_get_glossary_terms_cached()`

### 2. Selective Retrieval + Profile (Phase 3)

- **Profile Consolidation**: 개별 facts → LLM이 구조화 문서로 압축
- **조건부 전환**: < 20개 → full dump, ≥ 20개 → Profile + vector top-k
- **Profile 중복 방지**: selective facts에서 source="profile" 자동 제외
- **Vector search fallback**: 검색 실패 시 최근 10개 recency 기반

### 3. 거버넌스 (Phase 4)

- **Retention Policy**: source 기반 TTL 자동 분류 (auto=30d, manual=180d, profile=∞)
- **Soft Delete**: 삭제 시 deleted_at 설정, Vector DB 즉시 삭제, 30일 후 hard delete
- **Audit Log**: `AuditLogger` → 공통 `audit_log` 테이블에 `resource_type="memory"` 로 기록
- **Retention Worker**: asyncio 1시간 주기 배치 처리 (expiration + hard delete 모두에서 vector DB 삭제)

### 4. Admin Settings UI (Phase 5)

- **Memory 탭**: 2단 구조 — Configuration(상단 2컬럼 flat) + Management(하단 4탭)
- **Configuration**: Extraction Config (모델 + confidence slider) / Retention Policies (TTL 편집)
- **Management 탭**: Audit Log / User Memories / Organization Memory / Knowledge Entities
- **공통 컴포넌트**: Selector, Button(loading), Badge, Input, LabelBase, ConfirmDialog
- **a11y**: role="tablist", aria-label, ConfirmDialog(삭제 확인), focus-visible:ring

### 5. Knowledge Plane (Phase 5)

- **Entity Extraction**: fact extraction에 piggyback (추가 LLM 비용 없음)
- **Dynamic Entity Types**: DB에서 entity type 목록 동적 로드 → extraction prompt에 주입
- **Glossary Dedup**: 용어집에 등록된 term은 entity로 추출하지 않음
- **Entity Search Boost**: 쿼리에 매칭되는 entity가 태그된 메모리를 selective retrieval에서 우선
- **Admin Entity Management**: entity type 추가/삭제, entity 카운트/예시 조회

---

## 상세 문서

| 문서 | 설명 |
|------|------|
| [01_core_memory.md](./01_core_memory.md) | 장기/단기 메모리, 자동 추출, selective retrieval, profile |
| [02_governance.md](./02_governance.md) | retention policy, audit log (공통 테이블), soft delete, retention worker |
| [03_admin_ui.md](./03_admin_ui.md) | Admin Settings Memory 탭 (6개 섹션), API 엔드포인트 |
| [04_knowledge_plane.md](./04_knowledge_plane.md) | entity extraction, entity types, glossary 연동, search boost |

---

## 퀵 스타트

### 1. 메모리 조회

```python
from open_webui.models.memories import Memories

# 사용자 메모리 조회 (soft-deleted 자동 제외)
memories = Memories.get_memories_by_user_id(user_id)

# Profile 조회
profile = Memories.get_profile_by_user_id(user_id)

# 조직 메모리 조회
org_memories = Memories.get_org_memories(org_id)
```

### 2. 메모리 생성

```python
# 수동 생성 (retention_class="standard" 자동)
memory = Memories.insert_new_memory(user_id, "사용자는 FastAPI를 사용한다")

# 조직 메모리 생성 (retention_class="permanent" 자동)
org_mem = Memories.insert_org_memory(org_id, "사내 코딩 컨벤션: ruff formatter 사용", admin_user_id)
```

### 3. Audit Log 기록

```python
from open_webui.utils.audit_logger import AuditLogger

# 공통 audit_log 테이블에 resource_type="memory" 로 기록
AuditLogger.log_create(
    "memory",                    # resource_type
    memory.id,                   # resource_id
    after_data={"content": "...", "source": "manual"},
)
```

### 4. Entity 조회

```python
from open_webui.models.memory_entity import MemoryEntities, EntityTypes

# 사용자의 entity 목록
entities = MemoryEntities.get_entities_by_user_id(user_id)

# 쿼리에 매칭되는 entity 찾기
matched = MemoryEntities.find_matching_entities(user_id, "FastAPI 사용법")

# Entity type 관리
types = EntityTypes.get_all_types()
EntityTypes.add_type("tool", "Development tools")
```

### 5. Admin API 접근

```bash
# Extraction config
curl http://localhost:8080/api/v1/memories/config \
  -H 'Authorization: Bearer {ADMIN_TOKEN}'

# Retention policies
curl http://localhost:8080/api/v1/admin/memory/retention-policies \
  -H 'Authorization: Bearer {ADMIN_TOKEN}'

# Audit logs (with filter)
curl 'http://localhost:8080/api/v1/admin/memory/audit-logs?event_type=DELETE&limit=50' \
  -H 'Authorization: Bearer {ADMIN_TOKEN}'

# Org memory
curl -X POST http://localhost:8080/api/v1/admin/memory/org \
  -H 'Authorization: Bearer {ADMIN_TOKEN}' \
  -H 'Content-Type: application/json' \
  -d '{"content": "회사 공용 메모리"}'
```

---

## 핵심 상수

| Constant | Value | File | Description |
|----------|-------|------|-------------|
| `MAX_HISTORY_MESSAGES` | 20 | unified_agent.py | 단기 히스토리 메시지 수 |
| `MEMORY_SELECTIVE_THRESHOLD` | 20 | unified_agent.py | full dump → selective 전환 |
| `MEMORY_SEARCH_TOP_K` | 10 | unified_agent.py | vector search 반환 수 |
| `_DEBOUNCE_SECONDS` | 300 | memory_extractor.py | 자동 추출 debounce (5분) |
| `max_auto` | 100 | memory_extractor.py | 자동 메모리 상한/user |
| `PROFILE_TRIGGER_FACTS` | 5 | memory_consolidator.py | consolidation 최소 facts |
| `PROFILE_TRIGGER_HOURS` | 24 | memory_consolidator.py | consolidation 재실행 간격 |
| `BATCH_SIZE` | 100 | memory_retention_worker.py | retention worker 배치 크기 |
| `HARD_DELETE_GRACE_DAYS` | 30 | memory_retention_worker.py | hard delete 유예 기간 |
| `DEFAULT_ENTITY_TYPES` | 5종 | memory_entity.py | 기본 entity type |
| `_GLOSSARY_CACHE_TTL` | 60 | memory_extractor.py | glossary terms 캐시 (초) |
| `MEMORY_EXTRACTION_CONFIDENCE` | 0.8 | app.state.config | confidence threshold (Admin에서 변경 가능) |
| `MEMORY_EXTRACTION_MODEL` | `""` (empty string) | app.state.config | extraction 모델. **None/empty string 의미**: PersistentConfig가 `os.environ.get(..., "")`로 초기화되므로 미설정 시 빈 문자열. 빈 문자열 → Task Model fallback → Chat Model fallback 순. Admin UI에서 명시적으로 모델 ID 지정하면 덮어씀 |

---

## DB 스키마

### memory 테이블

```sql
id VARCHAR PRIMARY KEY
user_id VARCHAR
content TEXT
source VARCHAR DEFAULT 'manual'       -- 'manual' | 'auto' | 'profile'
scope VARCHAR DEFAULT 'user'           -- 'user' | 'org'
org_id VARCHAR NULL
retention_class VARCHAR DEFAULT 'standard'  -- 'temporary' | 'standard' | 'permanent'
deleted_at BIGINT NULL                 -- soft delete timestamp
created_at BIGINT
updated_at BIGINT
```

### memory_retention_policy 테이블

```sql
id VARCHAR PRIMARY KEY
retention_class VARCHAR NOT NULL       -- UNIQUE(retention_class, org_id)
ttl_days BIGINT NULL                   -- null = 무기한
on_expire VARCHAR DEFAULT 'soft_delete'  -- 현재 soft_delete만 지원
org_id VARCHAR NULL
created_at BIGINT
updated_at BIGINT
```

### memory_entity 테이블

```sql
id VARCHAR PRIMARY KEY
name VARCHAR NOT NULL                  -- "FastAPI", "Go" (소문자 정규화)
entity_type VARCHAR NOT NULL           -- "tech", "project", "person" 등
memory_id VARCHAR NOT NULL             -- 추출 원본 메모리 (같은 entity 재추출 시 갱신)
user_id VARCHAR NOT NULL
org_id VARCHAR NULL
created_at BIGINT NOT NULL
-- UNIQUE(name, entity_type, user_id)
-- Index: user_id, entity_type
```

### memory_entity_type 테이블

```sql
id VARCHAR PRIMARY KEY
name VARCHAR NOT NULL                  -- "tech", "project" 등 (소문자)
description VARCHAR NULL
org_id VARCHAR NULL
created_at BIGINT NOT NULL
-- UNIQUE(name, org_id)
```

**Note**: `memory_audit_log` 테이블은 폐기됨 (migration `p7b8c9d0e1f2`). 메모리 audit은 시스템 공통 `audit_log` 테이블에 `resource_type="memory"`로 기록.

---

## 관련 파일

### Backend

| 파일 | 역할 |
|------|------|
| `backend/open_webui/models/memories.py` | Memory 모델 + CRUD + soft delete + org memory |
| `backend/open_webui/models/memory_retention_policy.py` | Retention policy 모델 + SOURCE_RETENTION_MAP |
| `backend/open_webui/models/memory_entity.py` | Entity + EntityType 모델 + upsert/query |
| `backend/open_webui/routers/memories.py` | 사용자 메모리 API (CRUD + soft delete + extraction config) |
| `backend/open_webui/routers/admin_memory.py` | Admin API (retention, audit, org, users, entities) |
| `backend/open_webui/utils/audit_logger.py` | AuditLogger — 공통 audit log 기록 |
| `backend/extension_modules/agent/memory_extractor.py` | 자동 fact + entity extraction + glossary 연동 |
| `backend/extension_modules/agent/memory_consolidator.py` | Profile consolidation |
| `backend/extension_modules/agent/memory_retention_worker.py` | TTL 만료 + hard delete worker |
| `backend/extension_modules/agent/memory_tools.py` | get_recent_history tool (단기 메모리) |
| `backend/extension_modules/agent/unified_agent.py` | 메모리 로딩 + 주입 + entity boost |

### Frontend

| 파일 | 역할 |
|------|------|
| `src/lib/components/admin/Settings/Memory.svelte` | Admin Settings Memory 탭 (6개 섹션) |
| `src/lib/components/chat/Settings/Personalization.svelte` | 사용자 메모리 토글 |
| `src/lib/components/chat/Settings/Personalization/ManageModal.svelte` | 메모리 관리 모달 (Auto 뱃지, Profile Summary) |
| `src/lib/apis/memories/index.ts` | 사용자 메모리 API 클라이언트 |
| `src/lib/apis/admin/memory.ts` | Admin 메모리 API 클라이언트 (14개 함수) |

### Migrations

| 파일 | 내용 |
|------|------|
| `migrations/versions/9540f6a26bfd_add_source_column_to_memory.py` | source 컬럼 (Phase 2) |
| `migrations/versions/n5f6a7b8c9d0_memory_governance.py` | governance 컬럼 + retention 테이블 (Phase 4) |
| `migrations/versions/o6a7b8c9d0e1_memory_entities.py` | entity 테이블 (Phase 5) |
| `migrations/versions/p7b8c9d0e1f2_drop_memory_audit_log.py` | memory_audit_log 테이블 drop (공통 audit_log로 통합) |

### Tests

| 파일 | 내용 |
|------|------|
| `backend/open_webui/test/test_memory_governance.py` | 단위 테스트 (Phase 4 + 5) |

---

## 변경 이력

| 날짜 | 변경 | 관련 |
|------|------|------|
| 2026-04-08 | Last Updated + unified_agent.py injection point 명시 + MEMORY_EXTRACTION_MODEL None/empty 세맨틱 + glossary cache fallback | docs/eng-docs-refresh |
| 2026-03-22 | Admin UI 2단 구조 리레이아웃 반영 (accordion → Configuration + Management 탭) | feat/memory-system |
| 2026-03-22 | 문서 업데이트: audit_log 통합, extraction config, glossary 연동, org memory 토글 독립 반영 | feat/memory-system |
| 2026-03-21 | 최초 문서 생성 | feat/memory-system |
