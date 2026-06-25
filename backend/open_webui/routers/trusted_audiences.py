"""
Trusted Audiences admin CRUD router.

외부 IDP (Entra / Google) ID 토큰 passthrough 용 신뢰 audience 관리.
모든 엔드포인트는 admin 전용.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.trusted_audiences import (
    TrustedAudienceForm,
    TrustedAudienceModel,
    TrustedAudiences,
)
from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", "INFO"))

router = APIRouter()


@router.get("/", response_model=list[TrustedAudienceModel])
async def list_trusted_audiences(user=Depends(get_admin_user)):
    return TrustedAudiences.list_all()


@router.post("/", response_model=TrustedAudienceModel)
async def create_trusted_audience(
    form_data: TrustedAudienceForm, user=Depends(get_admin_user)
):
    if not form_data.audience.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="audience is required",
        )
    # 중복 체크 (같은 aud + idp + tenant 조합은 1개만)
    for existing in TrustedAudiences.list_all():
        if (
            existing.audience == form_data.audience.strip()
            and existing.idp_type == form_data.idp_type
            and (existing.tenant_id or "") == (form_data.tenant_id or "").strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This audience is already registered",
            )
    created = TrustedAudiences.insert(form_data)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create trusted audience"),
        )
    return created


@router.get("/{id}", response_model=TrustedAudienceModel)
async def get_trusted_audience(id: str, user=Depends(get_admin_user)):
    row = TrustedAudiences.get_by_id(id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return row


@router.post("/{id}", response_model=TrustedAudienceModel)
async def update_trusted_audience(
    id: str, form_data: TrustedAudienceForm, user=Depends(get_admin_user)
):
    updated = TrustedAudiences.update(id, form_data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return updated


@router.delete("/{id}")
async def delete_trusted_audience(id: str, user=Depends(get_admin_user)):
    ok = TrustedAudiences.delete(id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return {"ok": True}
