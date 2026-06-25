# 기술 아키텍처

## 데이터베이스 모델

### Organization (조직)

최상위 조직 엔티티입니다. 일반적으로 회사 또는 테넌트를 나타냅니다.

```python
# backend/open_webui/models/organization.py

class Organization(Base):
    __tablename__ = "organization"

    id: str              # UUID
    tenant_id: str       # 외부 시스템 ID (예: Azure Tenant ID)
    name: str            # 조직 이름
    display_name: str    # 표시 이름
    domain: str          # 도메인 (예: contoso.com)
    meta: dict           # 추가 메타데이터 (JSON)
    created_at: int      # 생성 시간 (Unix timestamp)
    updated_at: int      # 수정 시간 (Unix timestamp)
```

### OrganizationalUnit (조직 단위)

조직 내 부서, 팀 등의 계층 구조를 나타냅니다.

```python
class OrganizationalUnit(Base):
    __tablename__ = "organizational_unit"

    id: str              # UUID
    organization_id: str # 소속 조직 ID (FK)
    parent_id: str       # 상위 조직 단위 ID (계층 구조)
    name: str            # 이름 (예: "Engineering")
    display_name: str    # 표시 이름 (예: "엔지니어링팀")
    description: str     # 설명
    level: int           # 계층 레벨 (0=루트)
    type: str            # 유형 (department, team, admin_unit 등)
    external_id: str     # 외부 시스템 ID (예: Azure AD Object ID)
    member_ids: list     # 멤버 ID 목록 (oauth_sub 또는 email)
    meta: dict           # 추가 메타데이터 (멤버 상세 정보 등)
    created_at: int
    updated_at: int
```

### ER 다이어그램

```
┌─────────────────┐       ┌─────────────────────┐
│  Organization   │       │  OrganizationalUnit │
├─────────────────┤       ├─────────────────────┤
│ id (PK)         │◄──────│ organization_id(FK) │
│ tenant_id       │       │ id (PK)             │
│ name            │       │ parent_id (FK,self) │
│ display_name    │       │ name                │
│ domain          │       │ display_name        │
│ meta            │       │ member_ids          │
└─────────────────┘       │ meta                │
                          └─────────────────────┘
                                   │
                                   │ member_ids
                                   ▼
                          ┌─────────────────────┐
                          │       User          │
                          ├─────────────────────┤
                          │ id (PK)             │
                          │ oauth_sub           │
                          │ email               │
                          └─────────────────────┘
```

## API 구조

### 엔드포인트 목록

**Backend**: `backend/open_webui/routers/organizations.py`

| Method | Endpoint | 설명 | 권한 |
|--------|----------|------|------|
| GET | `/api/organizations/` | 모든 조직 목록 | verified_user |
| GET | `/api/organizations/{id}` | 조직 상세 | verified_user |
| POST | `/api/organizations/` | 조직 생성 | admin |
| POST | `/api/organizations/{id}` | 조직 수정 | admin |
| DELETE | `/api/organizations/{id}` | 조직 삭제 | admin |
| GET | `/api/organizations/units` | 모든 조직 단위 | verified_user |
| GET | `/api/organizations/{org_id}/units` | 조직의 조직 단위 | verified_user |
| GET | `/api/organizations/{org_id}/units/tree` | 조직 단위 트리 | verified_user |
| GET | `/api/organizations/units/{id}` | 조직 단위 상세 | verified_user |
| POST | `/api/organizations/units` | 조직 단위 생성 | admin |
| POST | `/api/organizations/units/{id}` | 조직 단위 수정 | admin |
| DELETE | `/api/organizations/units/{id}` | 조직 단위 삭제 | admin |
| GET | `/api/organizations/units/{id}/permissions` | 조직 단위 권한 조회 | admin |
| GET | `/api/organizations/sync/providers` | 동기화 Provider 목록 | admin |
| POST | `/api/organizations/sync/json` | JSON 동기화 | admin |
| POST | `/api/organizations/sync/msgraph` | MS Graph 동기화 | admin |

### 요청/응답 예시

#### 조직 목록 조회

```bash
GET /api/organizations/
Authorization: Bearer {token}
```

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "tenant_id": "contoso.onmicrosoft.com",
    "name": "Contoso",
    "display_name": "Contoso Corporation",
    "domain": "contoso.com",
    "meta": {},
    "created_at": 1706000000,
    "updated_at": 1706000000
  }
]
```

#### 조직 단위 트리 조회

```bash
GET /api/organizations/{org_id}/units/tree
Authorization: Bearer {token}
```

```json
[
  {
    "id": "unit-1",
    "name": "Engineering",
    "display_name": "엔지니어링",
    "type": "department",
    "level": 0,
    "member_ids": ["user-oauth-sub-1", "user-oauth-sub-2"],
    "meta": {
      "members": [
        {"id": "azure-id", "name": "홍길동", "email": "hong@contoso.com"}
      ]
    },
    "children": [
      {
        "id": "unit-2",
        "name": "Backend Team",
        "display_name": "백엔드팀",
        "type": "team",
        "level": 1,
        "children": []
      }
    ]
  }
]
```

#### MS Graph 동기화

```bash
POST /api/organizations/sync/msgraph
Authorization: Bearer {token}
Content-Type: application/json

{
  "use_admin_units": true,
  "use_groups": false,
  "use_departments": true,
  "group_filter": null
}
```

```json
{
  "success": true,
  "result": {
    "organization": {"created": 1, "updated": 0},
    "units": {"created": 5, "updated": 0, "deleted": 0}
  }
}
```

## Provider 아키텍처

동기화 로직은 Provider 패턴으로 구현되어 확장 가능합니다.

```
backend/open_webui/services/organization_providers/
├── __init__.py          # Factory: get_provider()
├── base.py              # BaseOrganizationProvider (추상 클래스)
├── json_provider.py     # JSON 데이터 파싱
└── msgraph_provider.py  # Microsoft Graph API 연동
```

### BaseOrganizationProvider

```python
class BaseOrganizationProvider(ABC):
    @abstractmethod
    async def get_organization(self) -> OrganizationModel:
        """조직 정보 가져오기"""
        pass

    @abstractmethod
    async def get_organizational_units(self) -> list[OrganizationalUnitModel]:
        """조직 단위 목록 가져오기"""
        pass

    async def sync_to_db(self) -> dict:
        """DB에 동기화 (공통 구현)"""
        org = await self.get_organization()
        units = await self.get_organizational_units()
        # DB 저장 로직...
        return {"organization": {...}, "units": {...}}
```

### MSGraphOrganizationProvider

Microsoft Graph API를 사용하여 조직 정보를 가져옵니다.

```python
class MSGraphOrganizationProvider(BaseOrganizationProvider):
    def __init__(
        self,
        access_token: str,
        use_admin_units: bool = True,
        use_groups: bool = False,
        use_departments: bool = False,
        group_filter: str = None
    ):
        ...

    @classmethod
    async def from_client_credentials(cls, tenant_id, client_id, client_secret, ...):
        """클라이언트 자격 증명으로 인스턴스 생성"""
        # Client Credentials Flow로 토큰 획득
        token = await cls._get_token_from_client_credentials(...)
        return cls(access_token=token, ...)
```

## 접근 제어 통합

### access_control 필드 구조

리소스의 `access_control` 필드 구조:

```json
{
  "read": {
    "group_ids": ["group-1", "group-2"],
    "org_unit_ids": ["unit-1", "unit-2"]
  },
  "write": {
    "group_ids": ["group-1"],
    "org_unit_ids": ["unit-1"]
  }
}
```

### 접근 체크 함수

```python
# backend/open_webui/utils/access_control.py

def get_org_unit_ancestors(org_unit_id: str) -> list[str]:
    """조직 단위의 모든 상위 조직 단위 ID 반환 (상속 체크용)"""
    ancestors = [org_unit_id]
    unit = OrganizationalUnits.get_organizational_unit_by_id(org_unit_id)
    while unit and unit.parent_id:
        ancestors.append(unit.parent_id)
        unit = OrganizationalUnits.get_organizational_unit_by_id(unit.parent_id)
    return ancestors

def has_access(
    user_id: str,
    permission: str,  # "read" or "write"
    access_control: dict
) -> bool:
    """사용자의 리소스 접근 권한 확인"""
    if access_control is None:
        return True  # public

    # 그룹 체크
    user_groups = Groups.get_groups_by_member_id(user_id)
    allowed_groups = access_control.get(permission, {}).get("group_ids", [])
    if any(g.id in allowed_groups for g in user_groups):
        return True

    # 조직 단위 체크 (상속 포함)
    user_org_units = get_user_org_units_with_ancestors(user_id)
    allowed_org_units = access_control.get(permission, {}).get("org_unit_ids", [])
    if any(ou in allowed_org_units for ou in user_org_units):
        return True

    return False
```

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `MICROSOFT_CLIENT_ID` | Azure AD 앱 클라이언트 ID | - |
| `MICROSOFT_CLIENT_SECRET` | Azure AD 앱 시크릿 | - |
| `MICROSOFT_CLIENT_TENANT_ID` | Azure AD 테넌트 ID | - |
| `ENABLE_OAUTH_ORG_UNIT_MANAGEMENT` | OAuth 로그인 시 자동 조직 배치 | `true` |
