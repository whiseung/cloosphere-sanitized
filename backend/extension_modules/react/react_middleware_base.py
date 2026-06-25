import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

# show_reasoning 라이브 트레이스에서 숨길 내부 제어용 툴 — 구조화 출력/submit 및
# HITL 되묻기(ask_user/drive_select_files)는 사용자에게 의미 없는 노이즈라
# collapsible narration 에 노출하지 않는다.
_INTERNAL_TOOL_NAMES = {
    "UnifiedAgentOutput",
    "submit_result",
    "ask_user",
    "drive_select_files",
}

from extension_modules.react.react_base import AgentStateBase
from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from langgraph.types import Command
from open_webui.models.message_trace import (
    MessageTraceCreateForm,
    MessageTraces,
    RunStatus,
    RunType,
)
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.utils.keep_alive import KeepAlive
from open_webui.utils.tracing import _trace_local_stack


class MiddlewareBase(AgentMiddleware):
    def __init__(
        self, event_emitter, event_call, metadata: Dict[str, Any], trace_context=None
    ):
        self.event_emitter = event_emitter
        self.event_call = event_call
        self.metadata = metadata
        self.message_step = 0

        # External TraceContext (shared with embedding code)
        self._trace_context = trace_context

        # Tracing state
        self._trace_id: Optional[str] = None
        self._chain_run_id: Optional[str] = None
        self._current_run_id: Optional[str] = None
        self._system_prompt: Optional[str] = (
            None  # Set externally (system prompt is not in state messages)
        )
        self._tool_descriptions: Optional[Dict[str, str]] = (
            None  # Set externally ({tool_name: description})
        )
        self._tool_descriptions_logged = False
        self._run_stack: list[str] = []
        self._order_counters: Dict[str, int] = {"root": 0}
        self._run_orders: Dict[str, str] = {}
        self._tracing_enabled = self._check_tracing_enabled()

        # show_reasoning: 모델 호출별 소요시간(초). aafter_model 에서 AIMessage
        # 순서대로 append → reasoning <details> 블록의 "Thought for Ns" 표시에 사용.
        self._model_started_at: Optional[float] = None
        self._model_durations: list[int] = []

        # show_reasoning 라이브 스트리밍: 에이전트의 "추론 과정"을 ChatGPT/Gemini 식
        # 라이브 윈도우로 표시. ⚠️ message.content 가 아니라 **전용 side-channel
        # 이벤트**({type:"agent_reasoning"})로 보낸다 — content 는 OpenAI 호환 API·임베드
        # 등 모든 소비자가 읽는 답변 본문이라 오염 금지. 프론트는 message.reasoning
        # 전용 필드에 저장해 우리 챗 UI 에서만 렌더(WS 블립에도 자가치유).
        # 에이전트가 미들웨어 생성 후 _show_reasoning_level 을 "off"|"brief"|"detailed".
        # _live_blocks 는 narration 단계 순서 리스트:
        #   {"kind":"tool","tool":<name>,"arg":<핵심 인자>,"result":<detailed 미리보기>}
        #   {"kind":"text","text":<모델 thought/thinking 텍스트>}
        # 문구(i18n)는 프론트가 현지화하도록 구조만 싣고, 단계 변경 때마다 전체 재emit.
        self._show_reasoning_level: str = "off"
        self._live_blocks: list[Dict[str, Any]] = []
        self._reasoning_start_at: Optional[float] = None

    def _check_tracing_enabled(self) -> bool:
        """Check if tracing is enabled from config"""
        try:
            from open_webui.config import ENABLE_MESSAGE_TRACING

            return ENABLE_MESSAGE_TRACING.value
        except Exception:
            return False

    # ── Shared state accessors ──
    # TraceContext가 있으면 공유 상태를 사용하여 dotted_order 충돌 방지

    @property
    def _effective_run_stack(self) -> list[str]:
        """로컬 스택 > TraceContext 공유 스택 > 인스턴스 스택 순서로 반환.

        동시 도구 호출 시 _trace_local_stack(contextvars)이 설정되어
        각 비동기 태스크가 독립 스택을 사용합니다.
        """
        local = _trace_local_stack.get(None)
        if local is not None:
            return local
        if self._trace_context:
            return self._trace_context._run_stack
        return self._run_stack

    @property
    def _effective_order_counters(self) -> Dict[str, int]:
        """TraceContext가 있으면 공유 _order_counters 사용"""
        if self._trace_context:
            return self._trace_context._order_counters
        return self._order_counters

    @property
    def _effective_run_orders(self) -> Dict[str, str]:
        """TraceContext가 있으면 공유 _run_orders 사용"""
        if self._trace_context:
            self._trace_context._init_run_orders()
            return self._trace_context._run_orders
        return self._run_orders

    def _get_next_order(self, parent_run_id: Optional[str]) -> str:
        """Generate next dotted_order (shared state 사용).

        숫자를 3자리 zero-pad하여 문자열 정렬 시 올바른 순서 보장.
        예: "001", "002", ... "010", "011" (10개 이상 자식 노드에서도 정렬 정확)
        """
        counters = self._effective_order_counters
        orders = self._effective_run_orders

        key = parent_run_id or "root"
        if key not in counters:
            counters[key] = 0
        counters[key] += 1
        counter = counters[key]

        padded = f"{counter:03d}"
        if parent_run_id and parent_run_id in orders:
            parent_order = orders[parent_run_id]
            return f"{parent_order}.{padded}"
        return padded

    def _start_trace_run(
        self,
        run_type: str,
        name: str,
        inputs: Optional[dict] = None,
        model_id: Optional[str] = None,
        push_stack: bool = True,
    ) -> Optional[str]:
        """Start a new trace run and return the run ID.

        Args:
            push_stack: True이면 실행 스택에 push하여 하위 run의 부모가 됨.
                        False이면 push하지 않음 (동시 실행 도구용).
        """
        if not self._tracing_enabled:
            return None

        # trace_id fallback — abefore_agent 는 graph 의 첫 invocation 에서만
        # 호출되므로 HITL Command(resume=...) 같은 깨우기 흐름에서는 _trace_id
        # 가 None 일 수 있다. 그 경우 즉시 fresh uuid 부여 (정상 흐름에서는
        # 이미 set 되어 있으니 no-op).
        if not self._trace_id:
            if self._trace_context and self._trace_context.enabled:
                self._trace_id = self._trace_context.trace_id
            else:
                self._trace_id = str(uuid.uuid4())

        run_stack = self._effective_run_stack
        parent_run_id = run_stack[-1] if run_stack else None
        dotted_order = self._get_next_order(parent_run_id)

        form_data = MessageTraceCreateForm(
            trace_id=self._trace_id,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
            chat_id=self.metadata.get("chat_id"),
            message_id=self.metadata.get("message_id"),
            user_id=self.metadata.get("user_id"),
            run_type=run_type,
            name=name,
            status=RunStatus.RUNNING.value,
            inputs=inputs,
            model_id=model_id,
        )

        trace = MessageTraces.create_trace(form_data)
        if trace:
            self._effective_run_orders[trace.id] = dotted_order
            if push_stack:
                run_stack.append(trace.id)
            return trace.id
        return None

    def _complete_trace_run(
        self,
        run_id: Optional[str],
        outputs: Optional[dict] = None,
        token_usage: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        """Complete a trace run"""
        if not run_id or not self._tracing_enabled:
            return

        MessageTraces.complete_trace(
            trace_id=run_id,
            outputs=outputs,
            token_usage=token_usage,
            error=error,
        )

        run_stack = self._effective_run_stack
        if run_stack and run_stack[-1] == run_id:
            run_stack.pop()

    @staticmethod
    def _extract_system_prompt(messages, max_length: int = 2000) -> Optional[str]:
        """Extract system prompt from message list."""
        for msg in messages:
            if hasattr(msg, "type") and msg.type == "system":
                content = msg.content if hasattr(msg, "content") else str(msg)
                if isinstance(content, str) and len(content) > max_length:
                    return content[:max_length] + "..."
                return content
        return None

    async def abefore_model(
        self, state: AgentStateBase, runtime: Runtime
    ) -> dict[str, Any] | None:
        """Called before LLM model invocation - start LLM tracing"""
        # show_reasoning: 이 모델 호출의 소요시간 측정 시작 (reasoning 블록 duration)
        self._model_started_at = time.time()
        model_id = self.metadata.get("llm_model_id")
        messages = state.get("messages", [])

        # Extract last user message for tracing
        user_message = None
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                user_message = msg.content if hasattr(msg, "content") else str(msg)
                if isinstance(user_message, str) and len(user_message) > 500:
                    user_message = user_message[:500] + "..."
                break

        # Use stored system prompt (updated by dynamic prompt middleware)
        # Fall back to extracting from messages (for non-dynamic agents)
        system_prompt = self._system_prompt or self._extract_system_prompt(messages)

        inputs: dict[str, Any] = {
            "messages_count": len(messages),
            "user_message": user_message,
            "system_prompt": system_prompt,
        }

        # Include tool descriptions on first LLM call only
        if self._tool_descriptions and not self._tool_descriptions_logged:
            inputs["tool_descriptions"] = self._tool_descriptions
            self._tool_descriptions_logged = True

        self._current_run_id = self._start_trace_run(
            run_type=RunType.LLM.value,
            name=model_id or "llm_call",
            inputs=inputs,
            model_id=model_id,
        )

    async def aafter_model(
        self, state: AgentStateBase, runtime: Runtime
    ) -> dict[str, Any] | None:
        # show_reasoning: 이 모델 호출 소요시간 기록 (AIMessage 순서와 1:1 정렬)
        if self._model_started_at is not None:
            self._model_durations.append(
                max(0, round(time.time() - self._model_started_at))
            )
            self._model_started_at = None
        ai_message = state.get("messages", [])[-1]

        # show_reasoning=detailed: 모델의 thought/thinking 텍스트를 추론 윈도우에 추가
        # (tool_calls 가 있는 "행동 전 사고" 또는 extended thinking 블록). 도구 단계보다
        # 먼저 추가돼 "분석 → 검색" 순서가 된다.
        if self._show_reasoning_level == "detailed" and isinstance(
            ai_message, AIMessage
        ):
            has_tc = bool(getattr(ai_message, "tool_calls", None))
            thought = self._extract_thought_text(ai_message, include_plain=has_tc)
            if thought:
                if self._reasoning_start_at is None:
                    self._reasoning_start_at = time.time()
                self._live_blocks.append({"kind": "text", "text": thought})
                await self._emit_live_trace()
        if isinstance(ai_message, AIMessage):
            tool_calls = getattr(ai_message, "tool_calls", None) or []
            usage = ai_message.usage_metadata
            self.message_step = self.message_step + 1

            if tool_calls:
                message_type = UsageMessageType.TOOL_CALL
            else:
                message_type = UsageMessageType.AGENT_STATE

            # 에이전트인 경우에만 agent_id 설정 (base_model_id가 있으면 에이전트)
            model_info = self.metadata.get("model", {})
            base_model_id = model_info.get("info", {}).get("base_model_id")
            agent_id = model_info.get("id") if base_model_id else None

            Usages.insert_new_usage(
                user_id=self.metadata.get("user_id"),
                chat_id=self.metadata.get("chat_id"),
                agent_id=agent_id,
                model_id=self.metadata.get("llm_model_id"),
                message_id=self.metadata.get("message_id"),
                message_step=self.message_step,
                message_type=message_type,
                total_tokens=usage.get("total_tokens"),
                usage=usage,
                tool_calls=tool_calls,
            )

            # Build detailed trace outputs
            outputs = {}
            if tool_calls:
                outputs["has_tool_calls"] = True
                outputs["tool_calls_count"] = len(tool_calls)
                outputs["tool_names"] = [
                    tc.get("name", "unknown")
                    for tc in tool_calls
                    if isinstance(tc, dict)
                ]
            else:
                outputs["has_tool_calls"] = False
                # Capture agent's final response text
                content = getattr(ai_message, "content", "")
                if isinstance(content, str) and content.strip():
                    outputs["response"] = (
                        content[:3000] + "..." if len(content) > 3000 else content
                    )
                    outputs["response_length"] = len(content)

            self._complete_trace_run(
                self._current_run_id,
                outputs=outputs,
                token_usage=usage,
            )
            self._current_run_id = None
        elif self._current_run_id:
            self._complete_trace_run(
                self._current_run_id,
                outputs={"note": "non_ai_message"},
            )
            self._current_run_id = None

    # 핵심 인자 추출용 우선순위 키 (narration arg)
    _ARG_KEYS = (
        "query",
        "queries",
        "seed",
        "term",
        "question",
        "q",
        # "sql" 제외 — SQL 쿼리 전문은 사용자에게 노출 안 함(추론 창엔 칩+결과 미리보기만)
        "name",
        "table_name",
        "concept",
        "document_id",
        "keyword",
        "text",
    )

    @classmethod
    def _extract_key_arg(cls, tool_input) -> str:
        """툴 인자에서 사용자에게 보여줄 핵심 값 하나를 뽑아 짧은 문자열로."""
        if not isinstance(tool_input, dict):
            return ""
        for k in cls._ARG_KEYS:
            v = tool_input.get(k)
            if v is None or v == "":
                continue
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v if x)
            v = " ".join(str(v).split())  # 개행·연속공백 정리
            return v[:200] + ("…" if len(v) > 200 else "")  # 결과와 동일하게 200자 캡
        return ""

    @staticmethod
    def _clean_preview(text, limit: Optional[int] = 200) -> str:
        """툴 결과를 짧은 미리보기로 절단(기본 200자). 추론 창은 '무엇을 했는지'
        요약이 목적이고, 툴 결과는 사실상 모델에 주입되는 컨텍스트 데이터(스키마
        덤프 등)라 통째로 보여주면 거대해진다 → 미리보기만."""
        s = " ".join(str(text).split())
        if limit is not None and len(s) > limit:
            return s[:limit] + "…"
        return s

    @staticmethod
    def _extract_thought_text(ai_message, include_plain: bool) -> str:
        """AIMessage 에서 thinking/thought 텍스트 추출 (extended thinking + 평문)."""
        parts: list[str] = []
        content = getattr(ai_message, "content", "")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                bt = block.get("type")
                if bt == "thinking":
                    t = block.get("thinking", "")
                elif bt == "reasoning":
                    t = block.get("reasoning") or block.get("text") or ""
                elif bt == "text" and include_plain:
                    t = block.get("text", "")
                else:
                    t = ""
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
        elif isinstance(content, str) and include_plain and content.strip():
            parts.append(content.strip())
        ak = getattr(ai_message, "additional_kwargs", None) or {}
        rc = ak.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            parts.append(rc.strip())
        return " ".join(parts).strip()  # 자르지 않음 — 전체 추론 텍스트 표시

    def reasoning_data(
        self, level: Optional[str] = None, done: bool = False
    ) -> Optional[Dict[str, Any]]:
        """_live_blocks(narration 단계)를 프론트 AgentReasoning 이 쓸 **구조화 dict** 로.

        ⚠️ message.content 에 넣지 않는다 — content 는 OpenAI 호환 API/임베드 등 모든
        소비자가 읽는 답변 본문이므로 오염시키면 안 된다. 대신 전용 side-channel
        이벤트({type:"agent_reasoning"}) 의 data 로 보내고, 우리 챗 UI 만 렌더한다.
        문구(i18n)는 프론트가 현지화하므로 구조(steps)만 싣는다.
        level: "brief"(narration 만) | "detailed"(+ 결과 한 줄 미리보기).
        """
        level = level or self._show_reasoning_level
        if level == "off" or not self._live_blocks:
            return None
        steps: list[Dict[str, Any]] = []
        for b in self._live_blocks:
            kind = b.get("kind")
            if kind == "tool":
                # 행동(툴+인자) + 결과 짧은 미리보기(≈200자, awrap 에서 이미 절단).
                # 전체 덤프는 거대해서 안 싣고, 그렇다고 빼면 thinking 미노출 모델에선
                # 툴 이름만 남아 텅 비므로 미리보기는 둔다. 모델이 thinking 을 노출하면
                # text 단계로 진짜 사고가 추가된다.
                s: Dict[str, Any] = {
                    "kind": "tool",
                    "tool": b.get("tool", ""),
                    "arg": b.get("arg", ""),
                }
                if b.get("result"):
                    s["result"] = b["result"]
                steps.append(s)
            elif kind == "text" and b.get("text"):
                steps.append({"kind": "text", "text": b["text"]})
        if not steps:
            return None
        dur = 0
        if self._reasoning_start_at is not None:
            dur = max(0, round(time.time() - self._reasoning_start_at))
        return {"steps": steps, "done": done, "duration": dur}

    async def _emit_live_trace(self) -> None:
        """현재 추론 단계를 **전용 side-channel 이벤트**(agent_reasoning)로 라이브 emit.

        message.content(공유 답변 본문)를 건드리지 않으므로 (a) API/임베드 등 다른
        소비자엔 본문만 깨끗이 나가고, (b) 답변 스트리밍·DB 저장과 충돌하지 않으며,
        (c) 프론트의 전용 필드(message.reasoning)에 저장돼 WS 블립에도 자가치유된다.
        어떤 예외도 에이전트 실행을 깨지 않는다(제어흐름 예외는 재전파).
        """
        if self._show_reasoning_level == "off":
            return
        try:
            data = self.reasoning_data(done=False)
            if data is not None:
                await self.event_emitter({"type": "agent_reasoning", "data": data})
        except GraphBubbleUp:
            raise
        except Exception:
            pass

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        tool_call = request.tool_call
        tool_name = tool_call.get("name") if tool_call else "unknown"
        tool_input = tool_call.get("args") if tool_call else {}

        # show_reasoning=detailed: "추론 과정" 윈도우에 이 도구 단계를 narration 으로
        # 추가하고 라이브 emit. 내부 제어용 툴(UnifiedAgentOutput/submit_result) 제외.
        # (brief 는 아래 기존 status 표시만, off 는 아무것도 안 함)
        live_step = None
        if (
            self._show_reasoning_level == "detailed"
            and tool_name not in _INTERNAL_TOOL_NAMES
        ):
            if self._reasoning_start_at is None:
                self._reasoning_start_at = time.time()
            live_step = {
                "kind": "tool",
                "tool": tool_name,
                "arg": self._extract_key_arg(tool_input),
                "result": None,
            }
            self._live_blocks.append(live_step)
            await self._emit_live_trace()

        # Start tool trace — push_stack=False로 공유 스택 오염 방지
        # LangGraph ToolNode가 asyncio.gather로 도구를 동시 실행하므로
        # 공유 스택에 push하면 동시 도구 호출 간 parent_run_id가 오염됨
        tool_run_id = self._start_trace_run(
            run_type=RunType.TOOL.value,
            name=tool_name,
            inputs={"args": tool_input},
            push_stack=False,
        )

        # 태스크별 로컬 스택 설정 — 도구 핸들러 내 서브런들이
        # 이 도구를 부모로 인식하도록 함 (asyncio.gather의 각 Task에 격리)
        local_stack: list[str] = [tool_run_id] if tool_run_id else []
        token = _trace_local_stack.set(local_stack)

        error_msg = None
        try:
            async with KeepAlive(
                self.event_emitter, "Executing {{detail}}...", detail=tool_name
            ):
                result = await handler(request)
        except GraphBubbleUp:
            # langgraph 제어흐름 예외(GraphInterrupt/NodeInterrupt/ParentCommand 등,
            # 모두 GraphBubbleUp 서브클래스)는 HITL interrupt·핸드오프를 위한 정상
            # 제어흐름이다. 절대 trace 오류로 마킹하거나 라이브 emit 같은 async 부작용을
            # 끼우지 말고 즉시 재전파해야 한다(부작용을 끼우면 interrupt 가 깨진다 —
            # langgraph ToolNode 자체도 동일하게 GraphBubbleUp 을 그대로 re-raise 한다).
            _trace_local_stack.reset(token)
            raise
        except Exception as e:
            error_msg = str(e)
            _trace_local_stack.reset(token)
            self._complete_trace_run(tool_run_id, error=error_msg)
            # narration 단계에 오류 미리보기 반영
            if live_step is not None:
                live_step["result"] = self._clean_preview(f"오류: {error_msg}")
                await self._emit_live_trace()
            raise

        _trace_local_stack.reset(token)

        # Extract tool result content from ToolMessage or Command
        result_str = None
        if isinstance(result, ToolMessage):
            result_str = str(result.content) if result.content else None
        elif isinstance(result, Command):
            # Command wraps ToolMessage inside update["messages"]
            messages = (result.update or {}).get("messages", [])
            for msg in messages:
                if isinstance(msg, ToolMessage) and msg.content:
                    result_str = str(msg.content)
                    break
        self._complete_trace_run(
            tool_run_id,
            outputs={"result": result_str},
        )

        # show_reasoning=detailed: 결과 한 줄 미리보기로 narration 단계 갱신 후 재emit.
        if live_step is not None:
            if result_str:
                live_step["result"] = self._clean_preview(result_str)
            await self._emit_live_trace()

        if tool_call is None:
            return result

        # show_reasoning=brief(기본): 기존 단순 상태표시 — 툴 이름만 status 로.
        # detailed 는 위 추론 윈도우가 대신하고, off 는 표시하지 않는다.
        if self._show_reasoning_level == "brief":
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Tool call: {{toolName}}",
                        "done": False,
                        "detail": tool_name,
                    },
                }
            )

        return result

    async def abefore_agent(
        self, state: AgentStateBase, runtime: Runtime
    ) -> dict[str, Any] | None:
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Starting Agent...",
                    "done": False,
                    "detail": "Starting Agent...",
                },
            }
        )

        # Initialize trace for the entire agent run
        # Use TraceContext's trace_id if available (so embedding traces share the same trace)
        if self._trace_context and self._trace_context.enabled:
            self._trace_id = self._trace_context.trace_id
        else:
            self._trace_id = str(uuid.uuid4())
        model_info = self.metadata.get("model", {})
        agent_name = model_info.get("name", "react_agent")

        # Extract last user message for tracing
        messages = state.get("messages", [])
        user_message = None
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                user_message = msg.content if hasattr(msg, "content") else str(msg)
                if isinstance(user_message, str) and len(user_message) > 500:
                    user_message = user_message[:500] + "..."
                break

        # Use stored system prompt, fall back to extracting from messages
        system_prompt = self._system_prompt or self._extract_system_prompt(messages)

        self._chain_run_id = self._start_trace_run(
            run_type=RunType.CHAIN.value,
            name=agent_name,
            inputs={
                "messages_count": len(messages),
                "user_id": self.metadata.get("user_id"),
                "user_message": user_message,
                "system_prompt": system_prompt,
            },
        )

    async def aafter_agent(
        self, state: AgentStateBase, runtime: Runtime
    ) -> dict[str, Any] | None:
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Agent completed...",
                    "done": False,
                    "detail": "Agent completed...",
                },
            }
        )

        # Safety: complete any uncompleted LLM trace (e.g., response_format edge cases)
        if self._current_run_id:
            self._complete_trace_run(self._current_run_id)
            self._current_run_id = None

        # Complete the chain trace
        self._complete_trace_run(
            self._chain_run_id,
            outputs={
                "total_steps": self.message_step,
            },
        )

    # ── Public trace helpers (for external callers like _run_stream) ──

    def start_trace_run(
        self,
        run_type: str,
        name: str,
        inputs: Optional[dict] = None,
        model_id: Optional[str] = None,
        push_stack: bool = True,
    ) -> Optional[str]:
        """Public wrapper for _start_trace_run."""
        return self._start_trace_run(run_type, name, inputs, model_id, push_stack)

    def complete_trace_run(
        self,
        run_id: Optional[str],
        outputs: Optional[dict] = None,
        token_usage: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        """Public wrapper for _complete_trace_run."""
        return self._complete_trace_run(run_id, outputs, token_usage, error)
