---
paths:
  - "src/lib/components/admin/**/*.svelte"
  - "src/routes/(app)/admin/**/*"
---

# 관리자 패널 UI 규칙

## 탭 구조 (6개 메인 탭)
| Tab ID | 라벨 | 경로 | 권한 키 |
|--------|------|------|---------|
| `users` | Users | `/admin` | `users` |
| `evaluations` | Evaluations | `/admin/evaluations` | `evaluations` |
| `functions` | Functions | `/admin/functions` | `functions` |
| `settings` | Settings | `/admin/settings` | `settings` |
| `monitoring` | Monitoring | `/admin/monitoring` | `monitoring` |
| `developer` | Developer Mode | `/admin/developer` | *(admin only)* |

## 권한 필터링 3계층
1. **메뉴 가시성**: `isMenuVisible(tab.id)` — `hiddenMenus` 배열, `devOnlyMenus` 배열
2. **역할 기반**: `$user?.role === 'admin'` → 모든 탭 접근
3. **세부 권한**: `$userPermissions?.admin?.[permissionKey]` → 개별 탭 접근

## 라우트 보호 패턴 (+layout.svelte)
```typescript
onMount(async () => {
  if (!hasAnyAdminAccess) { await goto('/'); return; }
  if (!isPathAllowed($page.url.pathname)) {
    await goto(getFirstAvailableTab());
  }
  loaded = true;
});

// 경로 변경 감시
$: if (loaded && $page.url.pathname) {
  if (!isPathAllowed($page.url.pathname)) goto(getFirstAvailableTab());
}
```

## 서브 탭 구성
- **Users**: Overview, Groups, Organizations 3탭
- **Evaluations**: Leaderboard, Feedbacks, Auto, Tracing (isMenuVisible 필터링)
- **Monitoring**: Audit Logs, Usage 2탭
- **Developer**: Locale Management
- **Settings**: 15개 하위 탭 (ui-admin-settings.md 참조)

## 메뉴 설정 (src/lib/config/menuConfig.ts)
```typescript
export function isMenuVisible(id: string): boolean {
  if (hiddenMenus.includes(id)) return false;
  if (devOnlyMenus.includes(id) && !isDev) return false;
  return true;
}
```

## 탭 네비게이션 패턴

새 코드에서는 `Tabs` 공통 컴포넌트 사용 권장:
```svelte
import Tabs from '$lib/components/common/Tabs.svelte';

<Tabs items={[
  { id: 'overview', labelKey: 'Overview', href: '#overview', state: selectedTab === 'overview' ? 'selected' : 'default' },
  { id: 'groups', labelKey: 'Groups', href: '#groups', state: selectedTab === 'groups' ? 'selected' : 'default' },
]} />
```

기존 수동 탭 패턴 (레거시):
```svelte
<button on:click={() => selectedTab = 'overview'}
  class:selected={selectedTab === 'overview'}>
  {$i18n.t('Overview')}
</button>
```

## Groups 컴포넌트 주요 패턴
- `defaultPermissions` 객체: workspace(7), sharing(6), chat(10), features(4) 권한 그룹
- 그룹별 권한 오버라이드 UI

## Organizations 컴포넌트
- MS Graph 동기화 UI (sync 버튼)
- 조직/부서 트리 구조 표시

## 참조 파일
- `src/routes/(app)/admin/+layout.svelte`: 관리자 레이아웃 + 권한 체크
- `src/lib/components/admin/Users.svelte`: 사용자 관리
- `src/lib/components/admin/Evaluations.svelte`: 평가 관리
- `src/lib/components/admin/Monitoring.svelte`: 모니터링
- `src/lib/components/admin/Functions.svelte`: 함수 관리
- `src/lib/components/admin/Developer.svelte`: 개발자 모드
- `src/lib/config/menuConfig.ts`: 메뉴 가시성 설정
