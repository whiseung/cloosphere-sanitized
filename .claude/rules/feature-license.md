---
paths:
  - "backend/open_webui/routers/license.py"
  - "backend/open_webui/routers/license_permissions.py"
  - "backend/open_webui/utils/license.py"
  - "backend/open_webui/models/cloocus_admin.py"
  - "src/lib/components/admin/Settings/License.svelte"
  - "src/lib/apis/license/**/*.ts"
---

# 라이선스(License) 규칙

## 백엔드 라우터 (`/api/v1/license`)
| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/status` | admin | 라이선스 상태 전체 조회 |
| GET | `/permissions` | 인증됨 | 기능 권한 조회 |
| POST | `/register` | admin | 키 등록 (자동 타입 감지) |
| DELETE | `/key` | admin | 키 삭제 |
| POST | `/enforcement` | admin | 강제 모드 토글 |

**레거시**: GET `/api/v1/license_permissions/` — 하위호환 (인증 불필요)

## JWT RS256 검증 (utils/license.py)
- 공개키 기반 오프라인 검증 (중앙 서버 불필요)
- 발급자: `iss == "cloosphere"`
- `decode_license_key(token)` → LicenseKeyPayload
- `decode_feature_key(token)` → FeatureKeyPayload

## 2단계 키 시스템
### 라이선스 키 (티어 지정)
```python
LicenseKeyPayload: iss, type="license", tier, company, max_users, exp, iat
```

### 피처 키 (개별 모듈)
```python
FeatureKeyPayload: iss, type="feature", module, company, exp, iat
```

## 티어 → 모듈 매핑
| 티어 | 모듈 |
|------|------|
| BASIC | (없음) |
| STANDARD | audit_log, glossary, guardrail, image_generation, kbsphere, tools |
| PROFESSIONAL | 위 6개 + agent_flow, branding, dbsphere, evaluation, trace |
| ENTERPRISE | `has_all_features=True` (현재+미래 자동) |

## 11개 기능 모듈 (FeatureModule enum)
audit_log, glossary, guardrail, image_generation, kbsphere, tools,
agent_flow, branding, dbsphere, evaluation, trace

## ENABLE_LICENSE_ENFORCEMENT
- `False` (기본): 모든 기능 자유 사용, `is_feature_enabled()` → 항상 True
- `True`: 라이선스/피처 키 기반 기능 제어
- PersistentConfig: `license.enforcement_enabled`

## 기능 체크 패턴
```python
# 라우터에서 의존성으로 사용
@router.get("/", dependencies=[Depends(require_feature("dbsphere"))])

# 유틸리티 직접 호출
if is_feature_enabled(app, "agent_flow"):
    ...
```

## resolve_license_status() 로직
1. 라이선스 키들 디코드 → 최고 우선순위 티어 선택
2. 티어 포함 모듈 → permissions에 추가
3. PROFESSIONAL 이상 → `has_all_features=True`
4. 피처 키들 → 개별 모듈 permissions에 추가 (누적)

## Config 저장
```python
LICENSE_KEYS = PersistentConfig("LICENSE_KEYS", "license.keys", [])
FEATURE_KEYS = PersistentConfig("FEATURE_KEYS", "license.feature_keys", [])
ENABLE_LICENSE_ENFORCEMENT = PersistentConfig(...)
```

## 프론트엔드 (License.svelte)
- License Status: 상태, 티어, 회사, 만료일, 최대 사용자
- Register Key: 텍스트 입력 → 자동 타입 감지
- Registered Keys: 라이선스(파란)/피처(자주) 배지 + 삭제
- Feature Status: enforcement 활성 시 모듈별 Available/Not Licensed

## Cloocus Admin 모델 (cloocus_admin.py)
- CloocusCustomer, CloocusLicenseRecord, CloocusFeatureKeyRecord, CloocusFeatureRegistry
- 용도: Cloocus 중앙 관리에서 발급 이력 추적
