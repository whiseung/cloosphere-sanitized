# 권한/인증 가이드

## 권한 체계 개요

Cloosphere는 3단계 권한 체계를 사용합니다:

```
┌─────────────────────────────────────────────────────┐
│  1. 역할 기반 권한 (Role-Based)                      │
│     pending, user, admin, moderator                 │
├─────────────────────────────────────────────────────┤
│  2. 그룹 기반 권한 (Group-Based)                     │
│     Group.member_ids, Group.permissions             │
├─────────────────────────────────────────────────────┤
│  3. 조직 기반 권한 (Org-Based)                       │
│     Organization → OrganizationalUnit → member_ids  │
│     계층적 상속 지원                                 │
└─────────────────────────────────────────────────────┘
```

## 1. 역할 기반 권한

### 사용자 역할

```python
# models/users.py
class User(Base):
    role = Column(Text)  # "pending", "user", "admin", "moderator"
```

| 역할 | 설명 | 권한 |
|------|------|------|
| `pending` | 승인 대기 | 기본 권한 없음 |
| `user` | 일반 사용자 | 채팅, 본인 리소스 관리 |
| `admin` | 관리자 | 모든 권한 + 시스템 설정 |
| `moderator` | 중재자 | 콘텐츠 관리 권한 |

### 인증 의존성 함수

```python
# utils/auth.py

async def get_current_user(
    request: Request,
    background_tasks: BackgroundTasks,
    auth_token: str = None
) -> Optional[UserModel]:
    """토큰에서 사용자 정보 추출 (인증만, 권한 검사 없음)"""

async def get_verified_user(
    user: UserModel = Depends(get_current_user)
) -> UserModel:
    """인증된 사용자 (role in {user, admin, moderator})"""
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.role == "pending":
        raise HTTPException(status_code=403, detail="Account pending approval")
    return user

async def get_admin_user(
    user: UserModel = Depends(get_current_user)
) -> UserModel:
    """관리자만 (role == admin)"""
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

### 라우터에서 사용

```python
from open_webui.utils.auth import get_verified_user, get_admin_user

# 일반 사용자 접근
@router.get("/items")
async def get_items(user=Depends(get_verified_user)):
    pass

# 관리자 전용
@router.get("/admin/items")
async def admin_get_items(user=Depends(get_admin_user)):
    pass
```

## 2. 그룹 기반 권한

### Group 모델

```python
# models/groups.py
class Group(Base):
    __tablename__ = "group"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)           # 그룹 생성자
    name = Column(Text)
    description = Column(Text)
    member_ids = Column(JSON)        # ["user-id-1", "user-id-2"]
    permissions = Column(JSON)       # 계층적 권한
```

### 그룹 권한 구조

```python
permissions = {
    "workspace": {
        "models": True,           # 모델 관리
        "knowledge": True,        # 지식베이스
        "prompts": True,          # 프롬프트
        "tools": True,            # 도구
    },
    "chat": {
        "delete": False,          # 채팅 삭제
        "edit": True,             # 채팅 편집
        "temporary": True,        # 임시 채팅
    },
    "features": {
        "web_search": True,
        "image_generation": False,
        "code_interpreter": True,
    }
}
```

### 권한 조합 규칙

여러 그룹에 속한 경우 **최대 권한** 적용:

```python
# utils/access_control.py
def get_permissions(user_id: str, default_permissions: dict) -> dict:
    """사용자의 모든 그룹 권한 조합"""
    user_groups = Groups.get_groups_by_member_id(user_id)

    combined = default_permissions.copy()
    for group in user_groups:
        if group.permissions:
            combined = merge_permissions(combined, group.permissions)

    return combined

def merge_permissions(base: dict, override: dict) -> dict:
    """권한 병합 (True > False)"""
    result = base.copy()
    for key, value in override.items():
        if isinstance(value, dict):
            result[key] = merge_permissions(result.get(key, {}), value)
        elif value is True:
            result[key] = True  # True가 우선
    return result
```

### 권한 검사

```python
# utils/access_control.py
def has_permission(
    user_id: str,
    permission_key: str,  # "chat.delete" 형식
    default_permissions: dict
) -> bool:
    """계층적 권한 검사"""
    permissions = get_permissions(user_id, default_permissions)

    # "chat.delete" → ["chat", "delete"]
    keys = permission_key.split(".")
    current = permissions

    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, False)
        else:
            return bool(current)

    return bool(current)

# 사용 예시
if not has_permission(user.id, "chat.delete", default_permissions):
    raise HTTPException(status_code=403, detail="No permission to delete")
```

## 3. 조직 기반 권한

### 모델 구조

```python
# models/organization.py

class Organization(Base):
    """최상위 조직 (회사/테넌트)"""
    __tablename__ = "organization"

    id = Column(Text, primary_key=True)
    tenant_id = Column(Text)         # Azure AD Tenant ID
    name = Column(Text)
    display_name = Column(Text)
    domain = Column(Text)            # contoso.com


class OrganizationalUnit(Base):
    """조직 단위 (부서/팀)"""
    __tablename__ = "organizational_unit"

    id = Column(Text, primary_key=True)
    organization_id = Column(Text)   # 소속 조직
    parent_id = Column(Text)         # 상위 조직 단위 (계층 구조)
    name = Column(Text)
    display_name = Column(Text)
    level = Column(Integer)          # 계층 레벨 (0=루트)
    type = Column(Text)              # department, team, admin_unit
    external_id = Column(Text)       # Azure AD Object ID
    member_ids = Column(JSON)        # ["oauth-sub-1", "email@domain.com"]
    meta = Column(JSON)              # 멤버 상세 정보
```

### 조직 단위 멤버십 검사

```python
# utils/access_control.py

def get_user_org_unit_ids(
    user_id: str,
    include_ancestors: bool = True
) -> list[str]:
    """사용자가 속한 조직 단위 ID 목록 (상위 계층 포함)"""
    user = Users.get_user_by_id(user_id)
    if not user:
        return []

    # 매칭 우선순위: oauth_sub > email
    user_identifiers = [user.oauth_sub, user.email]

    all_units = OrganizationalUnits.get_all_organizational_units()
    user_unit_ids = []

    for unit in all_units:
        member_ids = unit.member_ids or []
        # oauth_sub 또는 email로 매칭
        if any(uid in member_ids for uid in user_identifiers if uid):
            user_unit_ids.append(unit.id)

            # 상위 계층 포함
            if include_ancestors and unit.parent_id:
                ancestors = get_org_unit_ancestors(unit.id)
                user_unit_ids.extend(ancestors)

    return list(set(user_unit_ids))


def get_org_unit_ancestors(org_unit_id: str) -> list[str]:
    """조직 단위의 모든 상위 조직 단위 ID"""
    ancestors = []
    unit = OrganizationalUnits.get_organizational_unit_by_id(org_unit_id)

    while unit and unit.parent_id:
        ancestors.append(unit.parent_id)
        unit = OrganizationalUnits.get_organizational_unit_by_id(unit.parent_id)

    return ancestors
```

## 4. 리소스 접근 제어

### access_control 필드 구조

```python
# 리소스(Knowledge, DbSphere 등)의 access_control 필드
access_control = {
    "read": {
        "user_ids": ["user-id-1", "user-id-2"],     # 직접 지정 사용자
        "group_ids": ["group-id-1"],                # 그룹
        "org_unit_ids": ["org-unit-id-1"]           # 조직 단위
    },
    "write": {
        "user_ids": ["user-id-1"],
        "group_ids": ["group-id-1"],
        "org_unit_ids": []
    }
}

# None → 비공개 (소유자만)
# {} (빈 dict) → 공개
```

### 접근 검사 함수

```python
# utils/access_control.py

def has_access(
    user_id: str,
    type: str = "write",  # "read" 또는 "write"
    access_control: Optional[dict] = None
) -> bool:
    """리소스 접근 권한 검사"""

    # 1. 공개 리소스
    if access_control is None:
        return False  # 소유자만 (라우터에서 별도 처리)
    if access_control == {}:
        return True   # 모든 사용자

    permissions = access_control.get(type, {})

    # 2. 직접 지정 사용자
    user_ids = permissions.get("user_ids", [])
    if user_id in user_ids:
        return True

    # 3. 그룹 권한
    group_ids = permissions.get("group_ids", [])
    if group_ids:
        user_groups = Groups.get_groups_by_member_id(user_id)
        if any(g.id in group_ids for g in user_groups):
            return True

    # 4. 조직 단위 권한 (상위 계층 포함)
    org_unit_ids = permissions.get("org_unit_ids", [])
    if org_unit_ids:
        user_org_units = get_user_org_unit_ids(user_id, include_ancestors=True)
        if any(ou in org_unit_ids for ou in user_org_units):
            return True

    return False
```

### 라우터에서 사용

```python
from open_webui.utils.access_control import has_access

@router.get("/{id}")
async def get_item(id: str, user=Depends(get_verified_user)):
    item = Items.get_item_by_id(id)

    if not item:
        raise HTTPException(status_code=404, detail="Not found")

    # 소유자 확인
    if item.user_id == user.id:
        return item

    # 공유 권한 확인
    if has_access(user.id, type="read", access_control=item.access_control):
        return item

    # 관리자 확인
    if user.role == "admin":
        return item

    raise HTTPException(status_code=403, detail="Permission denied")


@router.post("/{id}")
async def update_item(id: str, form_data: ItemForm, user=Depends(get_verified_user)):
    item = Items.get_item_by_id(id)

    # 수정은 write 권한 필요
    if item.user_id != user.id and not has_access(
        user.id, type="write", access_control=item.access_control
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    # 수정 로직...
```

## 5. JWT 인증

### 토큰 생성

```python
# utils/auth.py

def create_token(data: dict, expires_delta: timedelta = None) -> str:
    """JWT 토큰 생성"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=7)

    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, WEBUI_SECRET_KEY, algorithm=ALGORITHM)


# 로그인 시 토큰 발급
@router.post("/signin")
async def signin(form_data: SigninForm):
    user = Auths.authenticate_user(form_data.email, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(
        data={"id": user.id},
        expires_delta=timedelta(days=7)
    )
    return {"token": token, "user": user}
```

### 토큰 검증

```python
# utils/auth.py

def decode_token(token: str) -> Optional[dict]:
    """JWT 토큰 디코딩"""
    try:
        payload = jwt.decode(token, WEBUI_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None


async def get_current_user(request: Request, auth_token: str = None):
    """요청에서 사용자 추출"""
    token = auth_token

    # 1. Authorization 헤더
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    # 2. 쿠키
    if not token:
        token = request.cookies.get("token")

    if not token:
        return None

    # API 키인지 확인
    if token.startswith("sk-"):
        return await get_current_user_by_api_key(token)

    # JWT 디코딩
    payload = decode_token(token)
    if not payload:
        return None

    user_id = payload.get("id")
    return Users.get_user_by_id(user_id)
```

## 6. API 키

### API 키 생성

```python
# utils/auth.py

def create_api_key() -> str:
    """sk-로 시작하는 API 키 생성"""
    return f"sk-{secrets.token_urlsafe(32)}"


# 사용자 API 키 발급
@router.post("/api-keys")
async def create_api_key_endpoint(user=Depends(get_verified_user)):
    api_key = create_api_key()
    # DB에 해시된 키 저장
    Users.update_user_api_key(user.id, get_password_hash(api_key))
    return {"api_key": api_key}  # 한 번만 표시
```

### API 키 검증

```python
# utils/auth.py

async def get_current_user_by_api_key(api_key: str) -> Optional[UserModel]:
    """API 키로 사용자 조회"""
    users = Users.get_all_users()

    for user in users:
        if user.api_key and verify_password(api_key, user.api_key):
            return user

    return None
```

## 권한 검사 플로우

```
┌─────────────────────────────────────┐
│  요청 수신                           │
│  Authorization: Bearer <token>      │
└─────────────────────────────────────┘
            ↓
┌─────────────────────────────────────┐
│  get_current_user()                 │
│  - 토큰 추출 (헤더/쿠키)              │
│  - API 키 vs JWT 분기                │
│  - 사용자 정보 조회                   │
└─────────────────────────────────────┘
            ↓
┌─────────────────────────────────────┐
│  get_verified_user()                │
│  - role 검사 (pending 차단)          │
└─────────────────────────────────────┘
            ↓
┌─────────────────────────────────────┐
│  라우터 핸들러                        │
│  - 리소스 조회                        │
│  - 소유자 확인 (user_id)              │
│  - has_access() 권한 검사            │
└─────────────────────────────────────┘
            ↓
┌─────────────────────────────────────┐
│  응답 반환 또는 403 에러              │
└─────────────────────────────────────┘
```

## 참조 파일

| 파일 | 역할 |
|------|------|
| `utils/auth.py` (7.3KB) | JWT, 비밀번호, API 키 |
| `utils/access_control.py` (8.8KB) | 권한 검사 함수 |
| `utils/oauth.py` (25KB) | OAuth 프로바이더 |
| `models/groups.py` | 그룹 모델 |
| `models/organization.py` | 조직 모델 |
| `routers/auths.py` (30KB) | 인증 엔드포인트 |
