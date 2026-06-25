# 프론트엔드 통합 가이드

SharePoint 브라우저 컴포넌트를 다른 위치에서 사용하거나 확장하기 위한 가이드입니다.

## 1. 기본 사용법

### 컴포넌트 임포트 (v2)

```svelte
<script lang="ts">
    import SharePointBrowser from '$lib/components/common/SharePointBrowser.svelte';

    let showBrowser = false;

    async function handleSelect(e) {
        // 새로운 이벤트 형식: files 배열
        const { files } = e.detail;

        // 파일과 폴더 내용이 모두 File[] 배열로 전달됨
        for (const file of files) {
            await uploadFile(file);
        }
    }
</script>

<button on:click={() => showBrowser = true}>
    Open SharePoint
</button>

<SharePointBrowser
    bind:show={showBrowser}
    on:select={handleSelect}
    on:cancel={() => showBrowser = false}
/>
```

## 2. 이벤트 상세

### select 이벤트 (v2 - 변경됨)

```typescript
// 새로운 단순화된 형식
interface SelectEvent {
    files: File[];    // 다운로드된 모든 파일 (폴더 선택 시 재귀적으로 수집됨)
}
```

> **이전 버전과의 차이점**:
> - 이전: `{ blob, name, isFolder, items }` - 폴더 처리를 호출자가 직접 해야 함
> - 현재: `{ files }` - 폴더 내 모든 파일이 자동으로 재귀 다운로드됨

### DriveItem 타입

```typescript
interface DriveItem {
    id: string;
    name: string;
    folder?: { childCount: number };
    file?: { mimeType: string };
    size?: number;
    lastModifiedDateTime?: string;
    webUrl?: string;
    parentReference?: {
        driveId: string;
        id: string;
        path: string;
    };
}
```

## 3. 기능 활성화 조건

SharePoint 버튼은 **Admin 설정에서 활성화**된 경우에만 표시됩니다.

### Admin 설정 토글 (Documents.svelte)

```svelte
<!-- src/lib/components/admin/Settings/Documents.svelte -->
<div class="mb-3">
    <div class="mb-2.5 text-base font-medium">{$i18n.t('Integration')}</div>
    <hr class="border-gray-100 dark:border-gray-850 my-2" />

    <!-- Google Drive, OneDrive 토글... -->

    <div class="mb-2.5 flex w-full justify-between">
        <div class="self-center text-xs font-medium">{$i18n.t('SharePoint')}</div>
        <div class="flex items-center relative">
            <Switch bind:state={RAGConfig.ENABLE_SHAREPOINT_INTEGRATION} />
        </div>
    </div>
</div>
```

### 설정 저장 및 반영 흐름

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Documents    │────▶│ retrieval.py │────▶│ main.py      │
│ .svelte      │     │ updateRAG    │     │ /api/config  │
│ (토글)       │     │ Config()     │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
       ┌─────────────────────────────────────────┘
       ▼
┌──────────────┐     ┌──────────────┐
│ Settings     │────▶│ config store │
│ .svelte      │     │ (refresh)    │
│ on:save      │     └──────────────┘
│ getBackend   │              │
│ Config()     │              ▼
└──────────────┘     ┌──────────────┐
                     │ InputMenu    │
                     │ .svelte      │
                     │ (버튼 표시)  │
                     └──────────────┘
```

### InputMenu 조건부 렌더링

```svelte
<!-- src/lib/components/chat/MessageInput/InputMenu.svelte -->
{#if $config?.features?.enable_sharepoint_integration}
    <DropdownMenu.Item on:click={uploadSharePointHandler}>
        <SharePointIcon />
        <div>{$i18n.t('SharePoint')}</div>
    </DropdownMenu.Item>
{/if}
```

### Config 타입 정의 (stores/index.ts)

```typescript
interface Config {
    features: {
        enable_sharepoint_integration: boolean;
        enable_google_drive_integration: boolean;
        enable_onedrive_integration: boolean;
        // ... 기타 features
    };
}
```

## 4. 스타일링 가이드

SharePointBrowser는 Tailwind CSS를 사용합니다. 주요 클래스:

### 다크 모드 지원

```svelte
<div class="bg-white dark:bg-gray-850">
    <span class="text-gray-900 dark:text-white">...</span>
</div>
```

### 상태별 스타일

```svelte
<!-- 선택된 항목 -->
<button class="{selectedItems.has(item.id)
    ? 'bg-blue-50 dark:bg-blue-900/20'
    : ''}">

<!-- 비활성화된 버튼 -->
<button class="{disabled
    ? 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
    : 'bg-black dark:bg-white text-white dark:text-black'}">
```

## 5. 다국어 지원

새로운 문자열 추가 시 번역 파일 업데이트 필요:

### en-US/translation.json

```json
{
    "SharePoint": "",
    "Select files or folders": "",
    "Loading...": "",
    "No items selected": "",
    "{{count}} selected": "",
    "Double-click to open": ""
}
```

### ko-KR/translation.json

```json
{
    "SharePoint": "SharePoint",
    "Select files or folders": "파일 또는 폴더 선택",
    "Loading...": "로딩 중...",
    "No items selected": "선택된 항목 없음",
    "{{count}} selected": "{{count}}개 선택됨",
    "Double-click to open": "열려면 더블 클릭하세요"
}
```

### 사용법

```svelte
<script>
    const i18n = getContext('i18n');
</script>

<span>{$i18n.t('Loading...')}</span>
<span>{$i18n.t('{{count}} selected', { count: 5 })}</span>
```

## 6. MessageInput 통합 코드 (v2)

현재 구현된 MessageInput.svelte 통합 방식:

```svelte
<script>
    import SharePointBrowser from '../common/SharePointBrowser.svelte';

    let showSharePointBrowser = false;
</script>

<SharePointBrowser
    bind:show={showSharePointBrowser}
    on:select={async (e) => {
        // 새로운 이벤트 형식: files 배열
        const { files } = e.detail;

        // 모든 파일을 순차적으로 업로드
        for (const file of files) {
            await uploadFileHandler(file);
        }
    }}
    on:cancel={() => {
        showSharePointBrowser = false;
    }}
/>

<!-- InputMenu에 핸들러 전달 -->
<InputMenu
    uploadSharePointHandler={() => {
        showSharePointBrowser = true;
    }}
/>
```

## 7. 확장 가능성

### 폴더 전체 업로드 (구현 완료)

폴더 선택 시 `collectFilesFromFolder()` 함수가 재귀적으로 모든 파일을 다운로드합니다.
이 기능은 SharePointBrowser 컴포넌트에 내장되어 있습니다.

```typescript
// SharePointBrowser.svelte 내부 구현
async function collectFilesFromFolder(
    driveId: string,
    folderId: string,
    folderName: string
): Promise<File[]> {
    const folderItems = await getItems(driveId, folderId);
    const files: File[] = [];

    for (const item of folderItems) {
        if (item.folder) {
            // 하위 폴더 재귀 처리
            const subFiles = await collectFilesFromFolder(
                driveId,
                item.id,
                `${folderName}/${item.name}`
            );
            files.push(...subFiles);
        } else {
            // 파일 다운로드
            const blob = await downloadFile(driveId, item.id);
            files.push(new File(
                [blob],
                item.name,
                { type: blob.type || 'application/octet-stream' }
            ));
        }
    }
    return files;
}
```

> **UI 피드백**: 폴더 다운로드 중 토스트 메시지로 진행 상황을 표시합니다.
> - `"Downloading folder: {폴더명}"`
> - `"{n} files added"` (완료 시)

### 검색 기능 추가

Graph API의 검색 엔드포인트 활용:

```typescript
// 사이트 내 파일 검색
GET /sites/{siteId}/drive/root/search(q='{query}')
```

### 최근 파일 표시

```typescript
// 사용자의 최근 파일
GET /me/drive/recent
```

## 8. Svelte 반응성 주의사항

> ⚠️ **중요**: Set 대신 Array를 사용해야 합니다.

Svelte는 변수 **재할당**을 통해 반응성을 감지합니다. `Set.add()`, `Set.delete()` 등 뮤테이션은 감지되지 않습니다.

### ❌ 잘못된 방식 (반응성 없음)

```typescript
let selectedItems = new Set<string>();

// 뮤테이션 - UI 업데이트 안됨!
selectedItems.add(itemId);
selectedItems.delete(itemId);
```

### ✅ 올바른 방식 (반응성 있음)

```typescript
let selectedItemIds: string[] = [];

function toggleSelection(itemId: string) {
    const idx = selectedItemIds.indexOf(itemId);
    if (idx >= 0) {
        // 새 배열 생성으로 반응성 트리거
        selectedItemIds = selectedItemIds.filter((id) => id !== itemId);
    } else {
        selectedItemIds = [...selectedItemIds, itemId];
    }
}

// 반응형 계산
$: selectedCount = selectedItemIds.length;
```

## 9. 테스트 체크리스트

- [ ] **Admin 설정**
  - [ ] Documents 설정에서 SharePoint 토글 표시 확인
  - [ ] 토글 변경 후 저장 시 설정 유지 확인
  - [ ] 비활성화 시 채팅에서 SharePoint 버튼 숨김 확인

- [ ] **인증 및 사이트**
  - [ ] 개발 환경에서 인증 팝업 동작 확인
  - [ ] 사이트 목록 로드 확인
  - [ ] 문서 라이브러리 선택 동작 확인

- [ ] **파일/폴더 선택**
  - [ ] 파일 단일 선택 → 업로드 확인
  - [ ] 파일 다중 선택 → 모두 업로드 확인
  - [ ] 폴더 선택 → 재귀 다운로드 → 모든 파일 업로드 확인
  - [ ] 선택 개수 표시 정상 동작 확인 (반응성)

- [ ] **UI/UX**
  - [ ] 다크 모드 UI 확인
  - [ ] 한국어/영어 번역 확인
  - [ ] 폴더 다운로드 중 토스트 메시지 확인
  - [ ] 에러 상황 (권한 없음, 네트워크 오류) 처리 확인
