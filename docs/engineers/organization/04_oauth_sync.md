# OAuth 로그인 시 자동 조직 배치

## 개요

사용자가 Microsoft OAuth로 로그인할 때 자동으로 조직 단위에 배치되는 기능입니다. 관리자가 매번 수동으로 조직 구조를 동기화하지 않아도, 사용자의 부서 정보를 기반으로 자동 배치됩니다.

## 동작 방식

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  사용자         │      │  Cloosphere     │      │  Microsoft      │
│  (브라우저)     │      │  Backend        │      │  Graph API      │
└────────┬────────┘      └────────┬────────┘      └────────┬────────┘
         │                        │                        │
         │  1. Microsoft 로그인   │                        │
         │───────────────────────▶│                        │
         │                        │  2. /me 호출           │
         │                        │───────────────────────▶│
         │                        │                        │
         │                        │◀───────────────────────│
         │                        │  3. department 반환    │
         │                        │                        │
         │                        │  4. 조직 단위 검색     │
         │                        │     (department 매칭)  │
         │                        │                        │
         │                        │  5. member_ids에 추가  │
         │                        │                        │
         │◀───────────────────────│                        │
         │  6. 로그인 완료        │                        │
         │     (조직 배치 완료)   │                        │
         │                        │                        │
```

## 상세 흐름

### 1. Microsoft Graph API 호출

OAuth 콜백에서 사용자 상세 정보 조회:

```python
# backend/open_webui/utils/oauth.py - handle_callback()

if provider == "microsoft":
    access_token = token.get("access_token")
    if access_token:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with aiohttp.ClientSession() as session:
            # 사용자 상세 정보 조회
            async with session.get(
                "https://graph.microsoft.com/v1.0/me",
                headers=headers,
                params={
                    "$select": "id,displayName,jobTitle,department,companyName,officeLocation"
                },
            ) as resp:
                if resp.ok:
                    ms_user_details = await resp.json()
```

**응답 예시:**

```json
{
  "id": "87654321-4321-4321-4321-210987654321",
  "displayName": "홍길동",
  "jobTitle": "Software Engineer",
  "department": "개발팀",
  "companyName": "Contoso",
  "officeLocation": "서울"
}
```

### 2. 조직 단위 매칭

`department` 필드와 일치하는 조직 단위를 찾습니다:

```python
# backend/open_webui/utils/oauth.py - update_user_org_units()

def update_user_org_units(self, user, ms_user_details: dict):
    department = ms_user_details.get("department")  # "개발팀"
    ms_user_id = ms_user_details.get("id")          # Azure AD Object ID

    if not department:
        return  # 부서 정보 없으면 스킵

    # 모든 조직 단위에서 이름 매칭
    all_units = OrganizationalUnits.get_all_organizational_units()
    target_unit = None

    for unit in all_units:
        unit_name = unit.display_name or unit.name
        if unit_name == department or unit.name == department:
            target_unit = unit
            break
```

### 3. 멤버십 업데이트

```python
    # 이미 해당 조직 단위에 속해 있으면 스킵
    user_identifier = user.oauth_sub or user.email
    if user_identifier in (target_unit.member_ids or []):
        return

    # 같은 조직 내 다른 단위에서 제거 (부서 이동 시)
    for unit in all_units:
        if unit.organization_id == target_unit.organization_id:
            if user_identifier in (unit.member_ids or []):
                updated_members = [m for m in unit.member_ids if m != user_identifier]
                OrganizationalUnits.update_organizational_unit_by_id(
                    unit.id,
                    OrganizationalUnitUpdateForm(member_ids=updated_members)
                )

    # 새 조직 단위에 추가
    new_member_ids = (target_unit.member_ids or []) + [user_identifier]
    OrganizationalUnits.update_organizational_unit_by_id(
        target_unit.id,
        OrganizationalUnitUpdateForm(member_ids=new_member_ids)
    )
```

### 4. 조건부 실행

환경 변수로 기능 활성화/비활성화:

```python
# backend/open_webui/utils/oauth.py - handle_callback()

if (provider == "microsoft" and
    ms_user_details and
    auth_manager_config.ENABLE_OAUTH_ORG_UNIT_MANAGEMENT):
    try:
        self.update_user_org_units(user=user, ms_user_details=ms_user_details)
    except Exception as e:
        log.warning(f"Failed to update user org units: {e}")
```

## 환경 변수

```env
# 기능 활성화 (기본값: true)
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true
```

**config.py 정의:**

```python
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT = PersistentConfig(
    "ENABLE_OAUTH_ORG_UNIT_MANAGEMENT",
    "oauth.enable_org_unit_mapping",
    os.environ.get("ENABLE_OAUTH_ORG_UNIT_MANAGEMENT", "True").lower() == "true",
)
```

## 사전 요구사항

### 1. 조직 구조 먼저 동기화

이 기능이 작동하려면 조직 단위가 미리 DB에 존재해야 합니다:

1. 관리자 페이지 → 사용자 → 조직 → 동기화
2. MS Graph 선택 → **Departments** 옵션 활성화
3. 동기화 실행

### 2. 부서 이름 일치

Azure AD 사용자의 `department` 필드와 Cloosphere 조직 단위의 `name` 또는 `display_name`이 정확히 일치해야 합니다.

```
Azure AD 사용자:
  department: "개발팀"

Cloosphere 조직 단위:
  name: "Engineering"
  display_name: "개발팀"  ← 매칭됨
```

## 로그 확인

성공 시:

```
INFO: Updating org unit membership for user hong@contoso.com, department: 개발팀
INFO: Added user hong@contoso.com to org unit Engineering
```

부서 이동 시:

```
INFO: Updating org unit membership for user hong@contoso.com, department: 기획팀
INFO: Removed user hong@contoso.com from org unit Engineering
INFO: Added user hong@contoso.com to org unit Planning
```

부서 정보 없을 시:

```
DEBUG: User hong@contoso.com has no department info, skipping org unit update
```

매칭 실패 시:

```
DEBUG: No matching org unit found for department: 새로운팀
```

## 제한 사항 및 주의점

### 1. 이름 기반 매칭

- 부서 이름이 정확히 일치해야 매칭됨
- 대소문자 구분함
- 향후 `external_id` 기반 매칭 지원 예정

### 2. 단일 조직 가정

- 현재는 같은 `organization_id` 내에서만 부서 이동 처리
- 멀티 조직 시나리오는 추가 개발 필요

### 3. 에러 처리

- 조직 단위 업데이트 실패해도 로그인은 성공
- 에러는 경고 로그로만 기록 (사용자 경험 우선)

```python
try:
    self.update_user_org_units(...)
except Exception as e:
    log.warning(f"Failed to update user org units: {e}")
    # 로그인 프로세스는 계속 진행
```

## 트러블슈팅

### 자동 배치가 안 됨

1. **환경 변수 확인**
   ```bash
   echo $ENABLE_OAUTH_ORG_UNIT_MANAGEMENT  # true 여야 함
   ```

2. **조직 단위 존재 여부 확인**
   - 관리자 페이지에서 조직 동기화 먼저 실행

3. **부서 이름 확인**
   - Azure Portal → 사용자 → 부서 필드 확인
   - Cloosphere 조직 단위 이름과 비교

4. **로그 확인**
   ```bash
   docker logs open-webui 2>&1 | grep -i "org unit"
   ```

### 권한이 적용 안 됨

1. **리소스에 조직 단위 권한 할당 확인**
   - 워크스페이스 → 리소스 → 접근 제어에서 조직 단위 선택

2. **멤버십 확인**
   - 관리자 페이지 → 조직 → 조직 단위 → 멤버 버튼으로 확인

3. **재로그인**
   - 권한 변경 후 사용자 재로그인 필요할 수 있음
