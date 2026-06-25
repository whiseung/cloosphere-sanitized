"""Admin CRUD endpoints for embed widgets.

관리자 전용 위젯 관리 (목록/생성/조회/수정/삭제).
외부 호스트에서 호출되는 공개 엔드포인트는 `embed_widgets_public.py` 참조.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.embed_widgets import (
    EmbedWidgetForm,
    EmbedWidgetModel,
    EmbedWidgets,
    EmbedWidgetUserModel,
)
from open_webui.utils.auth import get_admin_user
from open_webui.utils.license import require_feature

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("embed_widget"))])


############################
# GetEmbedWidgets
############################


@router.get("/", response_model=list[EmbedWidgetUserModel])
async def get_embed_widgets(user=Depends(get_admin_user)):
    """Get all embed widgets (admin only)."""
    return EmbedWidgets.get_widgets()


############################
# CreateEmbedWidget
############################


@router.post("/create", response_model=Optional[EmbedWidgetModel])
async def create_embed_widget(form_data: EmbedWidgetForm, user=Depends(get_admin_user)):
    """Create a new embed widget (admin only)."""
    widget = EmbedWidgets.insert_new_widget(user.id, form_data)

    if widget:
        return widget
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating embed widget"),
        )


############################
# GetEmbedWidgetById
############################


@router.get("/id/{id}", response_model=Optional[EmbedWidgetModel])
async def get_embed_widget_by_id(id: str, user=Depends(get_admin_user)):
    """Get an embed widget by ID (admin only)."""
    widget = EmbedWidgets.get_widget_by_id(id)

    if widget:
        return widget

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# UpdateEmbedWidgetById
############################


@router.post("/id/{id}/update", response_model=Optional[EmbedWidgetModel])
async def update_embed_widget_by_id(
    id: str, form_data: EmbedWidgetForm, user=Depends(get_admin_user)
):
    """Update an embed widget by ID (admin only)."""
    widget = EmbedWidgets.get_widget_by_id(id)

    if not widget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    updated = EmbedWidgets.update_widget_by_id(id, form_data)

    if updated:
        return updated
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating embed widget"),
        )


############################
# DeleteEmbedWidgetById
############################


@router.delete("/id/{id}/delete", response_model=bool)
async def delete_embed_widget_by_id(id: str, user=Depends(get_admin_user)):
    """Delete an embed widget by ID (admin only)."""
    widget = EmbedWidgets.get_widget_by_id(id)

    if not widget:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    result = EmbedWidgets.delete_widget_by_id(id)

    if result:
        return True
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting embed widget"),
        )
