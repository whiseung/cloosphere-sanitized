> Last Updated: 2026-04-08

# 04. 프론트엔드 통합

## 1. 컴포넌트 구조

```
src/lib/components/workspace/Database/
├── CreateDatabase.svelte      # 175 lines — 신규 생성 폼 (name/description/access_control)
├── DbSphereDetail.svelte      # 1487 lines — 상세 편집 페이지 (연결/스키마/메모리 탭)
└── MemoryEditModal.svelte     # 581 lines — 메모리 생성/수정 모달
```

페이지 경로: `src/routes/(app)/workspace/database/` (list, `create/`, `[id]/`).

### `CreateDatabase.svelte`

최소 정보만 입력받아 빈 껍데기 DbSphere를 생성하고 `/workspace/database/{id}` 로 이동하여 상세 편집을 유도하는 간결한 폼.

- **Props**: 없음
- **State**:
  - `name: string`
  - `description: string`
  - `accessControl: { read: {group_ids, user_ids}, write: {group_ids, user_ids} }` — 기본값은 현재 사용자만 read/write 소유
  - `loading: boolean`
- **의존**: `AccessControl.svelte`, `createNewDbSphere()` API 클라이언트
- **흐름**: `submitHandler` → `createNewDbSphere()` → `toast.success` → `goto('/workspace/database')`

### `DbSphereDetail.svelte` (1487 lines — 가장 큰 컴포넌트)

DB 연결 편집 + 스키마 관리 + 메모리 관리의 복합 페이지. 탭 구조로 구성.

**주요 섹션**:

| 섹션 | 설명 |
|---|---|
| **기본 정보** | name, description, access_control, auto_extract_model, sample_row_count |
| **Connection** | db_type dropdown → 타입별 동적 필드 렌더링 (Oracle의 service_name, Snowflake의 warehouse/account/role, Databricks의 http_path/catalog/access_token, Azure AD의 tenant_id/client_id/client_secret) |
| **Test Connection** | `testDbConnectionById()` 호출 → 성공/실패 토스트 |
| **Tables** | `getDbTables()`로 테이블/뷰 목록 로드 → 체크박스 선택 |
| **Schema Extraction** | `extractSchema()` 시작 + `getExtractionStatus()` 폴링 + 진행률 표시 |
| **Extracted Tables** | `getExtractedTables()` 목록 + 개별/전체 삭제 (`deleteExtractedTable`, `deleteAllExtractedTables`) |
| **Memories** | `getDbSphereMemories()` 목록 (entity_type 필터) + 통계 (`getDbSphereMemoryStats`) + 개별 edit (MemoryEditModal 호출) |

**주요 상태 관리**:
- `formData`: 편집 중인 DbSphere 폼
- `extractionJob`: background job 상태 (status/progress/error)
- `extractionPollInterval`: 폴링 interval ID (unmount 시 `clearInterval` 필요)
- `memories`: 현재 탭의 메모리 목록
- `memoryFilter`: `entity_type`, `table_name`, `query` 필터

**권한 처리**:
- Owner/admin 아니면 `write` 권한 체크 (`has_access`) — UI에서 edit 버튼 숨김
- 마스킹된 password는 사용자가 수정 시 기존값 유지되도록 placeholder 처리

### `MemoryEditModal.svelte`

메모리 항목 하나를 편집하는 모달. entity_type별로 다른 입력 필드를 렌더링.

| Entity Type | 주요 필드 |
|---|---|
| `sql_memory` | question, sql, result_summary |
| `ddl_schema` | table_name, columns, description (LLM 생성 또는 수동) |
| `documentation` | title, content (Markdown) |
| `sql_example` | name, sql, description |

`dispatch('save', { memory })`, `dispatch('delete', { id })` 이벤트로 부모(`DbSphereDetail.svelte`)와 통신.

---

## 2. API 클라이언트

**파일**: `src/lib/apis/dbsphere/index.ts` (893 lines)

### 함수 목록 (22개, 라우터 엔드포인트와 1:1 매핑)

| 함수 | 엔드포인트 |
|---|---|
| `createNewDbSphere(token, name, description, accessControl)` | `POST /create` |
| `getDbSpheres(token)` | `GET /` |
| `getDbSphereList(token)` | `GET /list` |
| `getDbSphereById(token, id)` | `GET /{id}` |
| `updateDbSphereById(token, id, form)` | `POST /{id}/update` |
| `getLinkedAgentsByDbSphereId(token, id)` | `GET /{id}/linked-agents` |
| `deleteDbSphereById(token, id)` | `DELETE /{id}/delete` |
| `testDbConnection(token, form)` | `POST /test-connection` |
| `testDbConnectionById(token, id, form)` | `POST /{id}/test-connection` |
| `getDbTables(token, form)` | `POST /tables` |
| `extractSchema(token, id, form)` | `POST /{id}/extract-schema` |
| `getExtractionStatus(token, id)` | `GET /{id}/extraction-status` |
| `getExtractedTables(token, id)` | `GET /{id}/extracted-tables` |
| `deleteAllExtractedTables(token, id)` | `DELETE /{id}/extracted-tables` |
| `deleteExtractedTable(token, id, tableName)` | `DELETE /{id}/extracted-tables/{table_name}` |
| `getDbSphereMemories(token, id, filters)` | `GET /{id}/memories` |
| `getDbSphereMemoryStats(token, id)` | `GET /{id}/memories/stats` |
| `getDbSphereMemoryById(token, id, memoryId)` | `GET /{id}/memories/{memory_id}` |
| `createDbSphereMemory(token, id, form)` | `POST /{id}/memories/create` |
| `updateDbSphereMemory(token, id, memoryId, form)` | `POST /{id}/memories/{memory_id}/update` |
| `deleteDbSphereMemory(token, id, memoryId)` | `DELETE /{id}/memories/{memory_id}` |
| `updateDbSphereSummary(token, id)` | `POST /{id}/memories/summary/update` |

### 공통 패턴

```typescript
const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/...`, {
  method: 'POST',
  headers: {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    authorization: `Bearer ${token}`
  },
  body: JSON.stringify(form),
});

if (!res.ok) {
  const err = await res.json();
  throw new Error(err.detail || 'Request failed');
}
return await res.json();
```

## 3. 에이전트 편집기 통합

Agent 편집기 (`workspace/Agents/AgentEditor.svelte`)의 **Database 섹션**에서 `getDbSphereList()` (write 권한 기준)를 호출하여 선택 가능한 DbSphere 목록을 로드한다. 선택된 DbSphere는 Agent 모델의 `meta.dbspheres` 배열에 `{id, name}` 형태로 저장된다.

```typescript
// meta 구조
{
  dbspheres: [
    { id: "uuid-1", name: "Sales DB" },
    { id: "uuid-2", name: "CRM DB" }
  ]
}
```

런타임에서 `DBSphereAgent`가 `metadata`를 통해 `dbsphere_id`를 추출하고 해당 DbSphere의 연결 정보를 로드한다. `getLinkedAgentsByDbSphereId()`는 이 역방향 관계를 조회한다 (예: DbSphere 삭제 전 사용 중인 Agent 확인).

## 4. i18n 키 (주요)

프론트엔드는 `$i18n.t('...')` 기반 (`src/lib/i18n/locales/ko-KR.json`, `en-US.json`):

| 키 | 설명 |
|---|---|
| `Database` | 메뉴명 |
| `Create Database` | 생성 버튼 |
| `Test Connection` | 연결 테스트 |
| `Extract Schema` | 스키마 추출 |
| `Extraction in progress` | 추출 중 |
| `Please fill in all fields.` | 필수 필드 오류 |
| `Database created successfully.` | 생성 성공 |
| `Connection successful` | 연결 성공 |

## 5. 다크모드/디자인 토큰

모든 컴포넌트는 `--cloo-*` CSS 변수를 사용한 공통 컴포넌트 (`Button`, `Input`, `Selector`, `Tabs`, `Switch`, `AccessControl`) 로 구성되어 있어 `dark:` 클래스 수동 지정이 최소화되어 있다. 커스텀 영역(예: 차트 컨테이너, 메모리 미리보기)만 `dark:bg-gray-900` 같은 기존 패턴 유지.

## 6. 확장 시 주의사항

- **새 DB 타입 추가**: 백엔드에 `SqlRunnerBase` 구현 추가 → `ConnectionTestForm`에 필요 필드 추가 → 프론트엔드 `DbSphereDetail.svelte`의 동적 필드 렌더링에 분기 추가 → i18n 키 추가
- **새 메모리 entity_type 추가**: `memory/models.py::MemoryType` enum → `memory/search_memory.py` 저장/검색 로직 → `MemoryEditModal.svelte` 폼 분기 → `03_api.md` memory filter 테이블 갱신
- **Dashboard Builder UI**: 별도 컴포넌트로 추가될 예정 (2026-04-08 기준 백엔드만 존재, 프론트엔드 미구현). `docs/engineers/bi_dashboard/` 참고
