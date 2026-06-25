import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.groups import (
    GroupForm,
    GroupResponse,
    Groups,
    GroupUpdateForm,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_admin_users_access, get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

############################
# GetFunctions
############################


@router.get("/", response_model=list[GroupResponse])
async def get_groups(user=Depends(get_verified_user)):
    if user.role == "admin":
        return Groups.get_groups()
    else:
        return Groups.get_groups_by_member_id(user.id)


############################
# CreateNewGroup
############################


@router.post("/create", response_model=Optional[GroupResponse])
async def create_new_group(form_data: GroupForm, user=Depends(get_admin_users_access)):
    try:
        group = Groups.insert_new_group(user.id, form_data)
        if group:
            return group
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error creating group"),
            )
    except Exception as e:
        log.exception(f"Error creating a new group: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


############################
# GetGroupsByIds
############################


class GroupIdsForm(BaseModel):
    ids: list[str]


class GroupNameResponse(BaseModel):
    id: str
    name: str


@router.post("/names", response_model=list[GroupNameResponse])
async def get_groups_by_ids(form_data: GroupIdsForm, user=Depends(get_verified_user)):
    results = []
    for gid in form_data.ids:
        group = Groups.get_group_by_id(gid)
        if group:
            results.append(GroupNameResponse(id=group.id, name=group.name))
    return results


############################
# GetGroupById
############################


@router.get("/id/{id}", response_model=Optional[GroupResponse])
async def get_group_by_id(id: str, user=Depends(get_admin_users_access)):
    group = Groups.get_group_by_id(id)
    if group:
        return group
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# GetGroupMemberEmails (Gmail 수신자 picker — 그룹 → 멤버 이메일 펼침)
############################


class GroupMemberEmail(BaseModel):
    name: str
    email: str


@router.get("/id/{id}/member-emails", response_model=list[GroupMemberEmail])
async def get_group_member_emails(id: str, user=Depends(get_verified_user)):
    """그룹 멤버의 이메일 목록 — Gmail 카드에서 그룹 선택 시 수신자로 펼치는 용도.

    권한: admin 또는 해당 그룹의 멤버만 (본인이 볼 수 있는 그룹의 멤버 주소만 노출).
    이메일 없는 멤버는 제외.
    """
    group = Groups.get_group_by_id(id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    member_ids = group.user_ids or []
    if user.role != "admin" and user.id not in member_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    members = Users.get_users_by_user_ids(member_ids)
    return [
        GroupMemberEmail(name=m.name or m.email, email=m.email)
        for m in members
        if getattr(m, "email", "")
    ]


############################
# UpdateGroupById
############################


@router.post("/id/{id}/update", response_model=Optional[GroupResponse])
async def update_group_by_id(
    id: str, form_data: GroupUpdateForm, user=Depends(get_admin_users_access)
):
    try:
        if form_data.user_ids:
            form_data.user_ids = Users.get_valid_user_ids(form_data.user_ids)

        group = Groups.update_group_by_id(id, form_data)
        if group:
            return group
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating group"),
            )
    except Exception as e:
        log.exception(f"Error updating group {id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


############################
# Group Usage Limit (per-model)
############################


class GroupUsageLimitResponse(BaseModel):
    per_model: dict[str, int] = {}


class GroupUsageLimitForm(BaseModel):
    per_model: dict[str, int] = {}


def _extract_per_model(payload) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    usage_limit = payload.get("usage_limit") or {}
    per_model = usage_limit.get("per_model") if isinstance(usage_limit, dict) else None
    if not isinstance(per_model, dict):
        return {}
    return {str(k): int(v) for k, v in per_model.items() if v is not None}


@router.get("/id/{id}/usage-limit", response_model=GroupUsageLimitResponse)
async def get_group_usage_limit(id: str, user=Depends(get_admin_users_access)):
    group = Groups.get_group_by_id(id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return GroupUsageLimitResponse(per_model=_extract_per_model(group.meta or {}))


@router.post("/id/{id}/usage-limit", response_model=GroupUsageLimitResponse)
async def update_group_usage_limit(
    id: str, form_data: GroupUsageLimitForm, user=Depends(get_admin_users_access)
):
    group = Groups.get_group_by_id(id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    meta = dict(group.meta or {})
    cleaned = {
        str(k): int(v) for k, v in (form_data.per_model or {}).items() if v is not None
    }
    if cleaned:
        meta["usage_limit"] = {"per_model": cleaned}
    else:
        meta.pop("usage_limit", None)

    update_form = GroupUpdateForm(
        name=group.name,
        description=group.description or "",
        permissions=group.permissions,
        user_ids=group.user_ids,
        meta=meta,
    )
    Groups.update_group_by_id(id, update_form)

    return GroupUsageLimitResponse(per_model=cleaned)


############################
# DeleteGroupById
############################


@router.delete("/id/{id}/delete", response_model=bool)
async def delete_group_by_id(id: str, user=Depends(get_admin_users_access)):
    try:
        result = Groups.delete_group_by_id(id)
        if result:
            return result
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting group"),
            )
    except Exception as e:
        log.exception(f"Error deleting group {id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )
