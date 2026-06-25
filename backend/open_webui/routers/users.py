import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.auths import Auths
from open_webui.models.chats import Chats
from open_webui.models.groups import Groups
from open_webui.models.users import (
    UserModel,
    UserResponse,
    UserRoleUpdateForm,
    Users,
    UserSettings,
    UserUpdateForm,
)
from open_webui.socket.main import get_active_status_by_user_id
from open_webui.utils.access_control import (
    get_permissions,
    search_organization_members,
)
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import (
    get_admin_users_read_access,
    get_admin_users_write_access,
    get_password_hash,
    get_verified_user,
)
from pydantic import BaseModel

PermissionLevel = Literal["none", "access", "read", "write"]


class OrgMemberResponse(BaseModel):
    id: str
    name: str
    email: str
    job_title: str = ""
    profile_image_url: str = ""


def normalize_permission_level(value) -> str:
    """Convert legacy boolean permission values to PermissionLevel strings."""
    if isinstance(value, bool):
        return "write" if value else "none"
    if value in ("none", "access", "read", "write"):
        return value
    return "none"


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

############################
# GetUsers
############################


@router.get("/", response_model=list[UserModel])
async def get_users(
    skip: Optional[int] = None,
    limit: Optional[int] = None,
    user=Depends(get_admin_users_read_access),
):
    return Users.get_users(skip, limit)


############################
# SearchUsers (any verified user)
############################


@router.get("/search", response_model=list[UserResponse])
async def search_users(
    q: str = "",
    limit: int = 50,
    user=Depends(get_verified_user),
):
    if not q.strip():
        return []
    return Users.search_users(q.strip(), min(limit, 50))


@router.get("/search/organization-members", response_model=list[OrgMemberResponse])
async def search_organization_members_route(
    q: str = "",
    limit: int = 50,
    user=Depends(get_verified_user),
):
    if not q.strip():
        return []
    return search_organization_members(user.id, q.strip(), min(limit, 50))


############################
# User Groups
############################


@router.get("/groups")
async def get_user_groups(user=Depends(get_verified_user)):
    return Groups.get_groups_by_member_id(user.id)


############################
# User Permissions
############################


@router.get("/permissions")
async def get_user_permissisions(request: Request, user=Depends(get_verified_user)):
    user_permissions = get_permissions(
        user.id, request.app.state.config.USER_PERMISSIONS
    )

    return user_permissions


############################
# User Default Permissions
############################


class AdminPermissions(BaseModel):
    users: PermissionLevel = "none"
    evaluations: PermissionLevel = "none"
    functions: PermissionLevel = "none"
    settings: PermissionLevel = "none"
    monitoring: PermissionLevel = "none"


class WorkspacePermissions(BaseModel):
    agents: PermissionLevel = "none"
    knowledge: PermissionLevel = "none"
    prompts: PermissionLevel = "none"
    tools: PermissionLevel = "none"
    databases: PermissionLevel = "none"
    glossaries: PermissionLevel = "none"
    knowledge_graphs: PermissionLevel = "none"
    guardrails: PermissionLevel = "none"
    agent_flows: PermissionLevel = "none"
    schedules: PermissionLevel = "none"
    tags: PermissionLevel = "none"
    marketplace: PermissionLevel = "none"


class SharingPermissions(BaseModel):
    public_agents: bool = True
    public_knowledge: bool = True
    public_prompts: bool = True
    public_tools: bool = True


class ChatPermissions(BaseModel):
    controls: bool = True
    file_upload: bool = True
    delete: bool = True
    edit: bool = True
    stt: bool = True
    tts: bool = True
    call: bool = True
    multiple_models: bool = True
    temporary: bool = True
    temporary_enforced: bool = False


class FeaturesPermissions(BaseModel):
    direct_tool_servers: bool = False
    web_search: bool = True
    image_generation: bool = True
    code_interpreter: bool = True


class UserPermissions(BaseModel):
    admin: AdminPermissions = AdminPermissions()
    workspace: WorkspacePermissions = WorkspacePermissions()
    sharing: SharingPermissions = SharingPermissions()
    chat: ChatPermissions = ChatPermissions()
    features: FeaturesPermissions = FeaturesPermissions()


@router.get("/default/permissions", response_model=UserPermissions)
async def get_default_user_permissions(
    request: Request, user=Depends(get_admin_users_read_access)
):
    perms = request.app.state.config.USER_PERMISSIONS
    return {
        "admin": AdminPermissions(
            **{
                k: normalize_permission_level(v)
                for k, v in perms.get("admin", {}).items()
                if k in AdminPermissions.model_fields
            }
        ),
        "workspace": WorkspacePermissions(
            **{
                k: normalize_permission_level(v)
                for k, v in perms.get("workspace", {}).items()
                if k in WorkspacePermissions.model_fields
            }
        ),
        "sharing": SharingPermissions(**perms.get("sharing", {})),
        "chat": ChatPermissions(**perms.get("chat", {})),
        "features": FeaturesPermissions(**perms.get("features", {})),
    }


@router.post("/default/permissions")
async def update_default_user_permissions(
    request: Request,
    form_data: UserPermissions,
    user=Depends(get_admin_users_write_access),
):
    request.app.state.config.USER_PERMISSIONS = form_data.model_dump()
    return request.app.state.config.USER_PERMISSIONS


############################
# UpdateUserRole
############################


@router.post("/update/role", response_model=Optional[UserModel])
async def update_user_role(
    form_data: UserRoleUpdateForm, user=Depends(get_admin_users_write_access)
):
    if user.id != form_data.id and form_data.id != Users.get_first_user().id:
        target_user = Users.get_user_by_id(form_data.id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.USER_NOT_FOUND,
            )

        before_role = target_user.role
        updated_user = Users.update_user_role_by_id(form_data.id, form_data.role)

        if updated_user and before_role != form_data.role:
            AuditLogger.log_role_change(
                user_id=form_data.id,
                before_role=before_role,
                after_role=form_data.role,
                user_name=target_user.name,
                user_email=target_user.email,
            )

        return updated_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ERROR_MESSAGES.ACTION_PROHIBITED,
    )


############################
# GetUserSettingsBySessionUser
############################


@router.get("/user/settings", response_model=Optional[UserSettings])
async def get_user_settings_by_session_user(user=Depends(get_verified_user)):
    user = Users.get_user_by_id(user.id)
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserSettingsBySessionUser
############################


@router.post("/user/settings/update", response_model=UserSettings)
async def update_user_settings_by_session_user(
    form_data: UserSettings, user=Depends(get_verified_user)
):
    user = Users.update_user_settings_by_id(user.id, form_data.model_dump())
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserInfoBySessionUser
############################


@router.get("/user/info", response_model=Optional[dict])
async def get_user_info_by_session_user(user=Depends(get_verified_user)):
    user = Users.get_user_by_id(user.id)
    if user:
        return user.info
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserInfoBySessionUser
############################


@router.post("/user/info/update", response_model=Optional[dict])
async def update_user_info_by_session_user(
    form_data: dict, user=Depends(get_verified_user)
):
    user = Users.get_user_by_id(user.id)
    if user:
        if user.info is None:
            user.info = {}

        user = Users.update_user_by_id(user.id, {"info": {**user.info, **form_data}})
        if user:
            return user.info
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.USER_NOT_FOUND,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# CheckUserUsageLimit (self)
############################


class UsageLimitCheckResponse(BaseModel):
    allowed: bool
    action: str
    daily_limit: int
    daily_used: int
    message: str
    model_id: Optional[str] = None
    pct: float = 0.0
    source: str = ""


@router.get("/user/usage-limit/check", response_model=UsageLimitCheckResponse)
async def check_user_usage_limit(
    request: Request,
    model_id: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """현재 사용자 한도 체크 (per-model).

    model_id 미지정 시 enabled/admin 만 검사 (legacy 호환).
    """
    from open_webui.utils.usage_limit import enforce_usage_limit

    result = enforce_usage_limit(request, user.id, user.role, model_id)
    return UsageLimitCheckResponse(
        allowed=result.allowed,
        action=result.action,
        daily_limit=result.daily_limit,
        daily_used=result.daily_used,
        message=result.message,
        model_id=result.model_id,
        pct=result.pct,
        source=result.source,
    )


############################
# GetUserById
############################


class UserResponse(BaseModel):
    name: str
    profile_image_url: str
    active: Optional[bool] = None


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(user_id: str, user=Depends(get_verified_user)):
    # Check if user_id is a shared chat
    # If it is, get the user_id from the chat
    if user_id.startswith("shared-"):
        chat_id = user_id.replace("shared-", "")
        chat = Chats.get_chat_by_id(chat_id)
        if chat:
            user_id = chat.user_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.USER_NOT_FOUND,
            )

    user = Users.get_user_by_id(user_id)

    if user:
        return UserResponse(
            **{
                "name": user.name,
                "profile_image_url": user.profile_image_url,
                "active": get_active_status_by_user_id(user_id),
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserById
############################


@router.post("/{user_id}/update", response_model=Optional[UserModel])
async def update_user_by_id(
    user_id: str,
    form_data: UserUpdateForm,
    session_user=Depends(get_admin_users_write_access),
):
    user = Users.get_user_by_id(user_id)

    if user:
        if form_data.email.lower() != user.email:
            email_user = Users.get_user_by_email(form_data.email.lower())
            if email_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.EMAIL_TAKEN,
                )

        if form_data.password:
            hashed = get_password_hash(form_data.password)
            log.debug(f"hashed: {hashed}")
            if not Auths.update_user_password_by_id(user_id, hashed):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Error updating password"),
                )

        Auths.update_email_by_id(user_id, form_data.email.lower())

        update_data = {
            "name": form_data.name,
            "email": form_data.email.lower(),
            "profile_image_url": form_data.profile_image_url,
        }

        # Update role if provided (and not self-update)
        if form_data.role and user_id != session_user.id:
            update_data["role"] = form_data.role

        updated_user = Users.update_user_by_id(user_id, update_data)

        if updated_user:
            return updated_user

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.USER_NOT_FOUND,
    )


############################
# GetUserUsageLimit
############################


class UsageLimitResponse(BaseModel):
    """per-model 한도 응답.

    per_model: {model_id: tokens} — 사용자가 명시적으로 설정한 모델별 한도.
                                    누락 키 = 상속 (전역값 따름).
    daily_used: 사용자의 모든 모델 합계 (요약용).
    """

    per_model: dict[str, int] = {}
    daily_used: int = 0


############################
# GetUserOrganizationalUnits
############################


@router.get("/{user_id}/organizational-units")
async def get_user_organizational_units(
    user_id: str, user=Depends(get_admin_users_read_access)
):
    from open_webui.models.organization import (
        OrganizationalUnitModel,
        OrganizationalUnits,
        Organizations,
    )
    from open_webui.utils.access_control import get_user_org_unit_ids

    target_user = Users.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )

    unit_ids = get_user_org_unit_ids(user_id, include_ancestors=False)
    if not unit_ids:
        return []

    all_units = OrganizationalUnits.get_all_organizational_units()
    unit_map = {u.id: u for u in all_units}

    org_cache: dict[str, Optional[str]] = {}

    def get_org_display(org_id: str) -> Optional[str]:
        if org_id in org_cache:
            return org_cache[org_id]
        org = Organizations.get_organization_by_id(org_id)
        org_cache[org_id] = (org.display_name or org.name) if org else None
        return org_cache[org_id]

    result = []
    for uid in unit_ids:
        unit = unit_map.get(uid)
        if not unit:
            continue
        result.append(
            {
                **OrganizationalUnitModel.model_validate(unit).model_dump(),
                "organization_name": get_org_display(unit.organization_id),
            }
        )

    result.sort(
        key=lambda u: ((u.get("organization_name") or ""), u["level"], u["name"])
    )
    return result


def _extract_per_model_from_payload(payload) -> dict[str, int]:
    """JSON dict 에서 usage_limit.per_model 부분만 추출 (없으면 빈 dict)."""
    if not isinstance(payload, dict):
        return {}
    usage_limit = payload.get("usage_limit") or {}
    per_model = usage_limit.get("per_model") if isinstance(usage_limit, dict) else None
    if not isinstance(per_model, dict):
        return {}
    return {str(k): int(v) for k, v in per_model.items() if v is not None}


@router.get("/{user_id}/usage-limit", response_model=UsageLimitResponse)
async def get_user_usage_limit(user_id: str, user=Depends(get_admin_users_read_access)):
    from open_webui.models.usage import Usages
    from open_webui.models.users import Users

    target_user = Users.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )

    per_model = _extract_per_model_from_payload(target_user.info or {})
    daily_used = Usages.get_user_daily_token_usage(user_id)

    return UsageLimitResponse(per_model=per_model, daily_used=daily_used)


############################
# UpdateUserUsageLimit
############################


class UsageLimitUpdateForm(BaseModel):
    """per_model dict 으로 한도 업데이트.

    빈 dict → 사용자의 모든 per-model override 제거 (= 전역값 상속).
    """

    per_model: dict[str, int] = {}


@router.post("/{user_id}/usage-limit", response_model=UsageLimitResponse)
async def update_user_usage_limit(
    user_id: str,
    form_data: UsageLimitUpdateForm,
    user=Depends(get_admin_users_write_access),
):
    from open_webui.models.usage import Usages
    from open_webui.models.users import Users

    target_user = Users.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )

    info = target_user.info or {}
    cleaned = {
        str(k): int(v) for k, v in (form_data.per_model or {}).items() if v is not None
    }
    if cleaned:
        info["usage_limit"] = {"per_model": cleaned}
    else:
        # 빈 dict = 모든 override 해제 → usage_limit 키 자체 제거 (legacy daily_tokens 도 함께 정리)
        info.pop("usage_limit", None)
    Users.update_user_by_id(user_id, {"info": info})

    daily_used = Usages.get_user_daily_token_usage(user_id)

    return UsageLimitResponse(per_model=cleaned, daily_used=daily_used)


############################
# Per-User Usage by Model (모니터링 보조)
############################


class UsageByModelEntry(BaseModel):
    model_id: str
    name: str
    used: int
    limit: int  # 0 = 무제한 / 한도 없음
    source: str  # "global:default" | "global:per_model" | "user" | "group:..." | "org:..." | "none"
    is_agent: bool


@router.get("/{user_id}/usage-by-model", response_model=list[UsageByModelEntry])
async def get_user_usage_by_model(
    user_id: str,
    request: Request,
    period: str = "today",  # today | week | month
    user=Depends(get_admin_users_read_access),
):
    """주어진 사용자의 모델별 토큰 사용량 (period 합계) + 일일 한도.

    카탈로그: `get_all_models()` 결과 중 **base LLM 만** (워크스페이스
    agent 는 제외). agent 호출도 base 모델 사용량으로 자동 합산되므로
    base 단위로 보면 사용자의 실 토큰 소비를 정확히 파악 가능.

    - `today`: UTC 자정 이후
    - `week`: 7일 전 이후
    - `month`: 30일 전 이후
    한도(`limit`) 는 항상 일일 효과한도 — 4계층 max boost
    (`get_effective_daily_limit_for_model`).
    """
    from datetime import datetime, timezone

    from open_webui.main import get_all_models
    from open_webui.models.models import Models
    from open_webui.models.usage import (
        USER_QUOTA_MESSAGE_TYPES,
        Usages,
        get_today_start_ts,
    )
    from open_webui.models.users import Users
    from open_webui.utils.usage_limit import (
        collect_user_quota_layers,
        resolve_limit_from_layers,
    )

    target_user = Users.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )

    now = datetime.now(timezone.utc)
    if period == "week":
        since_ts = int(now.timestamp()) - 7 * 24 * 3600
    elif period == "month":
        since_ts = int(now.timestamp()) - 30 * 24 * 3600
    else:  # today (default) — KST 자정 기준
        since_ts = get_today_start_ts()

    # 1) usage 한 번에 GROUP BY model_id (모델별 SUM 쿼리 N → 1)
    used_by_model = Usages.get_user_token_usage_by_model_since(
        user_id, since_ts, message_types=USER_QUOTA_MESSAGE_TYPES
    )

    # 2) Models 테이블 한 번에 fetch — agent 행 검출용 (개별 get_model_by_id N → 1)
    db_rows_by_id = {m.id: m for m in Models.get_models()}

    # 3) limit 계층 한 번 모음 (today 만 — week/month 는 limit 표시 안 함)
    if period == "today":
        layers = collect_user_quota_layers(request, user_id)
    else:
        layers = None

    # 카탈로그 = chat 에서 보이는 모든 모델 (connections 기반 base LLM 포함)
    catalog = await get_all_models(request, user=target_user)

    seen_ids: set[str] = set()
    out: list[UsageByModelEntry] = []
    for m in catalog or []:
        mid = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
        if not mid or mid in seen_ids:
            continue
        seen_ids.add(mid)

        # Filter pipelines 등 제외 (chat 호출 대상이 아님)
        if isinstance(m, dict) and m.get("pipeline", {}).get("type") == "filter":
            continue

        # agent 제외: Model 테이블에 row 가 있고 base_model_id 가 있으면 agent → skip
        db_row = db_rows_by_id.get(mid)
        if db_row is not None and getattr(db_row, "base_model_id", None):
            continue

        used = used_by_model.get(mid, 0)
        if layers is not None:
            limit, source = resolve_limit_from_layers(layers, mid)
        else:
            limit, source = 0, ""

        # 신호 없는 행 (사용도 한도도 없음) 스킵
        if used == 0 and limit == 0:
            continue

        name = (m.get("name") if isinstance(m, dict) else getattr(m, "name", None)) or (
            db_row.name if db_row else mid
        )

        out.append(
            UsageByModelEntry(
                model_id=mid,
                name=name,
                used=used,
                limit=limit,
                source=source,
                is_agent=False,
            )
        )
    out.sort(key=lambda e: e.used, reverse=True)
    return out


############################
# DeleteUserById
############################


@router.delete("/{user_id}", response_model=bool)
async def delete_user_by_id(user_id: str, user=Depends(get_admin_users_write_access)):
    if user.id != user_id:
        result = Auths.delete_auth_by_id(user_id)

        if result:
            return True

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DELETE_USER_ERROR,
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ERROR_MESSAGES.ACTION_PROHIBITED,
    )
