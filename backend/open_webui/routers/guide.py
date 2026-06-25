"""
Guide Q&A Router

가이드 문서 기반 Q&A 채팅 API.
색인은 BM25 in-memory — startup 시 자동 빌드, 콘텐츠 hash 변경 자동 감지.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


class GuideChatForm(BaseModel):
    messages: List[dict]
    model_id: Optional[str] = None


@router.post("/chat")
async def guide_chat(
    request: Request,
    form_data: GuideChatForm,
    user=Depends(get_verified_user),
):
    """가이드 Q&A 채팅. 사용자 질문에 가이드 문서를 기반으로 답변."""
    from extension_modules.guide_agent.guide_agent import GuideQAAgent
    from extension_modules.utils.llm import get_model_config_from_app

    if not form_data.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one message required",
        )

    if not form_data.model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model_id is required",
        )

    # 모델 설정 조회
    model_config = get_model_config_from_app(request.app, form_data.model_id)
    if not model_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{form_data.model_id}' not found",
        )

    metadata = {
        "user_id": user.id,
        "user_role": user.role,
        "user": {"id": user.id, "role": user.role},
    }

    agent = GuideQAAgent(
        api_config=model_config.get("api_config", {}),
        base_url=model_config.get("base_url", ""),
        api_key=model_config.get("api_key", ""),
        metadata=metadata,
        request=request,
    )

    result = await agent.run_chat(
        messages=form_data.messages,
        model_id=form_data.model_id,
    )

    return result
