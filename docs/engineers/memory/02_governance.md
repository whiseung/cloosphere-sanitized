# Governance (메모리 거버넌스)

Last Updated: 2026-03-22

## 1. 개요

메모리 데이터의 생명주기를 관리한다. retention policy로 자동 만료, audit log로 변경 추적, soft delete로 안전한 삭제를 제공한다.

## 2. Retention Policy

### 클래스별 TTL

| retention_class | 대상 | TTL | 자동 매핑 |
|----------------|------|-----|----------|
| `temporary` | 자동 추출 메모리 | 30일 | `source="auto"` |
| `standard` | 수동 생성 메모리 | 180일 | `source="manual"` |
| `permanent` | Profile, org memory | 무기한 | `source="profile"`, `scope="org"` |

### 매핑 로직

```python
# backend/open_webui/models/memory_retention_policy.py
SOURCE_RETENTION_MAP = {
    "auto": "temporary",
    "manual": "standard",
    "profile": "permanent",
}
```

메모리 생성 시 `insert_new_memory(source=...)` → `SOURCE_RETENTION_MAP`에서 자동 결정. LLM 판단 불필요.

### TTL 기준: `created_at`

TTL은 `created_at` 기준으로 계산된다. 메모리가 UPDATE되어 `updated_at`이 변경되더라도 TTL 카운트다운은 리셋되지 않는다. 이는 의도적 설계 — 자주 갱신되는 메모리가 영구히 살아남는 것을 방지.

### 정책 테이블

```python
class MemoryRetentionPolicy(Base):
    __tablename__ = "memory_retention_policy"
    id = Column(String, primary_key=True)
    retention_class = Column(String, nullable=False)  # UNIQUE(class, org_id)
    ttl_days = Column(BigInteger, nullable=True)       # null = 무기한
    on_expire = Column(String, server_default="soft_delete")  # 현재 soft_delete만 지원
    org_id = Column(String, nullable=True)             # org별 정책 (미활용)
```

**`on_expire` 필드**: 스키마에 존재하나 현재 retention worker는 `soft_delete`만 수행한다. 대체 동작(purge, archive 등)은 미구현.

### Seed Defaults

lifespan startup 시 `RetentionPolicies.seed_defaults()` 호출. 3개 기본 정책이 `org_id=None`(글로벌)으로 삽입. idempotent — 이미 존재하면 skip.

### Permanent 정책 보호

`retention_class="permanent"` 정책의 TTL은 Admin API에서 변경할 수 없다:

```python
if policy.retention_class == "permanent":
    return  # TTL 변경 거부
```

### Admin API

```
GET  /api/v1/admin/memory/retention-policies      → 전체 정책 목록
PUT  /api/v1/admin/memory/retention-policies/{id}  → TTL 일수 수정 (permanent 불가)
```

## 3. Soft Delete

### 동작

```
사용자 삭제 요청
  → deleted_at = int(time.time()) 설정
  → Vector DB에서 즉시 삭제 (검색 오염 방지)
  → AuditLogger.log_delete("memory", ...)
  → API 조회에서 자동 제외 (WHERE deleted_at IS NULL)
  → 30일 후 retention worker가 hard delete
```

### 왜 Vector DB는 즉시 삭제?

Vector DB는 `deleted_at` 필터를 지원하지 않으므로, soft delete 시점에 vector 엔트리를 즉시 삭제해야 검색 결과에 삭제된 메모리가 포함되지 않는다.

### 영향 범위

모든 메모리 조회 메서드에 `Memory.deleted_at.is_(None)` 필터 적용:
- `get_memories_by_user_id()`
- `get_memory_by_id()`
- `get_memory_count_by_user_id()`
- `get_profile_by_user_id()`
- `get_org_memories()`
- `update_memory_by_id_and_user_id()` — soft-deleted 메모리 수정 방지
- `get_memories_by_user_id_for_admin()` — admin 조회도 active만 반환

## 4. Audit Log

### 아키텍처 변경 (Phase 4 → 현재)

`memory_audit_log` 전용 테이블은 폐기되었다 (migration `p7b8c9d0e1f2`). 메모리 audit은 시스템 공통 `audit_log` 테이블에 `resource_type="memory"`로 기록된다.

| Before (폐기) | After (현재) |
|---|---|
| `memory_audit_log` 전용 테이블 | 공통 `audit_log` 테이블 |
| `MemoryAudit.log()` fire-and-forget | `AuditLogger.log_create/update/delete/settings_change()` |
| memory_id, event_type, actor 컬럼 | action, resource_type, resource_id, before_state, after_state |

### AuditLogger 사용 패턴

```python
from open_webui.utils.audit_logger import AuditLogger

# 메모리 생성
AuditLogger.log_create(
    "memory",                           # resource_type
    memory.id,                          # resource_id
    after_data={"content": "...", "source": "manual", "retention_class": "standard"},
)

# 메모리 수정
AuditLogger.log_update(
    "memory",
    memory.id,
    before_data={"content": "old"},
    after_data={"content": "new"},
)

# 메모리 삭제
AuditLogger.log_delete(
    "memory",
    memory.id,
    before_data={"retention_class": "temporary"},
)

# Extraction config 변경
AuditLogger.log_settings_change(
    "memory/extraction",
    before_data={...},
    after_data={...},
)
```

### Background Task에서의 Audit

`memory_extractor.py`, `memory_consolidator.py`, `memory_retention_worker.py`는 HTTP 요청 컨텍스트 없이 실행된다. AuditLogger는 background task에서 `meta.user_id` fallback으로 사용자를 기록한다.

### 이벤트 유형 (action)

| action | 트리거 | 기록 위치 |
|--------|--------|----------|
| `create` | 수동 추가, 자동 추출, profile 생성, org memory 추가 | routers, extractor, consolidator |
| `update` | 수동 수정, 자동 갱신, profile 업데이트 | routers, extractor, consolidator |
| `delete` | 수동 삭제, admin 삭제, TTL 만료 | routers, admin_memory, retention_worker |
| `settings_change` | extraction model/confidence 변경 | routers/memories.py |

### 조회 API

```
GET /api/v1/admin/memory/audit-logs
    ?event_type=create|update|delete|settings_change
    ?user_id=xxx
    ?include_system=true|false   (system event 토글)
    ?page=1
    ?limit=100  (max 500)
```

내부적으로 `AuditLogs.get_audit_logs(AuditLogQueryParams(resource_type="memory", ...))` 호출.

## 5. Retention Worker

```python
# backend/extension_modules/agent/memory_retention_worker.py

async def run_retention_worker(interval_seconds: int = 3600):
    """매 1시간 실행. lifespan에서 fire-and-forget으로 등록."""
```

### 시작 시점

```python
# main.py lifespan
asyncio.create_task(run_retention_worker(interval_seconds=3600))
```

**첫 sleep 후 실행**: `await asyncio.sleep(interval_seconds)` 후 첫 cycle 시작. 서버 startup 직후 1시간 동안 worker 유휴 — 초기 부하 분산 + seed/migration 완료 보장 목적.

### Step 1: TTL 만료 처리

```sql
SELECT m.id FROM memory m
JOIN memory_retention_policy p ON m.retention_class = p.retention_class
WHERE m.deleted_at IS NULL
  AND p.ttl_days IS NOT NULL
  AND p.org_id IS NULL              -- 글로벌 정책만 적용
  AND m.created_at + (p.ttl_days * 86400) < :now
LIMIT 100
```

→ soft delete + **Vector DB 즉시 삭제** + AuditLogger.log_delete

### Step 2: Hard delete 처리

```sql
SELECT id FROM memory
WHERE deleted_at IS NOT NULL
  AND deleted_at + (30 * 86400) < :now
LIMIT 100
```

→ DB에서 물리 삭제 (vector DB는 soft delete 시점에 이미 삭제됨)

### 안전장치

- 배치 100건씩, 배치 간 `asyncio.sleep(0.1)` — DB 부하 분산
- 한 cycle 내에서 모든 만료 건 처리 (배치 루프)
- 실패 시 log + 다음 cycle에 재시도
- Expiration과 hard delete 모두에서 vector DB 삭제 보장
