# 워크스페이스 리소스 권한 제어 규칙

지식기반에 적용된 권한 제어 패턴. 데이터베이스, 도구, 프롬프트 등 동일 구조의 워크스페이스 리소스에 동일하게 적용한다.

## 권한 계층

| 구분 | 설명 |
|------|------|
| **워크스페이스 기본권한** | `$user.permissions.workspace.{type}` = `'read'` / `'write'` |
| **리소스 access_control** | 리소스별 `access_control.read/write.group_ids`, `user_ids` |
| **소유자** | `item.user_id === $user.id` |
| **관리자** | `$user.role === 'admin'` → 모든 제한 무시 |

> **핵심 원칙**: 워크스페이스 기본권한이 그룹 공유보다 우선한다. 기본권한이 `read`이면 그룹 `write` 공유를 받아도 수정 불가.

---

## 목록 페이지 규칙

### 카드 클릭 (상세 진입)

```
관리자         → 항상 가능
소유자         → 기본권한 무관하게 가능 (읽기여도 상세 진입, 단 수정 불가)
공유받은 사용자 → 기본권한 write + access_control write일 때만 가능
```

```svelte
$user?.role === 'admin'
|| item.user_id === $user?.id
|| ($user?.permissions?.workspace?.{type} === 'write' && hasResourceAccess(item, 'write'))
```

### [...] 메뉴 (삭제 등)

```
관리자 또는 (기본권한 write + 소유자)만 표시
공유받은 사용자는 표시 안 함
```

```svelte
$user?.role === 'admin'
|| ($user?.permissions?.workspace?.{type} === 'write' && item.user_id === $user?.id)
```

### hasResourceAccess 헬퍼 (목록 페이지용)

```svelte
const hasResourceAccess = (item: any, level: 'read' | 'write') => {
    const ac = item.access_control;
    if (!ac) return false;
    const perm = ac[level];
    if (!perm) return false;
    if (perm.user_ids?.includes($user?.id)) return true;
    if (perm.group_ids?.some((gid: string) => group_ids.includes(gid))) return true;
    return false;
};
```

---

## 상세 페이지 규칙

### isOwnerOrAdmin (Access 버튼 표시용)

```svelte
$: isOwnerOrAdmin = $user?.role === 'admin' || item.user_id === $user?.id;
```

- Access 버튼: `isOwnerOrAdmin`일 때만 표시
- 공유받은 사용자는 접근 제어 수정 불가

### canWrite (Save 버튼 활성화용)

```
관리자         → 항상 가능
기본권한 write + (소유자 또는 access_control write) → 가능
기본권한 read  → 소유자여도 수정 불가
```

```svelte
$: canWrite = $user?.role === 'admin' || (
    $user?.permissions?.workspace?.{type} === 'write' && (
        item.user_id === $user?.id
        || item.access_control?.write?.user_ids?.includes($user?.id)
        || item.access_control?.write?.group_ids?.some(gid => group_ids.includes(gid))
    )
);
```

### Save & Update 버튼

```svelte
<Button disabled={!canWrite} on:click={() => saveHandler()}>
    {$i18n.t('Save & Update')}
</Button>
```

---

## 필수 구현 사항

1. **`getGroups` import + `group_ids` 로드**: onMount에서 사용자의 그룹 ID 목록 가져오기
2. **`hasResourceAccess` 헬퍼** (목록 페이지): access_control의 user_ids, group_ids 체크
3. **상세 페이지 타입에 `user_id`, `access_control` 필드 추가**

---

## 권한 매트릭스

| 사용자 | 기본권한 | 소유 | 공유(write) | 카드클릭 | ... 메뉴 | Access | 저장 |
|--------|----------|------|-------------|----------|----------|--------|------|
| 관리자 | -        | -    | -           | O        | O        | O      | O    |
| 사용자 | write    | 소유 | -           | O        | O        | O      | O    |
| 사용자 | read     | 소유 | -           | O        | X        | O      | X    |
| 사용자 | write    | X    | O           | O        | X        | X      | O    |
| 사용자 | write    | X    | X           | X        | X        | X      | X    |
| 사용자 | read     | X    | O           | X        | X        | X      | X    |

---

## 참조 구현

- 목록: `src/lib/components/workspace/Knowledge.svelte`
- 상세: `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte`
- AccessControl 그룹 표시: `src/lib/components/workspace/common/AccessControl.svelte`
- 그룹 이름 조회 API: `backend/open_webui/routers/groups.py` → `POST /groups/names`
- 프론트엔드 API: `src/lib/apis/groups/index.ts` → `getGroupsByIds()`
