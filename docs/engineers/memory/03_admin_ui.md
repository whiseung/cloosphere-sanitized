# Admin UI (관리자 메모리 설정)

Last Updated: 2026-03-22

## 1. 개요

Admin > Settings > Memory 탭에서 메모리 설정 및 거버넌스를 관리한다. 2단 구조: 상단 **Configuration** (항상 노출, 2컬럼 grid) + 하단 **Management** (4개 서브탭).

## 2. 위치

```
Admin Panel → Settings → Memory 탭
```

- 컴포넌트: `src/lib/components/admin/Settings/Memory.svelte`
- 탭 등록: `src/lib/components/admin/Settings.svelte` → `allTabs` 배열
- API 클라이언트: `src/lib/apis/admin/memory.ts` (Admin), `src/lib/apis/memories/index.ts` (extraction config)

## 3. 레이아웃

```
┌─────────────────────────────────────────────┐
│  CONFIGURATION                              │
│  ┌───────────────────┬─────────────────────┐│
│  │ Extraction Model  │ Retention Policies  ││
│  │ [Selector]        │ temp:  [30] days    ││
│  │ Confidence: ═══●  │ std:  [180] days    ││
│  │         [Save]    │ perm:  Indefinite   ││
│  │                   │         [Save]      ││
│  └───────────────────┴─────────────────────┘│
│                                             │
│  MANAGEMENT                                 │
│  [Audit Log] [User Memories] [Org] [Entities]│
│  ┌─────────────────────────────────────────┐│
│  │ (선택된 탭의 콘텐츠)                      ││
│  └─────────────────────────────────────────┘│
└─────────────────────────────────────────────┘
```

**설계 근거**: Extraction Config + Retention Policies는 "변경하는 설정"이므로 항상 노출. Audit Log, User Memories, Org Memory, Entities는 "조회/관리하는 데이터"이므로 탭으로 분리. 이전 accordion 6개 구조 대비:
- 설정은 열자마자 즉시 편집 가능
- 데이터 관리는 탭 전환으로 빠르게 접근 (상태 유지)
- 불필요한 스크롤 제거

### 공통 컴포넌트 사용

| 용도 | 컴포넌트 |
|------|---------|
| 모델/이벤트/사용자 선택 | `Selector` (searchEnabled) |
| 저장/추가/페이지네이션 | `Button` (kind: filled/outlined/text, loading) |
| 이벤트/소스/보존 뱃지 | `Badge` (status: success/warning/danger/info/default) |
| 필드 입력 | `Input` |
| 레이블+컨트롤 조합 | `LabelBase` (slot: right) |
| 삭제 확인 | `ConfirmDialog` |

## 4. Configuration 섹션

### Extraction Model (좌측 컬럼)

| 항목 | 설명 |
|------|------|
| 모델 선택 | `Selector` — 추출에 사용할 모델 선택 |
| Fallback | Extraction Model → Task Model → Chat Model 순 |
| Confidence | range slider (0.0~1.0, step 0.05, 기본 0.8) + tabular-nums 표시 |
| 저장 | `Button` (loading 상태) → POST /memories/config |

```
GET  /api/v1/memories/config          → 현재 설정 조회
POST /api/v1/memories/config          → 설정 변경
```

설정 변경 시 `AuditLogger.log_settings_change("memory/extraction", ...)` 기록.

### Retention Policies (우측 컬럼)

| 항목 | 설명 |
|------|------|
| 표시 | `Badge`(retention class) / TTL (days) / On Expire |
| 편집 | number input (permanent은 disabled, "Indefinite" 표시) |
| 저장 | `Button` (loading 상태) → 각 policy PUT API 호출 |

Badge status 매핑:
- permanent → `info` (파란색)
- standard → `default` (회색)
- temporary → `warning` (노란색)

```
GET  /api/v1/admin/memory/retention-policies
PUT  /api/v1/admin/memory/retention-policies/{id}  body: { ttl_days: 60 }
```

## 5. Management 섹션

4개 서브탭으로 구성. `role="tablist"` + `role="tab"` + `aria-selected` 적용. 탭 데이터는 lazy loading — 첫 진입 시에만 API 호출.

### Tab 1: Audit Log

| 항목 | 설명 |
|------|------|
| 필터 | `Selector`(event type: All/CREATE/UPDATE/DELETE/SETTINGS_CHANGE) + `Input`(user ID) |
| 테이블 | Time (tabular-nums) / Event (`Badge`) / Actor / User Email / Details |
| Details | `formatAuditDetail()` — meta 객체를 "source: auto · temporary" 형태로 요약, title에 raw JSON |
| 페이지네이션 | `Button`(outlined, Prev/Next) + "Page X of Y (N records)" |

```
GET /api/v1/admin/memory/audit-logs?event_type=DELETE&user_id=xxx&page=1&limit=20
```

이벤트 Badge status 매핑:
- CREATE → `success` (녹색)
- UPDATE → `warning` (노란색)
- DELETE → `danger` (빨간색)
- SETTINGS_CHANGE → `default` (회색)

**Note**: 내부적으로 공통 `audit_log` 테이블에서 `resource_type="memory"` 필터로 조회.

### Tab 2: User Memories

| 항목 | 설명 |
|------|------|
| 사용자 선택 | `Selector` (searchEnabled, 이름 + 이메일 표시) |
| 메모리 카드 | Content / Source `Badge` / Retention `Badge` / 생성일 (tabular-nums) |
| 삭제 | `ConfirmDialog` 확인 후 soft delete |

Source Badge status 매핑:
- manual → `info` (파란색)
- auto → `success` (녹색)
- profile → `default` (회색)

```
GET    /api/v1/admin/memory/users/{user_id}/memories
DELETE /api/v1/admin/memory/users/{user_id}/memories/{memory_id}
```

### Tab 3: Organization Memory

| 항목 | 설명 |
|------|------|
| 설명 | "조직 메모리는 모든 구성원에게 공유되며 모든 대화에 주입" |
| 추가 | `<form>` + `Input` + `Button`(type="submit") — Enter 키 지원 |
| 메모리 카드 | Content / Created date (tabular-nums) / Delete 버튼 |
| 삭제 | `ConfirmDialog` 확인 후 삭제 |
| 에러 | admin 조직 미소속 시 `role="alert"` 경고 배너 |

```
GET    /api/v1/admin/memory/org
POST   /api/v1/admin/memory/org           body: { content: "..." }
DELETE /api/v1/admin/memory/org/{id}
```

Org memory는 `scope="org"`, `source="manual"`, `retention_class="permanent"` 으로 생성. Vector DB 미사용 (SQL full dump).

Org ID 해석: `_resolve_org_id()` → `OrganizationalUnit` 테이블에서 admin 사용자의 소속 조직 조회.

### Tab 4: Knowledge Entities

| 항목 | 설명 |
|------|------|
| Entity Type 목록 | `Badge`(info) type name / count (tabular-nums) / examples |
| 추가 | "+ Add Entity Type" 토글 → `Input`(name) + `Input`(desc) + `Button`(Add/Cancel) |
| 삭제 | `ConfirmDialog` 확인 후 삭제 |

```
GET    /api/v1/admin/memory/entity-types
POST   /api/v1/admin/memory/entity-types   body: { name: "tool", description: "..." }
DELETE /api/v1/admin/memory/entity-types/{id}
GET    /api/v1/admin/memory/entities       ?entity_type=tech
```

## 6. API 엔드포인트 전체 목록

### User API (memories 라우터)

| Method | Path | Auth | 설명 |
|--------|------|------|------|
| GET | `/memories/` | verified | 사용자 메모리 목록 |
| POST | `/memories/add` | verified | 메모리 수동 추가 |
| POST | `/memories/{id}/update` | verified | 메모리 수정 |
| DELETE | `/memories/{id}/delete` | verified | 메모리 soft delete |
| DELETE | `/memories/delete/user` | verified | 전체 메모리 soft delete |
| POST | `/memories/query` | verified | 메모리 검색 (vector) |
| POST | `/memories/reset` | verified | 메모리 초기화 |
| GET | `/memories/config` | admin | extraction 설정 조회 |
| POST | `/memories/config` | admin | extraction 설정 변경 |

### Admin API (admin_memory 라우터)

| Method | Path | Auth | 설명 |
|--------|------|------|------|
| GET | `/admin/memory/retention-policies` | admin | 정책 목록 |
| PUT | `/admin/memory/retention-policies/{id}` | admin | TTL 수정 |
| GET | `/admin/memory/audit-logs` | admin | 감사 로그 조회 |
| GET | `/admin/memory/org` | admin | 조직 메모리 목록 |
| POST | `/admin/memory/org` | admin | 조직 메모리 추가 |
| DELETE | `/admin/memory/org/{id}` | admin | 조직 메모리 삭제 |
| GET | `/admin/memory/users/{user_id}/memories` | admin | 사용자 메모리 조회 |
| DELETE | `/admin/memory/users/{user_id}/memories/{id}` | admin | 사용자 메모리 삭제 |
| GET | `/admin/memory/entity-types` | admin | entity type 목록 |
| POST | `/admin/memory/entity-types` | admin | entity type 추가 |
| DELETE | `/admin/memory/entity-types/{id}` | admin | entity type 삭제 |
| GET | `/admin/memory/entities` | admin | entity 통계 조회 |

모든 Admin 엔드포인트: `Depends(get_admin_user)` — admin 권한 필수.

## 7. 프론트엔드 API 클라이언트

```typescript
// src/lib/apis/admin/memory.ts (14개 함수)
export const getRetentionPolicies = async (token: string) => { ... }
export const updateRetentionPolicy = async (token: string, id: string, ttlDays: number | null) => { ... }
export const getMemoryAuditLogs = async (token: string, params: {...}) => { ... }
export const getOrgMemories = async (token: string) => { ... }
export const createOrgMemory = async (token: string, content: string) => { ... }
export const deleteOrgMemory = async (token: string, id: string) => { ... }
export const getUserMemories = async (token: string, userId: string) => { ... }
export const deleteUserMemory = async (token: string, userId: string, memoryId: string) => { ... }
export const getEntityTypes = async (token: string) => { ... }
export const addEntityType = async (token: string, name: string, description?: string) => { ... }
export const deleteEntityType = async (token: string, id: string) => { ... }
export const getEntities = async (token: string) => { ... }
export const getMemoryExtractionConfig = async (token: string) => { ... }
export const updateMemoryExtractionConfig = async (token: string, config: {...}) => { ... }
```

## 8. a11y

| 항목 | 구현 |
|------|------|
| 탭 바 | `role="tablist"`, 각 탭 `role="tab"` + `aria-selected` |
| 삭제 확인 | `ConfirmDialog` — 즉시 삭제 없음 |
| 아이콘 버튼 | `aria-label` (Delete, Add Entity Type) |
| 장식 SVG | `aria-hidden="true"` |
| 포커스 | `focus-visible:ring-2` (delete, range, retention input) |
| 에러 알림 | org 에러 배너 `role="alert"` |
| 타임스탬프 | `Intl.DateTimeFormat` (locale-aware) |
| 숫자 정렬 | `tabular-nums` (timestamps, counts, page numbers) |

## 9. i18n 키

Memory 탭에서 사용하는 번역 키는 `en-US/translation.json`, `ko-KR/translation.json`에 등록.
`$i18n.t('Key')` 패턴으로 사용. 총 60개+ 키 (Configuration, Management, 확인 다이얼로그 포함).
