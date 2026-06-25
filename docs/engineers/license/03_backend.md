> Last Updated: 2026-04-08

# 03. 백엔드 구현 상세

## 파일 구조

```
backend/open_webui/
├── utils/
│   └── license.py               ← 핵심 로직
├── routers/
│   ├── license.py               ← 키 등록/삭제 API (고객용)
│   ├── license_permissions.py   ← 권한 조회 API (레거시 호환)
│   └── cloocus.py               ← 클루커스 내부 관리 API
├── internal/
│   └── cloocus_db.py            ← 클루커스 내부 DB 연결
└── models/
    └── cloocus_admin.py         ← 클루커스 내부 DB 모델
```

---

## `license.py` 주요 구성

### Public Key 설정

```python
# 환경변수 우선, 없으면 내장 키 사용
_env_pubkey = os.environ.get("CLOOSPHERE_PUBLIC_KEY", "").strip()
CLOOSPHERE_PUBLIC_KEY = _env_pubkey or """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8...
-----END PUBLIC KEY-----"""
```

> **보안**: Private key는 이 코드베이스에 없습니다. 클루커스 내부 키 생성 도구에만 존재합니다.
> Public key를 교체해야 할 경우 `CLOOSPHERE_PUBLIC_KEY` 환경변수로 주입합니다.

### LicenseTier Enum (5단계)

```python
class LicenseTier(str, Enum):
    BASIC        = "basic"
    STANDARD     = "standard"
    PROFESSIONAL = "professional"
    ENTERPRISE   = "enterprise"
    DEVELOPER    = "developer"
```

| Tier | Priority | 용도 |
|---|---|---|
| `basic` | 1 | license 없음 / 만료 fallback. 모듈 없음 |
| `standard` | 2 | 6개 기본 모듈 |
| `professional` | 3 | 11개 모듈 (standard 6개 + professional 5개) |
| `enterprise` | 4 | 모든 모듈 + 향후 자동 (`has_all_features=True`) |
| `developer` | 5 | Cloocus 내부 개발자. enterprise와 동일하게 전체 자동 |

### FeatureModule Enum (13개)

```python
class FeatureModule(str, Enum):
    # 아래 enum 주석의 "Standard tier (8개)"는 enum 멤버를 그룹화한 것일 뿐,
    # 실제 티어 배정은 TIER_INCLUDED_MODULES 딕셔너리에서 결정됩니다.
    # CODE_GATEWAY / FILE_GUARDRAIL은 enum 선언 위치와 무관하게 Enterprise 전용입니다.
    AUDIT_LOG        = "audit_log"
    CODE_GATEWAY     = "code_gateway"      # ENTERPRISE 전용
    FILE_GUARDRAIL   = "file_guardrail"    # ENTERPRISE 전용
    GLOSSARY         = "glossary"
    GUARDRAIL        = "guardrail"
    IMAGE_GENERATION = "image_generation"
    KBSPHERE         = "kbsphere"
    TOOLS            = "tools"
    # Professional tier 추가
    AGENT_FLOW       = "agent_flow"
    BRANDING         = "branding"
    DBSPHERE         = "dbsphere"
    EVALUATION       = "evaluation"
    TRACE            = "trace"
```

> 새 모듈 추가 시 enum에 먼저 추가하고, 아래 `TIER_INCLUDED_MODULES`에 적절한 tier로 배정해야 합니다. Enterprise 전용으로 두려면 딕셔너리에서 STANDARD/PROFESSIONAL에 넣지 **않으면** 됩니다 (ENTERPRISE는 `has_all_features=True`로 자동 포함됨).

### TIER_INCLUDED_MODULES (실제 배정)

```python
TIER_INCLUDED_MODULES: dict[LicenseTier, set[FeatureModule]] = {
    LicenseTier.BASIC: set(),                   # 모듈 없음
    LicenseTier.STANDARD: {                     # 6개
        FeatureModule.AUDIT_LOG,
        FeatureModule.GLOSSARY,
        FeatureModule.GUARDRAIL,
        FeatureModule.IMAGE_GENERATION,
        FeatureModule.KBSPHERE,
        FeatureModule.TOOLS,
    },
    LicenseTier.PROFESSIONAL: {                 # 11개 (standard 6 + professional 5)
        FeatureModule.AUDIT_LOG,
        FeatureModule.GLOSSARY,
        FeatureModule.GUARDRAIL,
        FeatureModule.IMAGE_GENERATION,
        FeatureModule.KBSPHERE,
        FeatureModule.TOOLS,
        FeatureModule.AGENT_FLOW,
        FeatureModule.BRANDING,
        FeatureModule.DBSPHERE,
        FeatureModule.EVALUATION,
        FeatureModule.TRACE,
    },
    # ENTERPRISE 이상: has_all_features=True (향후 추가 모듈 자동 포함)
    # CODE_GATEWAY, FILE_GUARDRAIL은 Enterprise 전용 (DB fallback 기준)
    LicenseTier.ENTERPRISE: set(),
    LicenseTier.DEVELOPER: set(),
}

TIER_PRIORITY = {
    LicenseTier.BASIC: 1,
    LicenseTier.STANDARD: 2,
    LicenseTier.PROFESSIONAL: 3,
    LicenseTier.ENTERPRISE: 4,
    LicenseTier.DEVELOPER: 5,
}

# 이 우선순위 이상이면 has_all_features=True (향후 추가 모듈 자동 포함)
TIER_ALL_FEATURES_THRESHOLD = 4  # ENTERPRISE 이상
```

> **과거 문서와의 차이 (주의)**: 이전 문서 버전은 `TIER_ALL_FEATURES_THRESHOLD = 3 (PROFESSIONAL)`과 `PROFESSIONAL: set()`으로 기술되어 있었으나, **현재 코드는 PROFESSIONAL을 11개 모듈로 명시하고 threshold를 4 (ENTERPRISE)로 설정**하고 있습니다. CODE_GATEWAY/FILE_GUARDRAIL이 Enterprise 전용이라는 코드 주석(`license.py` line 115)으로 볼 때, 이 구조는 해당 두 모듈이 PROFESSIONAL 고객에게 자동 활성화되는 것을 방지하기 위한 의도로 보입니다.

### DB 레지스트리 fallback (`load_tier_modules_from_db`)

`CLOOCUS_ADMIN_DATABASE_URL`이 설정된 Cloocus 내부 환경에서는 `cloocus_admin` DB의 feature registry를 읽어 `TIER_INCLUDED_MODULES`를 런타임에 덮어씁니다. 미설정이거나 DB 오류 시 위의 하드코딩 매핑이 fallback으로 사용됩니다. 고객 환경은 항상 하드코딩 매핑을 사용합니다.

---

## 라우터 게이팅 현황

현재 `require_feature()` 데코레이터가 적용된 라우터:

| 라우터 파일 | module_id | 티어 | 적용 범위 |
|------------|-----------|------|---|
| `knowledge.py` | `kbsphere` | standard | 라우터 전체 |
| `guardrails.py` | `guardrail` | standard | 라우터 전체 |
| `glossary.py` | `glossary` | standard | 라우터 전체 |
| `tools.py` | `tools` | standard | 라우터 전체 |
| `audit_logs.py` | `audit_log` | standard | 라우터 전체 |
| `images.py` | `image_generation` | standard | 라우터 전체 |
| `dbsphere.py` | `dbsphere` | professional | 라우터 전체 |
| `agent_flows.py` | `agent_flow` | professional | 라우터 전체 |
| `auto_evaluations.py` | `evaluation` | professional | 라우터 전체 |
| `traces.py`, `trace_analysis.py` | `trace` | professional | 라우터 전체 |
| `branding.py` | `branding` | professional | 엔드포인트별 (`/config`, `/app-name`, `/upload/{asset_type}`, `/{asset_type}` DELETE) |

### Enterprise 전용 모듈의 비표준 게이팅

**`code_gateway`와 `file_guardrail`은 `require_feature()`를 직접 사용하지 않는다** — 2026-04-08 기준. 대신 다음 메커니즘으로 gating:

| 모듈 | 라우터/경로 | Gating 방식 |
|---|---|---|
| `code_gateway` | `routers/code_gateway.py` (`/api/v1/code-gateway`) | `_check_gateway_access(request, user)` 내부 함수 (line 1995~) — **`ENABLE_CODE_GATEWAY` PersistentConfig 토글** + `has_permission(user.id, "features.code_gateway", USER_PERMISSIONS)` 체크. **⚠️ 라우터 코드에서 직접 `is_feature_enabled(app, "code_gateway")` 를 호출하지 않음** — license enum에만 등록되어 있고 admin 토글과 user permission에만 의존. |
| `file_guardrail` | `routers/files.py` | `utils/file_guardrails.py` **utility module** (FastAPI middleware 아님) — 5-stage pipeline: Stage 1 `detect_macros` (pre-storage), Stage 2 `strip_exif_metadata` + `detect_nsfw_via_llm` (post-storage), Stage 3 `apply_text_guardrails[_with_llm]` (GuardrailEngine 재사용, block-only), Stage 4 `classify_document` (LLM 분류). `FILE_GUARDRAIL_ENABLED`/`FILE_GUARDRAIL_SCOPES` config 플래그로 제어. Orchestrator: `run_pre_storage_guardrails`, `run_post_storage_guardrails`, `run_text_guardrails`, `run_classification`. |

**⚠️ 중요 — License enforcement 갭**: 현재 코드(2026-04-08)에는 **`CODE_GATEWAY`와 `FILE_GUARDRAIL` 모듈의 license feature gate가 코드 레벨에서 실제로 enforce되지 않는 것으로 보입니다**. Enum에 정의되어 있고 `TIER_INCLUDED_MODULES`에서 PROFESSIONAL 이하에 포함되지 않았으나, `require_feature()`나 `is_feature_enabled()` 호출이 해당 라우터/유틸에 없습니다. 실질적인 접근 제어는:
- **Code Gateway**: Admin 토글 `ENABLE_CODE_GATEWAY` + user permission `features.code_gateway`
- **File Guardrail**: Admin 토글 `FILE_GUARDRAIL_ENABLED` + `FILE_GUARDRAIL_SCOPES`

License 티어와의 실제 연동은 **Admin UI에서 license 상태에 따라 해당 토글을 숨기거나 자동 제어**하는 방식일 가능성이 있습니다 (코드 검증 필요). 신규 모듈 추가 시에는 **`require_feature()` 또는 `is_feature_enabled()` 명시적 호출을 권장**합니다.

### 패턴

```python
from open_webui.utils.license import require_feature

# 라우터 전체 게이팅 (권장)
router = APIRouter(dependencies=[Depends(require_feature("module_id"))])

# 특정 엔드포인트만 게이팅
@router.post("/action", dependencies=[Depends(require_feature("module_id"))])
async def my_endpoint(...):
    ...
```

---

## 키 관리 API (고객용)

**prefix**: `/api/v1/license`

| 메서드 | 경로 | 설명 | 권한 |
|--------|------|------|------|
| GET | `/status` | 전체 라이선스 상태 조회 | admin |
| GET | `/permissions` | 모듈별 허용 여부 조회 | 인증된 사용자 |
| POST | `/register` | 키 등록 (타입 자동 감지) | admin |
| DELETE | `/key` | 키 삭제 | admin |
| POST | `/enforcement` | enforcement 토글 | admin |

### 키 등록 예시

```bash
curl -X POST /api/v1/license/register \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"key": "eyJhbGciOiJSUzI1NiJ9..."}'
```

응답:
```json
{
  "success": true,
  "type": "license",
  "payload": {
    "tier": "standard",
    "company": "고객사명",
    "max_users": 100,
    "exp": 1737600000
  }
}
```

---

## 클루커스 내부 DB (`cloocus_db.py`)

`CLOOCUS_ADMIN_DATABASE_URL` 환경변수 설정 시에만 활성화됩니다.
고객 환경에는 이 변수가 없으므로 모든 관련 함수가 자동으로 skip됩니다.

```python
# 사용 가능 여부 확인
if is_cloocus_db_available():
    ...

# 세션 사용 (컨텍스트 매니저)
with get_cloocus_db() as db:
    records = db.query(CloocusLicenseRecord).all()
```

### 시작 시 자동 초기화

```python
# main.py lifespan
run_cloocus_migrations()   # 테이블 자동 생성
seed_feature_registry()    # 기능 레지스트리 초기 데이터 삽입
```

`seed_feature_registry()`는 **이미 있는 항목은 건너뛰고** 없는 것만 삽입합니다.

---

## 클루커스 내부 DB 모델

### CloocusCustomer — 고객사 정보

```python
class CloocusCustomer(CloocusBase):
    id           # PK
    company_name # 고객사명
    contact_email
    contact_name
    notes
    is_active
```

### CloocusLicenseRecord — 발급 이력

```python
class CloocusLicenseRecord(CloocusBase):
    id
    customer_id   # CloocusCustomer FK
    tier          # basic / standard / professional
    max_users
    issued_at
    expires_at
    token         # 발급된 JWT 전문
    is_revoked    # 폐기 여부
```

### CloocusFeatureKeyRecord — 피처 키 발급 이력

```python
class CloocusFeatureKeyRecord(CloocusBase):
    id
    customer_id
    module        # 허용한 module_id
    expires_at
    token
    is_revoked
```

### CloocusFeatureRegistry — 모듈 레지스트리

```python
class CloocusFeatureRegistry(CloocusBase):
    module_id     # PK (예: "kbsphere")
    display_name  # 표시명 (예: "Knowledge Base (KbSphere)")
    description
    tier_minimum  # standard / professional
    is_active
```

---

## 환경변수 정리

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ENABLE_LICENSE_ENFORCEMENT` | `false` | 라이선스 검사 활성화 |
| `LICENSE_KEYS` | `[]` | 등록된 라이선스 JWT 목록 (DB Config에 저장) |
| `FEATURE_KEYS` | `[]` | 등록된 피처 JWT 목록 (DB Config에 저장) |
| `CLOOSPHERE_PUBLIC_KEY` | 내장 | RS256 공개키 (환경변수로 덮어쓰기 가능) |
| `CLOOCUS_ADMIN_DATABASE_URL` | 없음 | 클루커스 내부 DB (고객 환경에는 없음) |
