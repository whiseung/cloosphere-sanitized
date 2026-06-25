# 워크스페이스 공유 태그 & 필터

에이전트 목록에 적용된 공유 태그 + 필터 탭 패턴. 워크스페이스 하위 전체 리소스에 동일하게 적용한다.

## 1. 필터 탭 (Filter Chips)

### 탭 구성

```
[전체] [공유됨] [내 {리소스}] [태그1] [태그2] ...
```

| 탭 | 필터 값 | 표시 조건 | 필터 로직 |
|---|---|---|---|
| 전체 | `all` | 항상 | 모든 리소스 (전체공개 포함) |
| 공유됨 | `shared` | 그룹/조직 공유받은 리소스가 1개 이상일 때 | `user_id !== 내 것` AND `access_control !== null` |
| 내 {리소스} | `mine` | 항상 | `user_id === 내 것` |
| 태그 | `tag:{name}` | 태그가 있을 때 | 해당 태그 할당된 리소스 |

> **핵심**: "공유됨" 탭에는 그룹/조직으로 공유받은 것만 표시. 전체공개(access_control=null)는 "전체" 탭에서만 보임.

### isGroupShared 판별 함수

```svelte
const isGroupShared = (item: any): boolean => {
    if (item.user_id === $user?.id) return false;
    const ac = item.access_control;
    if (ac === null || ac === undefined) return false;
    return true;
};

$: hasSharedItems = items.some((item) => isGroupShared(item));
```

### 필터 로직

```svelte
$: if (items) {
    let result = items;

    if ($activeWorkspaceFilter === 'mine') {
        result = result.filter((item) => item.user_id === $user?.id);
    } else if ($activeWorkspaceFilter === 'shared') {
        result = result.filter((item) => isGroupShared(item));
    } else if ($activeWorkspaceFilter.startsWith('tag:')) {
        const tagName = $activeWorkspaceFilter.slice(4);
        result = result.filter((item) => (tagAssignments[item.id] ?? []).includes(tagName));
    }

    filteredItems = result;
}
```

### 필터 칩 템플릿

```svelte
<div class="flex items-center gap-1.5 mb-4 flex-wrap">
    <!-- 전체 -->
    <button
        class="px-3 py-1 text-xs font-medium rounded-full transition-colors
            {$activeWorkspaceFilter === 'all'
            ? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
        on:click={() => ($activeWorkspaceFilter = 'all')}
    >
        {$i18n.t('All')}
    </button>

    <!-- 공유됨 (공유받은 리소스가 있을 때만) -->
    {#if hasSharedItems}
        <button
            class="px-3 py-1 text-xs font-medium rounded-full transition-colors
                {$activeWorkspaceFilter === 'shared'
                ? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
            on:click={() => ($activeWorkspaceFilter = 'shared')}
        >
            {$i18n.t('Shared')}
        </button>
    {/if}

    <!-- 내 리소스 -->
    <button
        class="px-3 py-1 text-xs font-medium rounded-full transition-colors
            {$activeWorkspaceFilter === 'mine'
            ? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
        on:click={() => ($activeWorkspaceFilter = 'mine')}
    >
        {$i18n.t('My {Resource}')}
    </button>

    <!-- 태그 -->
    {#each allTags as tag}
        ...
    {/each}
</div>
```

---

## 2. 카드 공유 태그 (Badge)

### 태그 종류

| 태그 | 조건 | Badge type | 색상 |
|------|------|------------|------|
| `공개` | access_control이 null | warning | 노란색 |
| `공유됨` | 내가 만든 리소스에 그룹 공유 설정됨 | info | 파란색 |
| `내 {리소스}` | 전체 탭에서 내가 만들고 공유 안 한 리소스 | muted | 회색 |
| `그룹(R)` | 공유받은 리소스 - 읽기 권한 | info | 파란색 |
| `그룹(W)` | 공유받은 리소스 - 쓰기 권한 | info | 파란색 |

### 사용자별 표시 규칙

| 사용자 | 소유 | 상태 | 내 탭 | 전체/공유됨 탭 |
|--------|------|------|-------|--------------|
| 관리자 | - | - | 태그 없음 | 태그 없음 |
| 사용자 | 내 것 | 전체공개 | `[공개]` | `[공개]` |
| 사용자 | 내 것 | 그룹공유 | `[공유됨]` | `[공유됨]` |
| 사용자 | 내 것 | 공유 안 함 | 태그 없음 | `[내 {리소스}]` |
| 사용자 | 남의 것 | 그룹(W) | - | `[그룹(W)]` |
| 사용자 | 남의 것 | 그룹(R) | - | `[그룹(R)]` |

### getShareTag 함수

```svelte
const getShareTag = (item: any): { label: string; type: string } | null => {
    if ($user?.role === 'admin') return null;
    const isOwner = item.user_id === $user?.id;
    const ac = item.access_control;

    if (isOwner) {
        // 전체공개
        if (ac === null || ac === undefined) return { label: $i18n.t('Public'), type: 'warning' };
        // 그룹 공유 여부
        const hasGroupShare = (ac?.read?.group_ids?.length > 0 || ac?.write?.group_ids?.length > 0);
        if ($activeWorkspaceFilter === 'mine') {
            return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : null;
        } else {
            return hasGroupShare
                ? { label: $i18n.t('Shared'), type: 'info' }
                : { label: $i18n.t('My {Resource}'), type: 'muted' };
        }
    }

    // 공유받은 리소스: 그룹(R/W) 표시
    if (!ac) return { label: $i18n.t('Public'), type: 'warning' };
    const writeGroups = ac?.write?.group_ids ?? [];
    const readGroups = ac?.read?.group_ids ?? [];
    if (writeGroups.some((gid: string) => group_ids.includes(gid))) {
        return { label: `${$i18n.t('Group')}(W)`, type: 'info' };
    }
    if (readGroups.some((gid: string) => group_ids.includes(gid))) {
        return { label: `${$i18n.t('Group')}(R)`, type: 'info' };
    }
    return null;
};
```

### 템플릿 (WorkspaceCard badge slot)

```svelte
<svelte:fragment slot="badge">
    <!-- 기존 뱃지 유지 -->
    <Badge type="muted" content={$i18n.t('Chat')} />
    <!-- 공유 태그 -->
    {#if getShareTag(item)}
        <Badge type={getShareTag(item).type} content={getShareTag(item).label} />
    {/if}
</svelte:fragment>
```

---

## 3. i18n 키

| 키 | en-US | ko-KR |
|---|---|---|
| `Public` | Public | 공개 |
| `Shared` | Shared | 공유됨 |
| `Group` | Group | 그룹 |
| `My Agents` | My Agents | 내 에이전트 |

> `My {Resource}`는 리소스별로 다른 키를 사용: `My Agents`, `My Knowledge`, `My Database` 등

---

## 4. 필요 데이터 (이미 권한 제어에서 추가됨)

```svelte
import { getGroups } from '$lib/apis/groups';

let group_ids: string[] = [];

onMount(async () => {
    const groups = await getGroups(localStorage.token);
    group_ids = groups.map((group: any) => group.id);
});
```

---

## 5. 적용 대상 파일

| 리소스 | 목록 파일 | My 키 |
|--------|----------|-------|
| 에이전트 | `src/lib/components/workspace/Agents.svelte` | `My Agents` |
| 지식기반 | `src/lib/components/workspace/Knowledge.svelte` | `My Knowledge` |
| 데이터베이스 | `src/routes/(app)/workspace/database/+page.svelte` | `My Database` |
| 지식사전 | `src/routes/(app)/workspace/glossary/+page.svelte` | `My Glossary` |
| 가드레일 | `src/lib/components/workspace/Guardrails.svelte` | `My Guardrail` |
| 프롬프트 | `src/lib/components/workspace/Prompts.svelte` | `My Prompt` |
| 도구 | `src/routes/(app)/workspace/tools/+page.svelte` | `My Tool` |

## 6. 적용 체크리스트

각 파일에서:
1. `group_ids` 변수 확인 (이미 권한 제어에서 추가됨)
2. `isGroupShared` 함수 추가
3. `hasSharedItems` reactive 변수 추가
4. 필터 로직에 `shared` 분기 추가
5. `getShareTag` 함수 추가
6. 필터 칩에 "공유됨" 버튼 추가 (`hasSharedItems` 조건)
7. WorkspaceCard badge slot에 `getShareTag` 추가
8. i18n 키 추가 (`My {Resource}`)

## 참조 구현

- `src/lib/components/workspace/Agents.svelte` (적용 완료)
