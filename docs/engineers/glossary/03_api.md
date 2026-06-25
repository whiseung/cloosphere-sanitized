> Last Updated: 2026-04-08

# 03. Glossary REST API

**Base path**: `/api/v1/glossary`
**License gate**: `require_feature("glossary")` (라우터 전체)
**Router**: `backend/open_webui/routers/glossary.py`
**Permission**: `workspace.glossary` (생성 시)

## 엔드포인트 (8개)

| Method | Path | 설명 | Permission |
|---|---|---|---|
| GET | `/` | 사용자가 읽기 가능한 Glossary 목록 | `read` 또는 owner/admin |
| GET | `/list` | 편집 가능한 Glossary 목록 (에이전트 편집기용) | `write` 또는 owner/admin |
| POST | `/create` | Glossary 신규 생성 | `workspace.glossary` (write) 또는 admin |
| GET | `/{id}` | 단일 Glossary 조회 (entries 포함) | `read` 또는 owner/admin |
| POST | `/{id}/update` | Glossary 업데이트 (entries 포함) | `write` 또는 owner/admin |
| POST | `/{id}/sync` | 검색 엔진 인덱스 재동기화 (background task) | `write` 또는 owner/admin |
| GET | `/{id}/linked-agents` | 이 Glossary를 사용 중인 Agent(Model) 목록 | verified user |
| DELETE | `/{id}/delete` | 삭제 (+검색 엔진 인덱스 삭제) | `write` 또는 owner/admin |

## Request/Response 스키마

### `GlossaryForm`

```python
class GlossaryForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None            # {"entries": [...], "metadata": {...}}
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
```

### `data.entries[]` 구조

**중요**: 과거 문서의 `data.terms[]` 및 `aliases` 필드명은 **구 용어**이며 현재 코드와 일치하지 않습니다. 실제 구조:

```json
{
  "entries": [
    {
      "id": "entry-uuid-1",
      "term": "RAG",
      "synonyms": ["검색 증강 생성", "Retrieval Augmented Generation"],
      "description": "외부 지식을 검색하여 LLM 응답을 개선하는 기법",
      "example": "RAG는 LLM의 할루시네이션을 줄이는 데 효과적입니다.",
      "category": "AI"
    }
  ],
  "metadata": {
    "last_sync_at": 1712000000
  }
}
```

### 필드 매핑 (구 vs 신)

| 구 필드 (과거 문서) | 신 필드 (실제 코드) | 비고 |
|---|---|---|
| `data.terms[]` | `data.entries[]` | |
| `entry.definition` | `entry.description` | |
| `entry.aliases` | `entry.synonyms` | |
| (없음) | `entry.example` | 새 필드 |
| (없음) | `entry.id` | UUID 필수 (프론트엔드 tracking용) |

### `POST /create` 예시

```bash
curl -X POST http://localhost:8080/api/v1/glossary/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI 용어집",
    "description": "팀에서 사용하는 AI/ML 용어 모음",
    "data": {
      "entries": [
        {
          "id": "0001",
          "term": "RAG",
          "synonyms": ["검색 증강 생성"],
          "description": "...",
          "example": "...",
          "category": "AI"
        }
      ]
    },
    "access_control": {
      "read": {"group_ids": ["engineering"], "user_ids": [], "org_unit_ids": []},
      "write": {"group_ids": [], "user_ids": ["OWNER_ID"], "org_unit_ids": []}
    }
  }'
```

**생성 후 자동 동작**:
- Background task `index_glossary_entries()` 호출 → 모든 entries를 검색 엔진에 upsert
- 실패 시 경고 로그만 남기고 Glossary 생성은 성공으로 처리 (검색은 사용 불가 상태)

### `POST /{id}/update` 동작

- `old_entries`와 `new_entries`를 비교하여 **변경 사항만 검색 엔진에 동기화** (`sync_glossary_changes()`)
- 삭제된 entries → 검색 엔진에서 삭제
- 추가/수정된 entries → 검색 엔진에 upsert

### `POST /{id}/sync` — 강제 재동기화

기존 인덱스를 무시하고 **모든 entries를 재색인**. 다음 상황에서 사용:
- 검색 엔진 타입이 변경된 후 (Azure Search → pgvector)
- 인덱스가 corrupt되거나 partial state일 때
- 수동 복구가 필요할 때

**응답**: `{"success": true, "message": "Sync started"}`. 실제 동기화는 background task로 실행됨.

### `GET /{id}/linked-agents`

이 Glossary를 `meta.glossary_ids`로 연결하고 있는 Agent(Model) 목록을 반환. **Glossary 삭제 전 의존성 확인**에 사용.

```json
[
  {"id": "agent-1", "name": "Customer Support Agent"},
  {"id": "agent-2", "name": "Engineering Helper"}
]
```

### `DELETE /{id}/delete`

- DB에서 Glossary 레코드 삭제
- Background task `delete_glossary_index()` → 해당 glossary의 모든 entries를 검색 엔진에서 삭제
- **Linked agents는 자동으로 갱신되지 않음** — Agent 편집 시 dead reference 정리 필요

## 검색 엔진 연동 동작

### 색인 흐름

```
POST /{id}/update (or /create)
  │
  ▼
Glossaries.insert_new_glossary() / update_glossary_by_id()
  │
  └─▶ BackgroundTasks.add_task(index_glossary_entries, app, glossary_id, entries)
         │
         ▼
      GlossaryIndexService(app)
         │
         ├─▶ entries → List[GlossaryEntryInput] 변환
         ├─▶ embedding 생성 (RAG_EMBEDDING_ENGINE, RAG_EMBEDDING_MODEL 사용)
         └─▶ search_engine.upsert(entry_input + embedding)
```

### 검색 엔진 미설정 시

`index_glossary_entries()`는 `ValueError`를 catch하여 **경고 로그만 남기고 성공 처리**한다. Glossary CRUD 자체는 정상 동작하되 검색/LLM 주입 기능은 동작하지 않는다.

## 공통 에러

| Status | 상황 |
|---|---|
| 400 | `NAME_TAKEN`, `NOT_FOUND`, 입력 검증 실패 |
| 401 | `UNAUTHORIZED`, `ACCESS_PROHIBITED` |
| 403 | License feature gate 차단 (`require_feature("glossary")`) |
| 500 | DB 오류 (검색 엔진 오류는 500이 아닌 background warn으로 처리) |
