# 04. 프론트엔드 구현 상세

## 파일 구조

```
src/
├── lib/
│   ├── utils/
│   │   └── license.ts                          ← isFeatureAllowed 헬퍼
│   ├── config/
│   │   └── menuConfig.ts                       ← 정적 메뉴 제어
│   ├── stores/
│   │   └── index.ts                            ← $config 스토어 (license 포함)
│   └── components/admin/
│       ├── Settings/
│       │   └── License.svelte                  ← 관리자용 키 등록 UI
│       └── Developer/
│           └── LicenseManagement.svelte        ← 클루커스 내부용 발급 UI
└── routes/(app)/
    ├── workspace/
    │   └── +layout.svelte                      ← 워크스페이스 탭 가드
    └── admin/
        ├── +layout.svelte                      ← 관리자 탭 구조
        └── settings/+page.svelte               ← Settings 탭 라우팅
```

---

## `$config.license` 스토어

백엔드 `/api/config` 응답에서 자동으로 채워지며, Svelte 스토어를 통해 전체 앱에서 접근 가능합니다.

```typescript
interface Config {
  license?: {
    has_license: boolean;
    tier: string | null;               // "basic" | "standard" | "professional" | null
    permissions: Record<string, boolean>;  // { "kbsphere": true, "dbsphere": false, ... }
    enforcement_enabled: boolean;
    has_all_features?: boolean;
  };
  // ...
}
```

### 사용 예시

```svelte
<script>
    import { config } from '$lib/stores';

    // enforcement 활성화 여부
    $: enforced = $config?.license?.enforcement_enabled ?? false;

    // 특정 모듈 허용 여부
    $: canUseDbSphere = $config?.license?.permissions?.['dbsphere'] ?? false;
</script>
```

---

## `isFeatureAllowed()` 헬퍼

**파일**: `src/lib/utils/license.ts`

```typescript
export function isFeatureAllowed(config: any, module: string): boolean {
    if (!config?.license?.enforcement_enabled) return true;  // enforcement OFF
    return config?.license?.permissions?.[module] ?? false;
}
```

**동작 규칙**:
- `enforcement_enabled = false` → 항상 `true` (기본값, 개발/테스트 편의)
- `enforcement_enabled = true` + `permissions[module] = true` → `true`
- `enforcement_enabled = true` + `permissions[module] = false` → `false`
- `enforcement_enabled = true` + `permissions[module]` 미존재 → `false`

---

## 적용 위치 및 패턴

### 워크스페이스 탭 (`+layout.svelte`)

```svelte
<script>
    import { config } from '$lib/stores';
    import { isMenuVisible } from '$lib/config/menuConfig';
    import { isFeatureAllowed } from '$lib/utils/license';
</script>

<!-- Layer 1 (정적) + Layer 2 (라이선스) 동시 적용 -->
{#if ($user?.role === 'admin' || $user?.permissions?.workspace?.glossaries)
    && isMenuVisible('glossary')
    && isFeatureAllowed($config, 'glossary')}
    <a href="/workspace/glossary">Glossary</a>
{/if}
```

**워크스페이스 탭별 module_id**:

| 탭 | menuId | module_id |
|----|--------|-----------|
| Agents | `agents` | - (라이선스 무관) |
| Flows | `flows` | `agent_flow` |
| Knowledge | `knowledge` | `kbsphere` |
| Database | `database` | `dbsphere` |
| Glossary | `glossary` | `glossary` |
| Guardrails | `guardrails` | `guardrail` |
| Prompts | `prompts` | - (라이선스 무관) |
| Tools | `tools` | `tools` |

### Settings 탭 (`Settings.svelte`)

탭 배열의 `module` 필드로 선언적으로 관리합니다.

```javascript
const allTabs = [
    { id: 'general',  labelKey: 'General' },              // 라이선스 무관
    { id: 'tools',    labelKey: 'Tools',   module: 'tools' },
    { id: 'branding', labelKey: 'Branding', module: 'branding' },
    { id: 'images',   labelKey: 'Images',  module: 'image_generation' },
    // ...
];

$: tabs = allTabs.filter(
    (tab) => isMenuVisible(tab.id) && (!tab.module || isFeatureAllowed($config, tab.module))
);
```

새 Settings 탭에 라이선스 게이팅을 추가할 때는 `module` 필드만 추가하면 됩니다.

### Monitoring 탭 (`Monitoring.svelte`)

```svelte
{#if isMenuVisible('audit-logs') && isFeatureAllowed($config, 'audit_log')}
    <button on:click={() => selectedTab = 'audit-logs'}>Audit Logs</button>
{/if}
```

### Evaluations 탭 (`Evaluations.svelte`)

```svelte
{#if isMenuVisible('auto') && isFeatureAllowed($config, 'evaluation')}
    <button on:click={() => selectedTab = 'auto'}>Auto Evaluations</button>
{/if}

{#if isMenuVisible('tracing') && isFeatureAllowed($config, 'trace')}
    <button on:click={() => selectedTab = 'tracing'}>Tracing</button>
{/if}
```

---

## `menuConfig.ts` 상세

**파일**: `src/lib/config/menuConfig.ts`

정적으로 숨길 메뉴를 관리합니다. **재배포 없이는 변경 불가**합니다.

```typescript
// 항상 숨김 (라이선스/사용자 무관)
export const hiddenMenus: string[] = [
    'functions',   // 현재 비활성화
];

// npm run dev에서만 표시
export const devOnlyMenus: string[] = [];

export function isMenuVisible(id: string): boolean {
    if (hiddenMenus.includes(id)) return false;
    if (devOnlyMenus.includes(id) && !isDev) return false;
    return true;
}
```

**Layer 2와의 관계**: `isMenuVisible` → `isFeatureAllowed` 순서로 AND 조건.
`isMenuVisible`이 `false`면 라이선스 체크 자체가 의미 없습니다.

---

## 관리자용 라이선스 UI (`Settings/License.svelte`)

**접근 경로**: 관리자 > Settings > License

고객의 관리자가 직접 라이선스 키를 등록/삭제하는 UI입니다.

- 라이선스 키 / 피처 키 등록 (JWT 텍스트 붙여넣기)
- 등록된 키 목록 및 상태 확인 (유효/만료/오류)
- Enforcement 토글 (ON/OFF)
- 현재 티어 및 활성화된 모듈 목록 표시

---

## 클루커스 내부용 발급 UI (`Developer/LicenseManagement.svelte`)

**접근 경로**: 관리자 > Developer > 라이선스 관리

클루커스 직원만 사용하는 UI입니다. 고객 환경에서는 Developer 탭 자체가 노출되지 않습니다.

- 고객사 등록 및 관리
- 라이선스 키 발급 (tier, max_users, 만료일 설정)
- 피처 키 발급 (특정 모듈 개별 활성화)
- 발급 이력 조회
- 기능 레지스트리 (등록된 module_id 목록) 관리
