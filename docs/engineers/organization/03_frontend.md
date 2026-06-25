# 프론트엔드 구현

## API 클라이언트

**파일**: `src/lib/apis/organizations/index.ts`

### 타입 정의

```typescript
export interface Organization {
  id: string;
  tenant_id: string;
  name: string;
  display_name: string | null;
  domain: string | null;
  meta: Record<string, unknown> | null;
  created_at: number;
  updated_at: number;
}

export interface OrganizationalUnit {
  id: string;
  organization_id: string;
  parent_id: string | null;
  name: string;
  display_name: string | null;
  description: string | null;
  level: number;
  type: string | null;
  external_id: string | null;
  member_ids: string[];
  meta: Record<string, unknown> | null;
  created_at: number;
  updated_at: number;
  children?: OrganizationalUnit[];  // 트리 구조용
}

export interface ResourcePermission {
  id: string;
  name: string;
  description?: string;
  read: boolean;
  write: boolean;
  inherited: boolean;  // 상위에서 상속된 권한인지
}

export interface UnitPermissions {
  unit_id: string;
  unit_name: string;
  permissions: {
    knowledge: ResourcePermission[];
    tools: ResourcePermission[];
    prompts: ResourcePermission[];
    models: ResourcePermission[];
    databases: ResourcePermission[];
    glossaries: ResourcePermission[];
  };
  ancestor_ids: string[];
}
```

### API 함수

```typescript
// 조직 목록 조회
export const getOrganizations = async (token: string): Promise<Organization[]>

// 조직 삭제
export const deleteOrganization = async (token: string, id: string): Promise<boolean>

// 조직 단위 트리 조회
export const getOrganizationalUnitsTree = async (
  token: string,
  organizationId: string
): Promise<OrganizationalUnit[]>

// 조직 단위 권한 조회
export const getOrganizationalUnitPermissions = async (
  token: string,
  unitId: string
): Promise<UnitPermissions>

// 동기화 Provider 목록
export const getSyncProviders = async (token: string): Promise<{ providers: SyncProvider[] }>

// JSON 동기화
export const syncFromJson = async (token: string, data: JsonSyncData): Promise<SyncResult>

// MS Graph 동기화
export const syncFromMSGraph = async (
  token: string,
  options: MSGraphSyncOptions
): Promise<SyncResult>
```

## 주요 컴포넌트

### Organizations.svelte

**파일**: `src/lib/components/admin/Users/Organizations.svelte`

관리자 페이지의 조직 관리 탭 컴포넌트입니다.

#### 기능
- 조직 목록 표시 (검색 지원)
- 조직 선택 시 하위 조직 단위 트리 표시
- 조직 단위별 멤버 조회 모달
- 조직 단위별 권한 조회 모달
- 조직 삭제 (확인 다이얼로그 포함)
- 동기화 모달 (JSON / MS Graph)

#### 상태 관리

```typescript
let organizations: Organization[] = [];          // 조직 목록
let organizationalUnits: OrganizationalUnit[] = [];  // 선택된 조직의 단위
let selectedOrganization: Organization | null = null;  // 현재 선택된 조직

// 모달 상태
let showSyncModal = false;
let showUsersModal = false;
let showPermissionsModal = false;
let showDeleteConfirmDialog = false;

// 동기화 옵션
let selectedSyncProvider = 'json';
let msgraphOptions = {
  use_admin_units: true,
  use_groups: false,
  use_departments: false,
  group_filter: ''
};
```

#### 주요 핸들러

```typescript
// 조직 선택
const selectOrganization = async (org: Organization) => {
  selectedOrganization = org;
  await loadOrganizationalUnits(org.id);
};

// 동기화 실행
const handleSync = async () => {
  if (selectedSyncProvider === 'json') {
    result = await syncFromJson(localStorage.token, JSON.parse(jsonInput));
  } else if (selectedSyncProvider === 'msgraph') {
    result = await syncFromMSGraph(localStorage.token, msgraphOptions);
  }
  // 성공 시 조직 목록 새로고침
  await loadOrganizations();
};

// 조직 삭제
const handleDeleteOrganization = async () => {
  await deleteOrganization(localStorage.token, selectedOrganization.id);
  selectedOrganization = null;
  await loadOrganizations();
};
```

### AccessControl.svelte

**파일**: `src/lib/components/workspace/common/AccessControl.svelte`

리소스별 접근 제어 설정 컴포넌트입니다.

#### Props

```typescript
export let accessControl = {};                // 현재 접근 제어 설정
export let accessRoles = ['read', 'write'];   // 지원하는 권한 유형
export let allowPublic = true;                // Public 옵션 허용 여부
export let onChange: (val: object) => void;   // 변경 콜백
```

#### 기능
- 그룹 선택 (기존)
- 조직 단위 선택 (신규)
- Read/Write 권한 분리
- Public/Private 토글

#### 조직 단위 선택 UI

```svelte
<!-- 조직 단위 선택 섹션 -->
{#if organizationalUnits.length > 0}
  <div class="mt-3">
    <div class="text-xs font-medium mb-1">
      {$i18n.t('Select an organizational unit')}
    </div>
    <Dropdown>
      <!-- 조직 단위 목록 (계층 구조로 표시) -->
      {#each organizationalUnits as unit}
        <button on:click={() => addOrgUnit(unit, role)}>
          <span style="margin-left: {unit.level * 12}px">
            {unit.display_name ?? unit.name}
          </span>
        </button>
      {/each}
    </Dropdown>
  </div>
{/if}
```

#### accessControl 데이터 구조

```typescript
// 컴포넌트가 관리하는 데이터 구조
accessControl = {
  read: {
    group_ids: ['group-1', 'group-2'],
    org_unit_ids: ['unit-1', 'unit-2']
  },
  write: {
    group_ids: ['group-1'],
    org_unit_ids: ['unit-1']
  }
}
```

### ConfirmDialog.svelte

**파일**: `src/lib/components/common/ConfirmDialog.svelte`

삭제 등 위험한 작업 전 확인 다이얼로그입니다.

#### Props

```typescript
export let show = false;                           // 표시 여부
export let title = '';                             // 제목
export let message = '';                           // 메시지
export let cancelLabel = $i18n.t('Cancel');        // 취소 버튼 텍스트
export let confirmLabel = $i18n.t('Confirm');      // 확인 버튼 텍스트
export let onConfirm = () => {};                   // 확인 콜백
```

#### 사용 예시

```svelte
<ConfirmDialog
  bind:show={showDeleteConfirmDialog}
  title={$i18n.t('Delete Organization')}
  on:confirm={handleDeleteOrganization}
>
  <div class="text-sm text-gray-500">
    <p>{$i18n.t('Are you sure you want to delete...?')}</p>

    <!-- 경고 박스 -->
    <div class="p-3 bg-red-50 rounded-lg border border-red-200">
      <ul class="text-xs text-red-600">
        <li>• 모든 조직 단위가 삭제됩니다</li>
        <li>• 이 작업은 되돌릴 수 없습니다</li>
      </ul>
    </div>
  </div>
</ConfirmDialog>
```

## 스타일링 가이드

### 조직 단위 트리 표시

계층 구조를 들여쓰기로 표현:

```svelte
<div
  class="flex items-center justify-between rounded-lg py-2 px-2 bg-gray-50 dark:bg-gray-850"
  style="margin-left: {(unit.level ?? 0) * 16}px"
>
  <!-- 조직 단위 내용 -->
</div>
```

### 권한 뱃지

```svelte
<!-- 읽기 권한 -->
<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
  {$i18n.t('Read')}
</span>

<!-- 쓰기 권한 -->
<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
  {$i18n.t('Write')}
</span>

<!-- 상속된 권한 -->
<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
  {$i18n.t('Inherited')}
</span>
```

### 삭제 버튼 스타일

```svelte
<button
  class="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 dark:bg-red-500 dark:hover:bg-red-600 rounded-lg transition disabled:opacity-50"
  disabled={deleting}
  on:click={() => showDeleteConfirmDialog = true}
>
  <TrashIcon class="size-4" />
  {$i18n.t('Delete')}
</button>
```

## i18n 번역 키

조직 관리 기능에서 사용하는 번역 키:

```json
{
  "Organizations": "조직",
  "Organization": "조직",
  "Organizational Units": "조직 단위",
  "Manage your organizations": "조직을 관리하세요",
  "Organizations will be synced from your identity provider": "조직은 ID 공급자에서 동기화됩니다",
  "Sync Organizations": "조직 동기화",
  "Sync Now": "지금 동기화",
  "Delete Organization": "조직 삭제",
  "Permanently delete this organization and all its organizational units. This action cannot be undone.": "이 조직과 모든 조직 단위를 영구적으로 삭제합니다. 이 작업은 되돌릴 수 없습니다.",
  "Organization deleted successfully": "조직이 성공적으로 삭제되었습니다",
  "All organizational units under this organization will be deleted": "이 조직의 모든 조직 단위가 삭제됩니다",
  "View Permissions": "권한 보기",
  "Assigned Permissions": "할당된 권한",
  "No permissions assigned": "할당된 권한 없음",
  "Inherited": "상속됨",
  "Select an organizational unit": "조직 단위 선택",
  "No organizational units with access": "접근 권한이 있는 조직 단위 없음"
}
```
