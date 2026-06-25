---
paths:
  - "backend/open_webui/routers/organizations.py"
  - "backend/open_webui/routers/groups.py"
  - "backend/open_webui/models/organization.py"
  - "backend/open_webui/models/groups.py"
  - "backend/open_webui/services/organization_providers/**/*.py"
  - "src/lib/components/admin/Users/Organizations.svelte"
  - "src/lib/components/admin/Users/Groups*.svelte"
---

# 조직/그룹 관리 규칙

## Organizations 라우터 (routers/organizations.py)
- `/`: GET 조직 목록, POST 생성 (admin)
- `/{id}`: GET/POST/DELETE 단일 관리
- `/{id}/sync`: POST MS Graph 동기화
- `/{id}/units`: GET 조직 단위 (부서) 목록

## Groups 라우터 (routers/groups.py)
- `/`: GET 그룹 목록, POST 생성 (admin)
- `/{id}`: GET/POST/DELETE 단일 관리
- `/{id}/members`: POST 멤버 추가/제거
- `user_ids` JSON 배열로 멤버 관리
- `permissions` JSON으로 그룹별 권한 설정

## Organization 모델
```python
class Organization(Base):
    __tablename__ = "organization"
    id, user_id, name, description
    data(JSON), meta(JSON)
    created_at, updated_at
```

## Group 모델
```python
class Group(Base):
    __tablename__ = "group"
    id, user_id, name, description
    data(JSON), meta(JSON)
    permissions(JSON), user_ids(JSON)
    created_at, updated_at
```
- `user_ids`: 멤버 사용자 ID 배열
- `permissions`: 그룹별 권한 (workspace, sharing, chat, features, admin)

## 조직 프로바이더 (services/organization_providers/)
- `base.py`: OrganizationProvider ABC
- `json_provider.py`: JSON 기반 수동 관리
- `msgraph_provider.py`: MS Graph API 연동 (Azure AD 동기화)

## 접근 제어 통합
- `access_control.org_unit_ids`: 조직 단위 기반 접근 제어
- `get_user_org_unit_ids()`: 사용자 소속 조직 단위 조회 (조상 포함)

## 참조 파일
- `routers/organizations.py`, `routers/groups.py`
- `models/organization.py`, `models/groups.py`
- `services/organization_providers/msgraph_provider.py`
- `utils/access_control.py`: 조직/그룹 권한 검사
