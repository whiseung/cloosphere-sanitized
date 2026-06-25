import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.workspace_tags import (
    WorkspaceTagAssignForm,
    WorkspaceTagForm,
    WorkspaceTagModel,
    WorkspaceTags,
)
from open_webui.utils.access_control import has_permission_min_level
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

VALID_RESOURCE_TYPES = {
    "agent",
    "knowledge",
    "guardrail",
    "prompt",
    "tool",
    "flow",
    "database",
    "glossary",
}


############################
# GetAllTags
############################


@router.get("/", response_model=list[WorkspaceTagModel])
async def get_all_tags(request: Request, user=Depends(get_verified_user)):
    # 태그 조회는 read 이상 (none 으로 막힌 사용자는 태그 풀 자체 비노출)
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.tags",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return WorkspaceTags.get_all_tags()


############################
# CreateTag
############################


@router.post("/create", response_model=WorkspaceTagModel)
async def create_tag(
    request: Request,
    form_data: WorkspaceTagForm,
    user=Depends(get_verified_user),
):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.tags",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if not form_data.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tag name is required",
        )

    tag = WorkspaceTags.create_tag(user.id, form_data)
    if tag:
        return tag
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Failed to create tag"),
    )


############################
# UpdateTag
############################


@router.post("/{id}/update", response_model=WorkspaceTagModel)
async def update_tag(
    id: str,
    request: Request,
    form_data: WorkspaceTagForm,
    user=Depends(get_verified_user),
):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.tags",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    tag = WorkspaceTags.get_tag_by_id(id)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Only admin or creator can update
    if user.role != "admin" and tag.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if not form_data.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tag name is required",
        )

    updated = WorkspaceTags.update_tag(id, form_data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tag with this name already exists",
        )
    return updated


############################
# DeleteTag
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_tag(id: str, request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.tags",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    tag = WorkspaceTags.get_tag_by_id(id)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Only admin or creator can delete
    if user.role != "admin" and tag.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    return WorkspaceTags.delete_tag(id)


############################
# GetTagsByResource
############################


@router.get(
    "/resource/{resource_type}/{resource_id}",
    response_model=list[WorkspaceTagModel],
)
async def get_tags_by_resource(
    resource_type: str,
    resource_id: str,
    user=Depends(get_verified_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource type: {resource_type}",
        )
    return WorkspaceTags.get_tags_by_resource(resource_type, resource_id)


############################
# AssignTag
############################


@router.post(
    "/resource/{resource_type}/{resource_id}/assign",
    response_model=list[WorkspaceTagModel],
)
async def assign_tag(
    resource_type: str,
    resource_id: str,
    form_data: WorkspaceTagAssignForm,
    user=Depends(get_verified_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource type: {resource_type}",
        )

    WorkspaceTags.assign_tag(
        tag_id=form_data.tag_id,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user.id,
    )

    return WorkspaceTags.get_tags_by_resource(resource_type, resource_id)


############################
# UnassignTag
############################


@router.delete(
    "/resource/{resource_type}/{resource_id}/unassign/{tag_id}",
    response_model=list[WorkspaceTagModel],
)
async def unassign_tag(
    resource_type: str,
    resource_id: str,
    tag_id: str,
    user=Depends(get_verified_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource type: {resource_type}",
        )

    WorkspaceTags.unassign_tag(
        tag_id=tag_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )

    return WorkspaceTags.get_tags_by_resource(resource_type, resource_id)


############################
# GetAllAssignmentsByType (for list filtering)
############################


@router.get("/assignments/{resource_type}")
async def get_all_assignments_by_type(
    resource_type: str,
    user=Depends(get_verified_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource type: {resource_type}",
        )
    return WorkspaceTags.get_all_assignments_by_type(resource_type)
