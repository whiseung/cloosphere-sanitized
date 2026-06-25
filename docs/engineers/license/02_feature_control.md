# 02. 기능 제어 3단계 레이어

기능 가시성과 접근을 제어하는 레이어가 3단계로 구분됩니다.
각 레이어는 독립적으로 동작하며, 상황에 맞게 선택해서 사용합니다.

---

## 레이어 전체 구조

```
요청/렌더링
│
├── Layer 1: menuConfig.ts          ← 정적 제어 (빌드/배포 단위)
│   목적: 이 기능을 이 배포판에서 아예 노출하지 않을 때
│   제어: hiddenMenus / devOnlyMenus 배열
│
├── Layer 2: isFeatureAllowed()     ← 동적 제어 (라이선스 기반)
│   목적: 고객 라이선스 티어에 따라 기능을 숨길 때
│   제어: app.state.LICENSE_STATUS.permissions
│
└── Layer 3: require_feature()      ← API 강제 (백엔드 게이트)
    목적: 프론트엔드 우회 방지, API 자체를 403으로 차단
    제어: FastAPI Depends
```

---

## Layer 1: `menuConfig.ts` — 정적 제어

**언제 사용**: 기능이 아직 개발 중이거나, 특정 배포판에서 완전히 제외할 때.
라이선스와 **무관**하게, 재배포 전까지 **모든 고객에게** 동일하게 적용됩니다.

**파일**: `src/lib/config/menuConfig.ts`

```typescript
// 항상 숨김 (모든 환경, 모든 고객)
export const hiddenMenus: string[] = [
    'functions',        // 현재 비활성화 중인 기능
    // 'new-feature',  // 주석 해제하면 배포에서 사라짐
];

// dev 빌드에서만 표시 (npm run dev)
export const devOnlyMenus: string[] = [
    // 'wip-feature',  // 개발 중인 기능
];
```

**동작 방식**:
```typescript
export function isMenuVisible(id: string): boolean {
    if (hiddenMenus.includes(id)) return false;           // 항상 숨김
    if (devOnlyMenus.includes(id) && !isDev) return false; // dev 전용
    return true;
}
```

**메뉴 ID 목록**:

| ID | 위치 |
|----|------|
| `agents` | 워크스페이스 > Agents |
| `flows` | 워크스페이스 > Flows |
| `knowledge` | 워크스페이스 > Knowledge |
| `database` | 워크스페이스 > Database |
| `glossary` | 워크스페이스 > Glossary |
| `guardrails` | 워크스페이스 > Guardrails |
| `prompts` | 워크스페이스 > Prompts |
| `tools` | 워크스페이스 > Tools |
| `users` | 관리자 > Users |
| `settings` | 관리자 > Settings |
| `monitoring` | 관리자 > Monitoring |
| `evaluations` | 관리자 > Evaluations |
| `developer` | 관리자 > Developer |
| `general` | Settings > General |
| `connections` | Settings > Connections |
| `models` | Settings > Models |
| `tools` (Settings) | Settings > Tools |
| `branding` | Settings > Branding |
| `images` | Settings > Images |
| `audit-logs` | Monitoring > Audit Logs |
| `guardrail-logs` | Monitoring > Guardrail Logs |
| `usage` | Monitoring > Usage |
| `auto` | Evaluations > Auto Evaluations |
| `tracing` | Evaluations > Tracing |

---

## Layer 2: `isFeatureAllowed()` — 라이선스 동적 제어

**언제 사용**: 고객 라이선스 티어에 따라 기능을 보여주거나 숨길 때.
`enforcement_enabled = false`(기본값)이면 항상 `true`를 반환합니다.

**파일**: `src/lib/utils/license.ts`

```typescript
export function isFeatureAllowed(config: any, module: string): boolean {
    if (!config?.license?.enforcement_enabled) return true;  // enforcement OFF → 전체 허용
    return config?.license?.permissions?.[module] ?? false;
}
```

**사용 패턴**:

```svelte
<script>
    import { config } from '$lib/stores';
    import { isFeatureAllowed } from '$lib/utils/license';
</script>

<!-- 탭 -->
{#if isMenuVisible('glossary') && isFeatureAllowed($config, 'glossary')}
    <a href="/workspace/glossary">Glossary</a>
{/if}

<!-- 버튼 -->
{#if isFeatureAllowed($config, 'image_generation')}
    <ImageGenerationButton />
{/if}
```

**Settings.svelte 탭 배열 패턴** (여러 탭을 한 번에 관리):

```javascript
const allTabs = [
    { id: 'general',  labelKey: 'General' },             // 라이선스 무관
    { id: 'tools',    labelKey: 'Tools',   module: 'tools' },   // tools 모듈 필요
    { id: 'branding', labelKey: 'Branding', module: 'branding' }, // branding 필요
    { id: 'images',   labelKey: 'Images',  module: 'image_generation' },
];

// isMenuVisible + 라이선스 동시 필터링
$: tabs = allTabs.filter(
    (tab) => isMenuVisible(tab.id) && (!tab.module || isFeatureAllowed($config, tab.module))
);
```

---

## Layer 3: `require_feature()` — 백엔드 API 게이트

**언제 사용**: 프론트엔드에서 숨기더라도 API를 직접 호출하는 것을 차단해야 할 때.
거의 모든 라이선스 게이팅 기능은 이 레이어도 함께 적용해야 합니다.

**파일**: `backend/open_webui/utils/license.py`

```python
def require_feature(module: str):
    async def _check_feature(request: Request):
        if not is_feature_enabled(request.app, module):
            raise HTTPException(
                status_code=403,
                detail=f"Module '{module}' is not enabled.",
            )
    return _check_feature
```

**라우터 전체에 적용** (권장):
```python
from open_webui.utils.license import require_feature

router = APIRouter(dependencies=[Depends(require_feature("glossary"))])
```

**특정 엔드포인트에만 적용**:
```python
@router.post("/generate", dependencies=[Depends(require_feature("image_generation"))])
async def generate_image(...):
    ...
```

**`is_feature_enabled` 내부 로직**:
```python
def is_feature_enabled(app, module: str) -> bool:
    license_status = getattr(app.state, "LICENSE_STATUS", None)
    if license_status is None or not license_status.enforcement_enabled:
        return True  # enforcement OFF → 모두 허용
    if license_status.has_all_features:
        return True  # ENTERPRISE/DEVELOPER → 모두 허용
    return license_status.permissions.get(module, False)
```

> **현재 동작**: `has_all_features=True`는 **ENTERPRISE 이상**에서만 적용됩니다 (`TIER_ALL_FEATURES_THRESHOLD = 4`). PROFESSIONAL은 `TIER_INCLUDED_MODULES[PROFESSIONAL]`의 11개 모듈만 명시적으로 허용합니다.

---

## 레이어 선택 기준

| 상황 | Layer 1 | Layer 2 | Layer 3 |
|------|---------|---------|---------|
| 미완성 기능을 숨길 때 | ✅ | | |
| 개발 환경에서만 볼 때 | ✅ | | |
| 라이선스 티어별로 탭/버튼 숨길 때 | | ✅ | |
| API 직접 호출도 막아야 할 때 | | ✅ | ✅ |
| UI 표시는 하되 API만 막을 때 | | | ✅ |

**일반적인 라이선스 게이팅**: Layer 2 + Layer 3 함께 사용
**배포 제어**: Layer 1만 사용
**순수 API 보호**: Layer 3만 사용

---

## enforcement 플래그

`ENABLE_LICENSE_ENFORCEMENT` 환경변수 또는 관리자 UI에서 토글 가능합니다.

```
enforcement = false (기본값)
  → Layer 2, Layer 3 모두 bypass
  → 모든 기능이 허용됨
  → 개발/테스트 환경에서 편리

enforcement = true
  → 라이선스 키 기반으로 엄격하게 검사
  → 운영 배포 시 사용
```

```bash
# 환경변수로 설정
ENABLE_LICENSE_ENFORCEMENT=true

# 관리자 UI: Settings > License > Enforcement 토글
# API: POST /api/v1/license/enforcement { "enabled": true }
```
