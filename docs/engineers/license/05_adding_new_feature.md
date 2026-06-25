> Last Updated: 2026-04-08

# 05. 신규 기능 게이팅 추가 가이드

새로운 기능을 개발하고 라이선스 게이팅을 적용하는 전체 과정을 케이스별로 설명합니다.

---

## Case A: 라이선스 게이팅이 필요한 신규 기능

예시: `new_module`이라는 신규 기능을 standard 티어에 추가하는 경우.

### Step 1. `FeatureModule` enum 추가

**파일**: `backend/open_webui/utils/license.py`

```python
class FeatureModule(str, Enum):
    # Standard tier
    AUDIT_LOG        = "audit_log"
    GLOSSARY         = "glossary"
    # ... 기존 항목 ...
    NEW_MODULE       = "new_module"   # ← 추가
```

### Step 2. 티어 배정

**파일**: `backend/open_webui/utils/license.py`

```python
TIER_INCLUDED_MODULES = {
    LicenseTier.STANDARD: {
        FeatureModule.AUDIT_LOG,
        FeatureModule.GLOSSARY,
        # ...
        FeatureModule.NEW_MODULE,     # ← standard면 여기
    },
    LicenseTier.PROFESSIONAL: {
        # standard 6개 모두 + professional 5개
        # ...
        FeatureModule.NEW_MODULE,     # ← professional이면 여기도 추가해야 함 (중요)
    },
    # ENTERPRISE: set() — has_all_features=True로 자동 포함되므로 추가 불필요
}
```

> **PROFESSIONAL 티어 주의**: 2026-01 이후 PROFESSIONAL도 명시적 모듈 리스트를 사용합니다. standard용 모듈은 STANDARD와 PROFESSIONAL **둘 다에 추가**해야 합니다. PROFESSIONAL용 모듈은 PROFESSIONAL에만 추가하면 됩니다.
>
> **ENTERPRISE 전용 모듈**: `CODE_GATEWAY`, `FILE_GUARDRAIL`처럼 Enterprise 고객만 사용할 모듈이라면 `TIER_INCLUDED_MODULES`의 STANDARD/PROFESSIONAL 어디에도 추가하지 **않습니다**. ENTERPRISE는 `has_all_features=True`로 자동 포함되므로, enum에 추가만 하면 자동으로 Enterprise 고객이 사용할 수 있습니다.

### Step 3. 백엔드 라우터 게이팅

**파일**: `backend/open_webui/routers/new_module.py`

```python
from open_webui.utils.license import require_feature

# 라우터 전체에 적용 (권장)
router = APIRouter(dependencies=[Depends(require_feature("new_module"))])
```

### Step 4. 프론트엔드 탭/버튼 가드

**워크스페이스 탭인 경우** (`src/routes/(app)/workspace/+layout.svelte`):

```svelte
{#if ($user?.role === 'admin' || $user?.permissions?.workspace?.new_module)
    && isMenuVisible('new-module')
    && isFeatureAllowed($config, 'new_module')}
    <a href="/workspace/new-module">{$i18n.t('New Module')}</a>
{/if}
```

**Settings 탭인 경우** (`src/lib/components/admin/Settings.svelte`):

```javascript
// allTabs 배열에 추가
{ id: 'new-module', labelKey: 'New Module', module: 'new_module' },
```

**Monitoring/Evaluations 서브탭인 경우**:

```svelte
{#if isMenuVisible('new-module') && isFeatureAllowed($config, 'new_module')}
    <button on:click={() => selectedTab = 'new-module'}>New Module</button>
{/if}
```

### Step 5. 클루커스 내부 DB 시드 추가

**파일**: `backend/open_webui/internal/cloocus_db.py`

```python
_FEATURE_REGISTRY_SEED = [
    # ... 기존 항목 ...
    {
        "module_id": "new_module",
        "display_name": "New Module",
        "tier_minimum": "standard",   # "standard" 또는 "professional"
    },
]
```

> 이 변경은 클루커스 내부 환경에서 앱 재시작 시 자동으로 적용됩니다.

---

## Case B: 배포에서 기능 완전히 끄기

라이선스와 무관하게 특정 배포판에서 기능을 비활성화합니다.

**파일**: `src/lib/config/menuConfig.ts`

```typescript
export const hiddenMenus: string[] = [
    'functions',
    'new-feature',   // ← 추가하면 즉시 모든 고객에게 숨겨짐
];
```

재배포 후 적용됩니다.

---

## Case C: 개발 중인 기능 (dev에서만 보임)

```typescript
export const devOnlyMenus: string[] = [
    'wip-feature',   // npm run dev에서만 표시됨
];
```

---

## Case D: 기존 기능의 티어 변경

예시: `dbsphere`를 standard에서 professional로 변경.

```python
# license.py
TIER_INCLUDED_MODULES = {
    LicenseTier.STANDARD: {
        # FeatureModule.DBSPHERE,   ← 제거
        FeatureModule.AUDIT_LOG,
        # ...
    },
}
# professional은 has_all_features=True이므로 자동 포함
```

> enum에서 제거하지 않도록 주의. 제거하면 Feature Key로도 활성화 불가능해집니다.

---

## Case E: 특정 고객에게만 상위 티어 기능 열어주기

Feature Key를 발급하면 됩니다. 라이선스 티어와 무관하게 특정 모듈만 추가 허용합니다.

```
클루커스 내부 환경:
  Developer > License Management > Feature Key 발급
  module: "dbsphere", company: "특정고객사", exp: ...
  → JWT 생성

고객:
  Admin > Settings > License > 키 등록
  → dbsphere만 추가 활성화됨
```

---

## 자주 하는 실수

### 1. Enum 추가 안 하고 require_feature만 적용

```python
# 잘못된 예: FeatureModule enum에 없는 module_id 사용
router = APIRouter(dependencies=[Depends(require_feature("my_new_feature"))])
```

Enum에 없으면 `resolve_license_status`에서 `permissions` 초기화 시 해당 키가 없습니다.
→ Feature Key로 발급해도 `FeatureModule(module_str)` 매핑은 실패하지만,
  `except ValueError` 분기에서 동적으로 허용되므로 Feature Key는 동작합니다.
  그러나 tier 기반 포함이 불가능하므로 **반드시 enum에 추가**해야 합니다.

### 2. 백엔드 게이팅 없이 프론트엔드만 숨김

API를 직접 호출하면 우회 가능합니다. 항상 `require_feature()`도 함께 적용하세요.

### 3. enforcement 플래그 무시

enforcement가 OFF일 때 `isFeatureAllowed`는 항상 `true`를 반환합니다.
로컬 개발 시 게이팅이 동작하지 않는다면 이 플래그를 확인하세요.

```bash
# 로컬에서 enforcement 켜보기
ENABLE_LICENSE_ENFORCEMENT=true npm run dev
```

---

## 체크리스트

```
라이선스 게이팅 추가 시:

□ license.py   FeatureModule enum에 추가
□ license.py   TIER_INCLUDED_MODULES에 티어 배정
□ router.py    require_feature("module_id") 추가
□ layout.svelte  isFeatureAllowed($config, 'module_id') 추가
□ cloocus_db.py  _FEATURE_REGISTRY_SEED에 시드 데이터 추가

배포 제어만 필요한 경우:
□ menuConfig.ts  hiddenMenus 또는 devOnlyMenus에 추가

검증:
□ enforcement=OFF → 탭 표시 확인
□ enforcement=ON + 키 없음 → 탭 숨김 + API 403 확인
□ enforcement=ON + 해당 티어 키 → 탭 표시 + API 200 확인
```
