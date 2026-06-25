"""
SR (Service Request) Router

고객 인스턴스에서 메인 Cloosphere로 SR을 제출하는 프록시 API.
SR_KEY, CLOOCUS_PUBLIC_URL 환경변수가 설정되어야 동작.
"""

import logging
import os
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.env import SR_KEY, SRC_LOG_LEVELS
from open_webui.utils.auth import get_admin_user
from pydantic import BaseModel

CLOOCUS_PUBLIC_URL: Optional[str] = os.environ.get("CLOOCUS_PUBLIC_URL")

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


SR_TYPES = {
    "usage_limit": ["limit_increase", "limit_check"],
    "feature": ["chat", "agent", "knowledge", "database", "tool"],
    "bug": ["chat_error", "agent_error", "upload_error", "other_error"],
    "account": ["permission_request", "account_issue"],
    "other": ["improvement", "other"],
}


class SRSubmitForm(BaseModel):
    title: str
    type: str = "other"
    content: str


class SRConfigResponse(BaseModel):
    enabled: bool
    types: dict


@router.get("/config")
async def get_sr_config(user=Depends(get_admin_user)) -> SRConfigResponse:
    """SR 설정 조회. SR_KEY와 CLOOCUS_PUBLIC_URL이 모두 설정되어야 활성화."""
    return SRConfigResponse(
        enabled=bool(SR_KEY and CLOOCUS_PUBLIC_URL),
        types=SR_TYPES,
    )


@router.post("/submit")
async def submit_sr(
    form_data: SRSubmitForm,
    user=Depends(get_admin_user),
):
    """SR 제출 — 메인 Cloosphere로 프록시."""
    if not SR_KEY or not CLOOCUS_PUBLIC_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SR is not configured. Set SR_KEY and CLOOCUS_PUBLIC_URL environment variables.",
        )

    url = f"{CLOOCUS_PUBLIC_URL.rstrip('/')}/api/v1/cloocus/sr/submit"

    try:
        response = requests.post(
            url,
            headers={
                "X-SR-Key": SR_KEY,
                "Content-Type": "application/json",
            },
            json={
                "title": form_data.title,
                "type": form_data.type,
                "content": form_data.content,
                "user_name": user.name,
                "user_email": user.email,
            },
            timeout=30,
        )

        if response.status_code == 200:
            return {"success": True, "message": "SR submitted successfully"}
        else:
            detail = response.json().get("detail", "Unknown error")
            log.error(f"SR submit failed: {response.status_code} - {detail}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"SR submission failed: {detail}",
            )
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="SR submission timed out",
        )
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect to SR server",
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"SR submit error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
