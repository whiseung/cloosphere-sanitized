import json
from typing import Any, Dict, List, Optional

from open_webui.config import DEFAULT_USER_PERMISSIONS
from open_webui.models.groups import Groups
from open_webui.models.organization import OrganizationalUnits
from open_webui.models.users import UserModel, Users

# 권한 레벨 상수: none(0) < access(1) < read(2) < write(3)
PERMISSION_LEVELS: Dict[str, int] = {"none": 0, "access": 1, "read": 2, "write": 3}


def get_permission_level(value: Any) -> int:
    """boolean 또는 string enum 값을 정수 레벨로 변환."""
    if isinstance(value, bool):
        return PERMISSION_LEVELS["write"] if value else PERMISSION_LEVELS["none"]
    return PERMISSION_LEVELS.get(str(value), 0)


def fill_missing_permissions(
    permissions: Dict[str, Any], default_permissions: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Recursively fills in missing properties in the permissions dictionary
    using the default permissions as a template.
    """
    for key, value in default_permissions.items():
        if key not in permissions:
            permissions[key] = value
        elif isinstance(value, dict) and isinstance(
            permissions[key], dict
        ):  # Both are nested dictionaries
            permissions[key] = fill_missing_permissions(permissions[key], value)

    return permissions


def get_user_groups(user_id: str) -> list:
    """
    사용자가 속한 모든 그룹 조회 (직접 멤버 + 조직 단위 기반).
    그룹의 meta.org_unit_ids에 사용자 소속 조직 단위가 포함되면 해당 그룹도 반환.
    """
    direct_groups = Groups.get_groups_by_member_id(user_id)
    direct_group_ids = {g.id for g in direct_groups}

    user_org_unit_ids = get_user_org_unit_ids(user_id, include_ancestors=True)
    if not user_org_unit_ids:
        return direct_groups

    all_groups = Groups.get_groups()
    for group in all_groups:
        if group.id in direct_group_ids:
            continue
        group_org_unit_ids = (group.meta or {}).get("org_unit_ids", [])
        if group_org_unit_ids and any(
            uid in user_org_unit_ids for uid in group_org_unit_ids
        ):
            direct_groups.append(group)

    return direct_groups


def get_permissions(
    user_id: str,
    default_permissions: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get all permissions for a user by combining the permissions of all groups the user is a member of.
    If a permission is defined in multiple groups, the most permissive value is used (True > False).
    Permissions are nested in a dict with the permission key as the key and a boolean/string as the value.
    """

    def combine_permissions(
        permissions: Dict[str, Any], group_permissions: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Combine permissions from multiple groups by taking the most permissive value."""
        if not group_permissions:
            return permissions
        for key, value in group_permissions.items():
            if isinstance(value, dict):
                if key not in permissions:
                    permissions[key] = {}
                permissions[key] = combine_permissions(permissions[key], value)
            elif isinstance(value, str) and value in PERMISSION_LEVELS:
                # string enum: 레벨 비교하여 최대값 선택
                lvl_a = get_permission_level(permissions.get(key, "none"))
                lvl_b = get_permission_level(value)
                max_lvl = max(lvl_a, lvl_b)
                permissions[key] = next(
                    k for k, v in PERMISSION_LEVELS.items() if v == max_lvl
                )
            else:
                if key not in permissions:
                    permissions[key] = value
                else:
                    permissions[key] = (
                        permissions[key] or value
                    )  # Use the most permissive value (True > False)
        return permissions

    user_groups = get_user_groups(user_id)

    # Deep copy default permissions to avoid modifying the original dict
    permissions = json.loads(json.dumps(default_permissions))

    # Combine permissions from all user groups
    for group in user_groups:
        group_permissions = group.permissions or {}
        permissions = combine_permissions(permissions, group_permissions)

    # 1차 fallback: caller가 넘긴 default_permissions로 missing key 보완.
    # (보통 PersistentConfig USER_PERMISSIONS — admin UI "일반 사용자 권한"에서 저장됨)
    permissions = fill_missing_permissions(permissions, default_permissions)

    # 2차 안전망: caller default 자체에 빠진 신규 키를 모듈 상수로 보완.
    # `fill_missing_permissions`는 missing key만 채우므로 1차 결과를 덮어쓰지 않는다.
    # 시나리오: 새 권한 키(workspace.schedules / workspace.tags 등)가 코드에는
    # 추가됐지만 admin이 아직 "일반 사용자 권한"을 한 번도 저장 안 한 환경.
    # USER_PERMISSIONS DB row와 1차 default 둘 다에 키가 없어 client 응답에서
    # 누락되는 회귀를 막는다.
    permissions = fill_missing_permissions(permissions, DEFAULT_USER_PERMISSIONS)

    return permissions


def has_permission(
    user_id: str,
    permission_key: str,
    default_permissions: Dict[str, Any] = {},
) -> bool:
    """
    Check if a user has a specific permission by checking the group permissions
    and fall back to default permissions if not found in any group.

    Permission keys can be hierarchical and separated by dots ('.').
    String enum values: "none" → False, others → True (backward compatible).
    """

    def get_permission(permissions: Optional[Dict[str, Any]], keys: List[str]) -> bool:
        """Traverse permissions dict using a list of keys (from dot-split permission_key)."""
        if not permissions:
            return False
        for key in keys:
            if not isinstance(permissions, dict) or key not in permissions:
                return False  # If any part of the hierarchy is missing, deny access
            permissions = permissions[key]  # Traverse one level deeper

        # 하위 호환: string "none" → False, 그 외 string → True
        if isinstance(permissions, str):
            return permissions != "none"
        return bool(permissions)  # Return the boolean at the final level

    permission_hierarchy = permission_key.split(".")

    # Retrieve user group permissions (직접 멤버 + 조직 단위 기반)
    user_groups = get_user_groups(user_id)

    for group in user_groups:
        group_permissions = group.permissions or {}
        if get_permission(group_permissions, permission_hierarchy):
            return True

    # Check default permissions afterward if the group permissions don't allow it
    default_permissions = fill_missing_permissions(
        default_permissions, DEFAULT_USER_PERMISSIONS
    )
    return get_permission(default_permissions, permission_hierarchy)


def has_permission_min_level(
    user_id: str,
    permission_key: str,
    min_level: str,
    default_permissions: Dict[str, Any] = {},
) -> bool:
    """
    permission_key 위치의 값이 min_level 이상인지 확인.

    Args:
        user_id: 사용자 ID
        permission_key: 점 구분 권한 키 (예: "workspace.knowledge")
        min_level: 최소 요구 레벨 ("access" | "read" | "write")
        default_permissions: 기본 권한 dict
    """
    permissions = get_permissions(user_id, default_permissions)
    keys = permission_key.split(".")
    value = permissions
    for k in keys:
        if not isinstance(value, dict) or k not in value:
            return False
        value = value[k]
    return get_permission_level(value) >= PERMISSION_LEVELS.get(min_level, 0)


def get_org_unit_ancestors(unit_id: str) -> List[str]:
    """
    조직 단위의 모든 상위 조직 단위 ID 목록 조회 (자신 포함)
    계층 구조에서 parent_id를 따라 올라감
    """
    ancestor_ids = [unit_id]
    all_units = OrganizationalUnits.get_all_organizational_units()
    unit_map = {u.id: u for u in all_units}

    current_unit = unit_map.get(unit_id)
    while current_unit and current_unit.parent_id:
        ancestor_ids.append(current_unit.parent_id)
        current_unit = unit_map.get(current_unit.parent_id)

    return ancestor_ids


def get_user_org_unit_ids(user_id: str, include_ancestors: bool = True) -> List[str]:
    """
    사용자가 속한 조직 단위 ID 목록 조회
    member_ids (Azure AD ID) 또는 meta.members의 이메일로 매칭

    Args:
        user_id: 사용자 ID
        include_ancestors: True면 상위 조직 단위도 포함 (권한 상속용)
    """
    user = Users.get_user_by_id(user_id)
    if not user:
        return []

    org_unit_ids = set()
    all_units = OrganizationalUnits.get_all_organizational_units()

    for unit in all_units:
        matched = False

        # 1. member_ids에서 oauth_sub로 매칭
        if user.oauth_sub and unit.member_ids and user.oauth_sub in unit.member_ids:
            matched = True

        # 2. meta.members에서 이메일로 매칭
        if not matched and unit.meta and "members" in unit.meta:
            members = unit.meta.get("members", [])
            member_emails = [
                m.get("email", "").lower() for m in members if m.get("email")
            ]
            if user.email and user.email.lower() in member_emails:
                matched = True

        if matched:
            if include_ancestors:
                # 상위 조직 단위도 포함 (계층 권한 상속)
                org_unit_ids.update(get_org_unit_ancestors(unit.id))
            else:
                org_unit_ids.add(unit.id)

    return list(org_unit_ids)


def search_organization_members(
    user_id: str, query: str, limit: int = 50
) -> list[dict]:
    """요청자가 속한 조직(organization)의 전체 구성원(미가입 포함)을 이름/이메일로 검색.

    ``org_unit.meta.members`` ({id,name,email,job_title}) 가 주 소스이며,
    ``member_ids`` 에만 있는 email 은 보조로 포함(이름은 email 로 대체). 가입
    여부와 무관하게 조직 디렉터리 전체가 대상이다. email(lowercase) 로 dedup.
    멤버 수에 비례하는 추가 DB 조회 없음(org_unit 스캔 + 메모리 필터).

    Returns: ``[{"id": email, "name", "email", "job_title", "profile_image_url": ""}]``
    (미가입자는 user 레코드가 없어 id=email, profile 없음). 조직 멤버십을 못
    찾거나 query 가 비면 ``[]``.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    unit_ids = get_user_org_unit_ids(user_id, include_ancestors=False)
    if not unit_ids:
        return []
    org_ids: set[str] = set()
    for uid in unit_ids:
        unit = OrganizationalUnits.get_organizational_unit_by_id(uid)
        if unit and unit.organization_id:
            org_ids.add(unit.organization_id)
    if not org_ids:
        return []

    members: dict[str, dict] = {}  # email(lower) -> record
    for org_id in org_ids:
        for unit in OrganizationalUnits.get_organizational_units_by_organization_id(
            org_id
        ):
            for m in (unit.meta or {}).get("members", []):
                email = (m.get("email") or "").strip()
                if not email:
                    continue
                key = email.lower()
                if key not in members:
                    members[key] = {
                        "id": email,
                        "name": m.get("name") or email,
                        "email": email,
                        "job_title": m.get("job_title") or "",
                        "profile_image_url": "",
                    }
            for s in unit.member_ids or []:
                if s and "@" in s:
                    key = s.strip().lower()
                    if key not in members:
                        members[key] = {
                            "id": s,
                            "name": s,
                            "email": s,
                            "job_title": "",
                            "profile_image_url": "",
                        }

    matched = [
        r for r in members.values() if q in r["name"].lower() or q in r["email"].lower()
    ]
    matched.sort(key=lambda r: r["name"])
    return matched[:limit]


def has_access(
    user_id: str,
    type: str = "write",
    access_control: Optional[dict] = None,
) -> bool:
    if access_control is None:
        return type == "read"

    # 그룹 체크 (직접 멤버 + 조직 단위 기반)
    user_groups = get_user_groups(user_id)
    user_group_ids = [group.id for group in user_groups]

    # 조직 단위 체크
    user_org_unit_ids = get_user_org_unit_ids(user_id)

    # write 권한은 read를 포함하므로, read 체크 시 write도 함께 확인
    levels_to_check = [type]
    if type == "read":
        levels_to_check.append("write")

    for level in levels_to_check:
        permission_access = access_control.get(level, {})
        permitted_group_ids = permission_access.get("group_ids", [])
        permitted_user_ids = permission_access.get("user_ids", [])
        permitted_org_unit_ids = permission_access.get("org_unit_ids", [])

        # 사용자 ID 직접 매칭
        if user_id in permitted_user_ids:
            return True

        # 그룹 매칭
        if any(group_id in permitted_group_ids for group_id in user_group_ids):
            return True

        # 조직 단위 매칭
        if any(
            org_unit_id in permitted_org_unit_ids for org_unit_id in user_org_unit_ids
        ):
            return True

    return False


# Get all users with access to a resource
def get_users_with_access(
    type: str = "write", access_control: Optional[dict] = None
) -> List[UserModel]:
    if access_control is None:
        return Users.get_users()

    permission_access = access_control.get(type, {})
    permitted_group_ids = permission_access.get("group_ids", [])
    permitted_user_ids = permission_access.get("user_ids", [])
    permitted_org_unit_ids = permission_access.get("org_unit_ids", [])

    user_ids_with_access = set(permitted_user_ids)

    # 그룹에서 사용자 수집
    for group_id in permitted_group_ids:
        group_user_ids = Groups.get_group_user_ids_by_id(group_id)
        if group_user_ids:
            user_ids_with_access.update(group_user_ids)

    # 조직 단위에서 사용자 수집
    for org_unit_id in permitted_org_unit_ids:
        unit = OrganizationalUnits.get_organizational_unit_by_id(org_unit_id)
        if unit:
            # member_ids (Azure AD ID)로 사용자 찾기
            if unit.member_ids:
                for member_id in unit.member_ids:
                    user = Users.get_user_by_oauth_sub(member_id)
                    if user:
                        user_ids_with_access.add(user.id)

            # meta.members의 이메일로 사용자 찾기
            if unit.meta and "members" in unit.meta:
                for member in unit.meta.get("members", []):
                    email = member.get("email")
                    if email:
                        user = Users.get_user_by_email(email.lower())
                        if user:
                            user_ids_with_access.add(user.id)

    return Users.get_users_by_user_ids(list(user_ids_with_access))
