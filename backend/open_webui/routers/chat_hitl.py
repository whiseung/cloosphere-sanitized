"""HITL (Human-in-the-Loop) resume 라우터.

UnifiedAgent 가 도구 호출 직전에 interrupt 로 멈추면 클라이언트는 socket.io
hitl_request 이벤트를 받는다. 사용자 결정 (approve/edit/reject/respond) 후
이 라우터로 같은 그래프를 깨워 stream 을 이어간다.

본 라우터는 thin shim — `metadata.hitl_resume` 를 박아서 기존 OpenAI
chat-completion 라우터에 위임한다 (모델 추출 / api_config / UnifiedAgent
인스턴스화 로직 재사용). UnifiedAgent.run() 의 라우팅 분기가 hitl_resume
마킹을 보고 UnifiedAgent.resume() 으로 분기한다.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.chats import Chats
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])
router = APIRouter()


class HITLDecision(BaseModel):
    """HITL 결정 한 건. interrupt 의 action_requests 와 동일 순서로 배열."""

    type: str  # "approve" | "edit" | "reject" | "respond"
    edited_action: Optional[dict] = None  # type=edit 일 때 {"name": ..., "args": {...}}
    message: Optional[str] = None  # type=reject/respond 일 때 사용자 메시지


class ResumeBody(BaseModel):
    thread_id: str
    decisions: List[HITLDecision]
    payload: dict  # 원본 chat-completion form_data (model, messages 등)
    # 트레이스 통합용 — 첫 invocation 의 chain_run_id / trace_id. 클라이언트가
    # hitl_request 이벤트로 받은 값을 그대로 다시 보낸다. 같은 chain 의 child
    # 로 이어가 트레이스가 두 chain 으로 쪼개지지 않게.
    chain_run_id: Optional[str] = None
    trace_id: Optional[str] = None


@router.post("/{chat_id}/resume")
async def resume_chat_hitl(
    chat_id: str,
    body: ResumeBody,
    request: Request,
    user=Depends(get_verified_user),
):
    """멈춰있는 HITL 그래프를 사용자 결정으로 재개.

    Args:
        chat_id: 권한 체크용. interrupt 가 발생한 chat 의 소유자만 resume 가능.
        body.thread_id: hitl_request 이벤트로 클라이언트가 받은 값.
        body.decisions: interrupt 의 각 action_request 에 대한 결정 (순서 일치).
        body.payload: 첫 invocation 의 form_data — 모델/메시지/api_config 추출에
            그대로 재사용된다. 클라이언트가 보유한 그대로 다시 보낸다.
    """
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    form_data = {**body.payload}
    metadata = dict(form_data.get("metadata") or {})
    metadata["hitl_resume"] = {
        "thread_id": body.thread_id,
        "decisions": [d.model_dump(exclude_none=True) for d in body.decisions],
        "chain_run_id": body.chain_run_id,
        "trace_id": body.trace_id,
    }
    # 첫 invocation 흐름과 동일하게 컨텍스트 보강 — resume 는 chat_completion 의
    # pre-처리 일부 (event_emitter 가 요구하는 user_id 주입 등) 를 건너뛰므로
    # 여기서 직접 채운다.
    metadata["chat_id"] = chat_id
    metadata["user_id"] = user.id
    metadata.setdefault("session_id", None)
    form_data["metadata"] = metadata

    # main.py 의 chat_completion 을 lazy import — 모듈 import-cycle 회피.
    # main.py 핸들러가 metadata 보강 (agent_config = AgentConfig.from_model_info...)
    # 까지 해주므로 UnifiedAgent.__init__ 의 _enable_tool_connections 가 정상 평가.
    # openai.py 의 generate_chat_completion 직접 호출 시 그 단계가 건너뛰어져서
    # tool_connection 도구가 LLM 에 노출되지 않는 버그가 있었음.
    from open_webui.main import chat_completion as main_chat_completion

    return await main_chat_completion(
        request=request,
        form_data=form_data,
        user=user,
    )
