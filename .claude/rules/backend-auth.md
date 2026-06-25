---
paths:
  - "backend/open_webui/utils/auth.py"
  - "backend/open_webui/utils/access_control.py"
  - "backend/open_webui/utils/oauth.py"
  - "backend/open_webui/routers/auths.py"
---

# 인증/권한 검사 규칙

## 인증 의존성 (Depends)
- `get_verified_user`: role이 "user" 또는 "admin" 확인. 대부분의 엔드포인트에 사용
- `get_admin_user`: role이 "admin"만 허용. 관리자 전용 엔드포인트
- `get_admin_user_or_permission(permission_key)`: 팩토리 함수 (기존 호환용 — write 레벨 의미)
- `get_admin_user_or_permission_level(permission_key, min_level)`: 팩토리 함수, admin 또는 특정 권한을 `min_level` 이상으로 보유한 사용자 허용

## 사전 정의된 권한 의존성
```python
# 기존 호환 (write 레벨)
get_admin_users_access = get_admin_user_or_permission("admin.users")
get_admin_evaluations_access = get_admin_user_or_permission("admin.evaluations")
get_admin_functions_access = get_admin_user_or_permission("admin.functions")
get_admin_settings_access = get_admin_user_or_permission("admin.settings")
get_admin_monitoring_access = get_admin_user_or_permission("admin.monitoring")

# read 레벨 (조회 엔드포인트용)
get_admin_users_read_access = get_admin_user_or_permission_level("admin.users", "read")
get_admin_evaluations_read_access = get_admin_user_or_permission_level("admin.evaluations", "read")
get_admin_functions_read_access = get_admin_user_or_permission_level("admin.functions", "read")
get_admin_settings_read_access = get_admin_user_or_permission_level("admin.settings", "read")
get_admin_monitoring_read_access = get_admin_user_or_permission_level("admin.monitoring", "read")

# write 레벨 (수정/생성/삭제 엔드포인트용)
get_admin_users_write_access = get_admin_user_or_permission_level("admin.users", "write")
get_admin_evaluations_write_access = get_admin_user_or_permission_level("admin.evaluations", "write")
get_admin_functions_write_access = get_admin_user_or_permission_level("admin.functions", "write")
get_admin_settings_write_access = get_admin_user_or_permission_level("admin.settings", "write")
get_admin_monitoring_write_access = get_admin_user_or_permission_level("admin.monitoring", "write")
```

## 4단계 권한 레벨 시스템
`PERMISSION_LEVELS = {"none": 0, "access": 1, "read": 2, "write": 3}` (`access_control.py:10`)

- **none**: 접근 불가
- **access**: 리소스 메타데이터 접근만 (미리보기 등)
- **read**: 조회 가능
- **write**: 생성/수정/삭제 가능

그룹 권한 결합 시 **가장 높은 레벨**이 적용됨. 기본값은 `config.py`의 `DEFAULT_USER_PERMISSIONS` (admin.* / workspace.*) — 모두 string enum.

### 레벨 검사 함수
```python
from open_webui.utils.access_control import has_permission_min_level

has_permission_min_level(user_id, "workspace.knowledge", "read", DEFAULT_USER_PERMISSIONS)
```
- `has_permission()`: 하위 호환 — string "none"→False, 그 외→True
- `has_permission_min_level()`: string/boolean 모두 지원, 정확한 레벨 비교
- `get_permission_level(value)`: boolean→write(3)/none(0), string→상수 매핑

## 역할 (Role)
- `pending`: 가입 대기 (API 접근 불가)
- `user`: 일반 사용자
- `admin`: 관리자 (모든 권한)
- `moderator`: 중간 관리자

## 리소스 접근 제어 — `has_access()`
```python
has_access(user_id: str, type: str, access_control: Optional[dict]) -> bool
```
- `access_control = None`: 공개 (모든 user 읽기 가능)
- `access_control = {}`: 비공개 (소유자만)
- 구조: `{"read": {"user_ids": [...], "group_ids": [...], "org_unit_ids": [...]}, "write": {...}}`

## 워크스페이스 권한 — `has_permission()` / `has_permission_min_level()`
```python
has_permission(user_id: str, permission_key: str, default_permissions: dict) -> bool
has_permission_min_level(user_id: str, permission_key: str, min_level: str, default_permissions: dict) -> bool
```
- 그룹 권한 우선 → 기본값 폴백, 여러 그룹일 경우 가장 높은 레벨 선택
- 키 예시: `workspace.knowledge`, `workspace.agents`, `admin.users`, `chat.delete`
- 워크스페이스 라우터 관례: GET list → `read`, POST create/update → `write`

## JWT 토큰
- `create_token(data={"id": user.id}, expires_delta)`: JWT 생성
- HS256 알고리즘, SESSION_SECRET (WEBUI_SECRET_KEY) 사용
- 쿠키 (httponly, secure) 또는 `Authorization: Bearer <token>` 헤더

## API 키
- `sk-` 접두사, `create_api_key()` 생성
- `get_current_user_by_api_key(api_key)` 검증

## 조직 단위 — `get_user_org_unit_ids()`
- oauth_sub 또는 email로 조직 단위 매칭
- 조상 단위 포함 (계층적 상속)
- access_control의 org_unit_ids와 비교

## 참조 파일
- `utils/auth.py`: JWT, 비밀번호 해싱, 의존성 함수
- `utils/access_control.py`: has_access, has_permission, 그룹 권한
- `utils/oauth.py`: OAuth2 프로바이더 통합
- `routers/auths.py`: 로그인/가입/LDAP/OAuth 엔드포인트
