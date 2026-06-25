# 01. 아키텍처 및 JWT 흐름

## 전체 구조

```
┌──────────────────────────────────────────────────────────────────┐
│                     클루커스 내부 환경                            │
│                                                                  │
│  개발자 모드 (Admin > Developer > License Management)            │
│  ┌─────────────────┐    ┌──────────────────────────────┐        │
│  │  고객사 관리    │    │  키 발급 (JWT RS256)           │        │
│  │  CloocusCustomer│    │  Private Key → JWT 서명       │        │
│  └─────────────────┘    └──────────────────────────────┘        │
│         │                         │                              │
│         └───────────────────────── ┘                             │
│                      CLOOCUS_ADMIN_DB                            │
│              (cloocus_customers, license_records 등)             │
└──────────────────────────────────────────────────────────────────┘
                              │
                 JWT 키 전달 (이메일, 고객 포털 등)
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                       고객 환경                                  │
│                                                                  │
│  관리자 > Settings > License 탭                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │  라이선스 키 / 피처 키 등록                       │           │
│  │  LICENSE_KEYS, FEATURE_KEYS (DB Config 저장)     │           │
│  └──────────────────────────────────────────────────┘           │
│                              │                                   │
│                              ▼                                   │
│  앱 시작 시 / 키 등록 시                                         │
│  ┌──────────────────────────────────────────────────┐           │
│  │  resolve_license_status()                        │           │
│  │  → Public Key로 JWT 검증 (오프라인)               │           │
│  │  → 티어 결정 + 모듈별 permissions 계산            │           │
│  │  → app.state.LICENSE_STATUS 저장                 │           │
│  └──────────────────────────────────────────────────┘           │
│                              │                                   │
│           ┌──────────────────┼──────────────────┐               │
│           ▼                  ▼                  ▼               │
│     Backend API         Frontend UI         Frontend UI          │
│   require_feature()   isFeatureAllowed()   isMenuVisible()       │
│   (403 반환)           (탭/버튼 숨김)       (정적 숨김)           │
└──────────────────────────────────────────────────────────────────┘
```

---

## 키 종류 및 JWT Payload

### License Key (티어 키)

```json
{
  "iss": "cloosphere",
  "type": "license",
  "tier": "standard",
  "company": "고객사명",
  "max_users": 100,
  "iat": 1706000000,
  "exp": 1737600000
}
```

| 필드 | 설명 |
|------|------|
| `tier` | `basic` / `standard` / `professional` |
| `max_users` | 최대 사용자 수 (0 = 무제한) |
| `exp` | 만료 시각 (Unix timestamp) |

### Feature Key (개별 모듈 키)

```json
{
  "iss": "cloosphere",
  "type": "feature",
  "module": "dbsphere",
  "company": "고객사명",
  "iat": 1706000000,
  "exp": 1737600000
}
```

- `module`: 활성화할 모듈 ID (예: `dbsphere`, `glossary`)
- License Key 없이 Feature Key만으로 특정 모듈만 추가 허용 가능

---

## 권한 계산 로직 (`resolve_license_status`)

```
입력: license_keys[], feature_keys[], enforcement_enabled

1. 모든 permissions = False 로 초기화

2. license_keys 처리:
   - 각 키를 public key로 검증
   - 유효한 키 중 가장 높은 tier 선택 (best_tier)
   - ENTERPRISE 이상 (priority ≥ 4) → has_all_features = True → 모든 permissions = True
     (향후 enum에 추가되는 모듈까지 자동 포함)
   - PROFESSIONAL → TIER_INCLUDED_MODULES[PROFESSIONAL] 의 11개 모듈만 True
   - STANDARD → TIER_INCLUDED_MODULES[STANDARD] 의 6개 모듈만 True
   - BASIC → 아무 모듈도 포함 안 됨

3. feature_keys 처리 (additive):
   - 각 키를 검증 후 해당 module의 permission = True
   - Enum에 없는 module_id도 동적으로 허용 (미래 확장 대비)

4. enforcement_enabled = False → 모든 체크 bypass (기본값)

출력: LicenseStatus
  - has_license: bool
  - tier: str
  - permissions: { "kbsphere": true, "dbsphere": false, ... }
  - has_all_features: bool
  - enforcement_enabled: bool
```

### 티어별 포함 모듈 (13개 중 분배)

```python
TIER_INCLUDED_MODULES = {
    LicenseTier.BASIC: set(),                    # 0개
    LicenseTier.STANDARD: {                      # 6개
        "audit_log", "glossary", "guardrail",
        "image_generation", "kbsphere", "tools"
    },
    LicenseTier.PROFESSIONAL: {                  # 11개 (standard 6 + professional 5)
        "audit_log", "glossary", "guardrail",
        "image_generation", "kbsphere", "tools",
        "agent_flow", "branding", "dbsphere",
        "evaluation", "trace"
    },
    LicenseTier.ENTERPRISE: set(),               # has_all_features=True로 처리 → 13개 전체 + 미래 자동
    LicenseTier.DEVELOPER: set(),                # has_all_features=True로 처리 (내부 개발자)
}

TIER_ALL_FEATURES_THRESHOLD = 4  # ENTERPRISE 이상
```

> **ENTERPRISE / DEVELOPER**: `has_all_features = True`이므로 13개 현재 모듈 전부 + 향후 enum에 추가되는 모듈까지 자동으로 포함됩니다. `CODE_GATEWAY`, `FILE_GUARDRAIL`은 이 경로로만 활성화됩니다 (STANDARD/PROFESSIONAL 매핑에 없음).

> **PROFESSIONAL 명시화**: 현재 코드는 `TIER_INCLUDED_MODULES[PROFESSIONAL]`에 11개 모듈을 **명시적으로 나열**하고 `TIER_ALL_FEATURES_THRESHOLD = 4` (ENTERPRISE 이상) 로 설정합니다. 향후 신규 PROFESSIONAL 모듈을 추가하려면 `TIER_INCLUDED_MODULES[PROFESSIONAL]` set에 **수동으로 추가**해야 합니다. 단순히 enum에 추가만 해서는 PROFESSIONAL 고객에게 활성화되지 않습니다. (정확한 변경 시점은 `git log -p backend/open_webui/utils/license.py` 로 추적 가능)

---

## 앱 상태 초기화 흐름

```python
# main.py lifespan
async def lifespan(app):
    # 1. 저장된 키 목록을 가져와 status 계산
    app.state.LICENSE_STATUS = resolve_license_status(
        license_keys=LICENSE_KEYS.value,       # DB Config에 저장된 JWT 목록
        feature_keys=FEATURE_KEYS.value,
        enforcement_enabled=ENABLE_LICENSE_ENFORCEMENT.value,
    )
    yield
```

```python
# routers/license.py - 키 등록/삭제 후 즉시 재계산
def _refresh_license_status(app):
    app.state.LICENSE_STATUS = resolve_license_status(...)
```

키를 등록하거나 삭제하면 **재시작 없이 즉시** 반영됩니다.

---

## 프론트엔드로 상태 전달

`/api/config` 응답에 포함되어 전달됩니다.

```python
# main.py get_app_config()
"license": {
    "has_license": app.state.LICENSE_STATUS.has_license,
    "tier": app.state.LICENSE_STATUS.tier,
    "permissions": app.state.LICENSE_STATUS.permissions,
    "enforcement_enabled": app.state.LICENSE_STATUS.enforcement_enabled,
}
```

프론트엔드 `$config.license.permissions` 스토어에서 접근합니다.

---

## 클루커스 내부 DB 스키마

`CLOOCUS_ADMIN_DATABASE_URL` 환경변수가 있을 때만 활성화됩니다.

```
cloocus_customers         고객사 정보
cloocus_license_records   발급한 라이선스 키 이력
cloocus_feature_key_records  발급한 피처 키 이력
cloocus_feature_registry  등록된 모듈 목록 (seed 데이터)
```

고객 환경에서는 이 DB가 없으므로 관련 코드가 모두 graceful skip됩니다.
