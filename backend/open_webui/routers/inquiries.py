import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.inquiry import (
    INQUIRY_TYPES,
    Inquiries,
    InquiryForm,
    InquiryModel,
    InquiryResponse,
    InquiryUpdateForm,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_admin_user, get_verified_user

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# Get Inquiry Types
############################


@router.get("/types")
async def get_inquiry_types():
    return INQUIRY_TYPES


############################
# Create Inquiry (any user)
############################


@router.post("/", response_model=InquiryModel)
async def create_inquiry(
    form_data: InquiryForm,
    user=Depends(get_verified_user),
):
    if form_data.type not in INQUIRY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid inquiry type",
        )

    valid_subtypes = INQUIRY_TYPES[form_data.type]["subtypes"]
    if form_data.subtype not in valid_subtypes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid inquiry subtype",
        )

    inquiry = Inquiries.insert_new_inquiry(user.id, form_data)
    if inquiry:
        return inquiry

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error creating inquiry"),
    )


############################
# Get My Inquiries (any user)
############################


@router.get("/me", response_model=list[InquiryModel])
async def get_my_inquiries(user=Depends(get_verified_user)):
    return Inquiries.get_inquiries_by_user_id(user.id)


############################
# Get All Inquiries (admin)
############################


@router.get("/list", response_model=list[InquiryResponse])
async def get_all_inquiries(
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    user=Depends(get_admin_user),
):
    inquiries = Inquiries.get_inquiries(status=status_filter, type=type_filter)

    # Attach user info
    user_ids = list(set(i.user_id for i in inquiries))
    users_map = {}
    for uid in user_ids:
        u = Users.get_user_by_id(uid)
        if u:
            users_map[uid] = {"name": u.name, "email": u.email}

    return [
        InquiryResponse(
            **i.model_dump(),
            user_name=users_map.get(i.user_id, {}).get("name"),
            user_email=users_map.get(i.user_id, {}).get("email"),
        )
        for i in inquiries
    ]


############################
# Get Inquiry Stats (admin)
############################


@router.get("/stats")
async def get_inquiry_stats(user=Depends(get_admin_user)):
    return Inquiries.get_inquiry_count_by_status()


############################
# Close Inquiry (owner)
############################


@router.post("/{inquiry_id}/close", response_model=InquiryModel)
async def close_inquiry(
    inquiry_id: str,
    user=Depends(get_verified_user),
):
    inquiry = Inquiries.get_inquiry_by_id(inquiry_id)
    if not inquiry or inquiry.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    result = Inquiries.update_inquiry_by_id(
        inquiry_id, InquiryUpdateForm(status="closed")
    )
    if result:
        return result

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error closing inquiry"),
    )


############################
# Update Inquiry (admin)
############################


@router.post("/{inquiry_id}", response_model=InquiryModel)
async def update_inquiry(
    inquiry_id: str,
    form_data: InquiryUpdateForm,
    user=Depends(get_admin_user),
):
    inquiry = Inquiries.update_inquiry_by_id(inquiry_id, form_data)
    if inquiry:
        return inquiry

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# Delete Inquiry (admin)
############################


@router.delete("/{inquiry_id}", response_model=bool)
async def delete_inquiry(
    inquiry_id: str,
    user=Depends(get_admin_user),
):
    result = Inquiries.delete_inquiry_by_id(inquiry_id)
    if result:
        return True

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )
