import logging
from typing import Any, Dict, List

from extension_modules.react.prompts import (
    get_final_answer_system_prompt,
    get_react_system_prompt,
)
from extension_modules.react.react_base import (
    AgentOutputBase,
    AgentStateBase,
)
from extension_modules.react.react_middleware_base import MiddlewareBase
from extension_modules.react.tools_base import ReactToolsBase
from fastapi import Request
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRequest,
    dynamic_prompt,
)
from langchain_core.tools import StructuredTool
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
)
from pydantic import Field
from starlette.responses import StreamingResponse

log = logging.getLogger(__name__)


class CustomAgentState(AgentStateBase):
    country_codes: List[str] = Field(default_factory=list)


class CustomAgentOutput(AgentOutputBase):
    pass


@dynamic_prompt
def dynamic_system_prompt(request: ModelRequest) -> str:
    state = request.state
    return get_react_system_prompt(state=state)


class KBSphereAgent(ReactToolsBase):
    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
    ):
        super().__init__(
            api_config,
            base_url,
            api_key,
            metadata,
            enable_evaluation=True,
            enable_extract_context_info=True,
            enable_web_search=True,
            tavily_api_key=request.app.state.config.TAVILY_API_KEY,
            request=request,
        )

    async def _run_agent(self, payload: Dict[str, Any], tools: List[StructuredTool]):
        llm = self._create_llm(payload, stream=False)
        messages, system_prompt = self._extract_messages_and_prompt(payload)
        attached_files = self.metadata.get("message_info", {}).get("file_ids", [])

        # 실제 LLM 모델 ID를 metadata에 추가
        middleware_metadata = {
            **self.metadata,
            "llm_model_id": payload.get("model"),
        }

        from open_webui.utils.tracing import get_trace_context

        trace_context = get_trace_context(self.request)
        agent = create_agent(
            llm,
            tools,
            system_prompt=get_react_system_prompt(state={}),
            state_schema=CustomAgentState,
            middleware=[
                MiddlewareBase(
                    self.event_emitter,
                    self.event_call,
                    middleware_metadata,
                    trace_context=trace_context,
                ),
                dynamic_system_prompt,
            ],
            response_format=CustomAgentOutput,
        )

        state_snapshot: Dict[str, Any] = {
            "messages": messages,
            "attached_files": attached_files,
        }
        result = await agent.ainvoke(state_snapshot)
        return result

    async def _run_stream(
        self, agent_result: CustomAgentState, payload: Dict[str, Any]
    ):
        aggregated_sources = self.build_aggregated_sources_by_filename(agent_result)

        source_lines: list[str] = []
        idx = 1

        for src in aggregated_sources.values():
            if not isinstance(src, dict):
                continue

            # 1) 프론트(OpenWebUI)로 source 이벤트 전송
            await self.event_emitter({"type": "source", "data": src})

            # 2) 모델 입력용 source context 구성
            src_obj = src.get("source") or {}
            name = src_obj.get("name") or src_obj.get("id") or "N/A"

            docs = [
                d.strip()
                for d in src.get("document", [])
                if isinstance(d, str) and d.strip()
            ]
            if not docs:
                continue

            source_lines += [f"[{idx}] {name}", *[f"- {d}" for d in docs], ""]

            idx += 1

        source_ctx = "\n".join(source_lines).strip()

        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Generating final answer...",
                    "done": False,
                    "detail": "Generating final answer...",
                },
            }
        )

        # Fallback: extract question from payload if normalized_question is empty
        user_question = agent_result.get("normalized_question", "")
        if not user_question:
            for msg in reversed(payload.get("messages", [])):
                if msg.get("role") == "user":
                    c = msg.get("content", "")
                    if isinstance(c, str):
                        user_question = c
                    elif isinstance(c, list):
                        user_question = " ".join(
                            p.get("text", "")
                            for p in c
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    break

        system_prompt = get_final_answer_system_prompt(
            user_question=user_question,
            base_system_prompt=None,
            sources_context=source_ctx,
            language=agent_result.get("language", ""),
            messages=payload.get("messages", []),
        )
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            self._run_final_stream(payload, system_prompt),
            media_type="text/event-stream",
            headers=headers,
        )

    async def run(
        self,
        *,
        request,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        user,
        run_flow: bool = False,
    ):
        self.tools = self.get_tools()

        self.event_emitter = get_event_emitter(metadata)
        self.event_call = get_event_call(metadata)

        result = await self._run_agent(payload, self.tools)
        aggregated_sources = self.build_aggregated_sources_by_filename(result)

        if run_flow:
            return {
                "messages": result["messages"],
                "sources": aggregated_sources,
            }

        return await self._run_stream(result, payload)
