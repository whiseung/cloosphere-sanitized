"""UI Action Tools — client-side DOM manipulation bridge for embed widgets.

Flow:
    1. Agent calls a tool (e.g. fill_form_field)
    2. Tool generates a request_id, creates an asyncio Future
    3. Tool emits 'chat-events' with type='ui:command' to the user's session
    4. Client iframe (EmbedChat) receives the event and forwards via postMessage
    5. embed.js executes the command on the parent DOM
    6. Result flows back via postMessage → iframe → Socket.IO 'ui:response'
    7. The registered listener completes the Future → tool returns result

Multi-worker safety:
    `_pending_futures` is per-process. In multi-worker deployments, the
    HTTP handler (worker A) that owns the Future may differ from the
    Socket.IO worker (B) that receives the 'ui:response'. To bridge this,
    register_ui_response() publishes to Redis and every worker subscribes;
    whichever worker owns the Future resolves it locally.

Timeout: 60 seconds default. 호스트 페이지가 fill-field 응답에 외부 API
fetch (예: DART) 결과를 동기적으로 끼워넣는 경우 15s 로는 부족 — 실측
20–30s 케이스 다수 관찰. UI 액션 자체는 빠르지만 호스트가 시키는
side-effect 가 늦으면 그 latency 가 그대로 응답 시간이 됨.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Global registry of pending UI command futures (request_id -> asyncio.Future)
_pending_futures: Dict[str, asyncio.Future] = {}

DEFAULT_TIMEOUT = 60.0

# ---- Redis pub/sub for cross-worker future resolution ----
_UI_RESPONSE_CHANNEL = "cloosphere:ui_action:response"
_redis_pub: Any = None  # redis.asyncio.Redis | None
_pubsub_task: Optional[asyncio.Task] = None
_pubsub_init_lock: Optional[asyncio.Lock] = None
# 첫 호출 race 방지: subscribe() 가 실제 effective 한 뒤 set 됨.
# _ensure_pubsub() 은 이 event 를 await 한 후에만 리턴.
_pubsub_ready: Optional[asyncio.Event] = None


async def _ensure_pubsub() -> None:
    """Lazily start Redis pub/sub for cross-worker future resolution.

    Returns only after the subscriber loop has actually subscribed to the
    response channel — otherwise the first ui:command that is answered by
    a different worker would be lost (publish arrives before subscribe).

    No-op if WEBSOCKET_MANAGER is not 'redis' (single-worker dev).
    """
    global _redis_pub, _pubsub_task, _pubsub_init_lock, _pubsub_ready

    try:
        from open_webui.env import WEBSOCKET_MANAGER, WEBSOCKET_REDIS_URL
    except Exception:
        return

    if WEBSOCKET_MANAGER != "redis" or not WEBSOCKET_REDIS_URL:
        return

    if (
        _pubsub_task is not None
        and not _pubsub_task.done()
        and _pubsub_ready is not None
        and _pubsub_ready.is_set()
    ):
        return

    if _pubsub_init_lock is None:
        _pubsub_init_lock = asyncio.Lock()

    async with _pubsub_init_lock:
        if (
            _pubsub_task is not None
            and not _pubsub_task.done()
            and _pubsub_ready is not None
        ):
            # 이미 다른 코루틴이 task 를 띄움. ready 만 기다리고 리턴.
            try:
                await asyncio.wait_for(_pubsub_ready.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("[ui_action] pubsub ready wait timed out (5s)")
            return
        try:
            import redis.asyncio as aioredis

            _redis_pub = aioredis.from_url(WEBSOCKET_REDIS_URL, decode_responses=True)
            _pubsub_ready = asyncio.Event()
            _pubsub_task = asyncio.create_task(_subscriber_loop(WEBSOCKET_REDIS_URL))
            log.info(
                f"[ui_action] Redis pub/sub starting (channel={_UI_RESPONSE_CHANNEL})"
            )
        except Exception as e:
            log.warning(
                f"[ui_action] Redis pub/sub init failed, local-only resolution: {e}"
            )
            _redis_pub = None
            _pubsub_task = None
            _pubsub_ready = None
            return

    # subscribe() 가 effective 해질 때까지 대기 (lock 밖에서).
    if _pubsub_ready is not None:
        try:
            await asyncio.wait_for(_pubsub_ready.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("[ui_action] pubsub subscribe didn't become ready within 5s")


async def _subscriber_loop(redis_url: str) -> None:
    """Subscribe to ui_action response channel and resolve local pending futures.

    Sets `_pubsub_ready` only after subscribe() completes AND the first
    'subscribe' confirmation message is consumed from pubsub.listen() —
    only then are subsequent published messages guaranteed to arrive here.
    """
    import redis.asyncio as aioredis

    global _pubsub_ready

    while True:
        try:
            client = aioredis.from_url(redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(_UI_RESPONSE_CHANNEL)
            log.warning(f"[ui_action] Subscribed to {_UI_RESPONSE_CHANNEL}")
            async for message in pubsub.listen():
                msg_type = message.get("type")
                if msg_type == "subscribe":
                    # Confirmation that subscription is now live on the broker.
                    if _pubsub_ready is not None and not _pubsub_ready.is_set():
                        _pubsub_ready.set()
                        log.warning("[ui_action] pubsub ready (subscription confirmed)")
                    continue
                if msg_type != "message":
                    continue
                try:
                    payload = json.loads(message.get("data") or "{}")
                    req_id = payload.get("request_id")
                    if not req_id:
                        continue
                    resolved = _local_resolve(req_id, payload.get("result"))
                    log.warning(
                        f"[ui_action] subscriber received req_id={req_id} "
                        f"resolved_locally={resolved} "
                        f"pending_count={len(_pending_futures)}"
                    )
                except Exception as e:
                    log.error(f"[ui_action] subscriber parse error: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"[ui_action] subscriber loop error, retry in 2s: {e}")
            # 재시도 시에는 ready 를 다시 false 로. 다음 subscribe 확인까지 대기.
            if _pubsub_ready is not None and _pubsub_ready.is_set():
                _pubsub_ready = asyncio.Event()
            await asyncio.sleep(2)


def _local_resolve(request_id: str, result: Any) -> bool:
    fut = _pending_futures.pop(request_id, None)
    if fut is None:
        return False
    if not fut.done():
        fut.set_result(result)
    return True


async def register_ui_response(request_id: str, result: Any) -> bool:
    """Called from Socket.IO 'ui:response' handler.

    Tries local resolution first (same-worker fast path). If no local future
    is pending, publishes to Redis so the worker that owns the Future can
    resolve it. Returns True if dispatched (locally or via Redis).

    수신 워커가 _send_ui_command 를 한 번도 안 한 상태면 _redis_pub 이 아직
    None 이라 publish 가 그냥 드롭된다. 8-worker 환경에서 emit 워커 ≠ recv
    워커가 잦아 이게 회귀의 핵심. 여기서도 _ensure_pubsub() 을 먼저 돌려
    publisher 를 보장한다.
    """
    log.warning(
        f"[ui_action] register_ui_response invoked req_id={request_id} "
        f"local_pending_count={len(_pending_futures)}"
    )
    if _local_resolve(request_id, result):
        log.warning(f"[ui_action] LOCAL resolve succeeded req_id={request_id}")
        return True

    # publisher 가 이 워커에 아직 없을 수 있다. ensure 후 재시도.
    await _ensure_pubsub()

    if _redis_pub is not None:
        try:
            await _redis_pub.publish(
                _UI_RESPONSE_CHANNEL,
                json.dumps({"request_id": request_id, "result": result}),
            )
            log.warning(f"[ui_action] PUBLISHED response to Redis req_id={request_id}")
            return True
        except Exception as e:
            log.error(f"[ui_action] Redis publish failed: {e}")

    log.warning(
        f"[ui_action] No pending future for request_id={request_id} "
        f"_redis_pub_set={_redis_pub is not None}"
    )
    return False


async def _send_ui_command(
    sio,
    session_id: Optional[str],
    user_id: Optional[str],
    chat_id: str,
    message_id: str,
    command: str,
    args: Dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Emit a UI command via Socket.IO and wait for the client response.

    라우팅 우선순위:
      1) user_id 가 있으면 `room=f"user:{user_id}"` 으로 emit
         (sid 가 reconnect 로 바뀌어도 새 sid 가 user_room 에 자동 enter — 일반
         chat-events 와 동일한 패턴, get_event_emitter 참조)
      2) user_id 없을 때만 fallback 으로 `to=session_id`
         (capture-once 라 reconnect 시 stale 가능 — 가능한 user_id 를 넘길 것)

    클라이언트 측 EmbedChat.svelte 는 `event.chat_id !== chatId` 필터로 같은
    유저의 다른 탭/iframe 으로의 누수를 차단한다.

    Args:
        sio: socketio.AsyncServer instance
        session_id: 클라이언트 소켓 sid. user_id 없을 때 fallback 라우팅에 사용.
        user_id: 사용자 ID. user_room 라우팅의 기본 키.
        chat_id: Current chat id
        message_id: Current AI message id (for UI correlation)
        command: Command name (fill-field, click, etc.)
        args: Command arguments
        timeout: Seconds to wait for response

    Returns:
        {"ok": bool, ...} result dict, or {"ok": False, "error": "timeout"}
    """
    await _ensure_pubsub()

    request_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    _pending_futures[request_id] = fut

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "data": {
            "type": "ui:command",
            "data": {
                "command": command,
                "args": args,
                "request_id": request_id,
            },
        },
    }

    emit_kwargs: Dict[str, Any]
    route: str
    if user_id:
        emit_kwargs = {"room": f"user:{user_id}"}
        route = f"user_room=user:{user_id}"
    elif session_id:
        emit_kwargs = {"to": session_id}
        route = f"session_id={session_id}"
    else:
        _pending_futures.pop(request_id, None)
        return {
            "ok": False,
            "error": "no routing target (user_id/session_id missing)",
            "_diag": {
                "user_id_present": False,
                "session_id_present": False,
            },
        }

    # 진단용 라우팅 메타. 로그에 못 가도 trace 의 도구 응답에는 박혀
    # 사용자가 timeout 시 어떤 경로로 emit 됐는지 확인 가능.
    diag = {
        "route": route,
        "user_id_present": bool(user_id),
        "session_id_present": bool(session_id),
        "request_id": request_id,
        "timeout_s": timeout,
    }

    try:
        log.info(
            f"[ui_action] Emitting ui:command command={command} request_id={request_id} "
            f"to {route}"
        )
        await sio.emit("chat-events", payload, **emit_kwargs)
    except Exception as e:
        _pending_futures.pop(request_id, None)
        log.error(f"[ui_action] emit failed: {e}")
        return {"ok": False, "error": f"emit failed: {e}", "_diag": diag}

    try:
        result = await asyncio.wait_for(fut, timeout=timeout)
        log.info(f"[ui_action] Received response for request_id={request_id}: {result}")
        if isinstance(result, dict):
            # 성공 응답에도 _diag 박아서 trace 로 어느 경로가 살아있는지 확인 가능.
            result.setdefault("_diag", diag)
            return result
        return {"ok": False, "error": "invalid response", "_diag": diag}
    except asyncio.TimeoutError:
        _pending_futures.pop(request_id, None)
        log.warning(
            f"[ui_action] Timeout waiting for response to request_id={request_id} "
            f"(route={route})"
        )
        return {
            "ok": False,
            "error": f"timeout after {timeout}s",
            "_diag": diag,
        }


# ============================================================
# Tool Argument Schemas
# ============================================================


class FillFieldArgs(BaseModel):
    selector: str = Field(
        ...,
        description='CSS selector for the input/textarea/select (e.g. "#title", \'select[name="type"]\')',
    )
    value: str = Field(..., description="Value to set (will be coerced to string)")


class FillFormArgs(BaseModel):
    form_selector: str = Field(
        ..., description='CSS selector for the form element (e.g. "#leave-form")'
    )
    data: Dict[str, Any] = Field(
        ...,
        description="Dict mapping field names (or ids) to values. Each key is matched against id or name attribute inside the form.",
    )


class ClickArgs(BaseModel):
    selector: str = Field(..., description="CSS selector for the element to click")


class ReadFormArgs(BaseModel):
    form_selector: str = Field(..., description="CSS selector for the form to read")


class HighlightArgs(BaseModel):
    selector: str = Field(..., description="CSS selector for the element to highlight")
    message: Optional[str] = Field(
        None, description="Optional message to show alongside the highlight"
    )


class NavigateArgs(BaseModel):
    url: str = Field(..., description="URL to navigate to (must be in allowed domains)")


class NoArgs(BaseModel):
    pass


# ============================================================
# UIActionManager
# ============================================================


class UIActionManager:
    """Builds LangChain tools that communicate with the embed widget client.

    Constructed per-request with the active chat/session context.
    """

    def __init__(
        self,
        sio,
        session_id: Optional[str],
        chat_id: str,
        message_id: str,
        user_id: Optional[str] = None,
    ):
        self.sio = sio
        self.session_id = session_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.user_id = user_id

    def _is_ready(self) -> bool:
        # user_id 또는 session_id 중 하나만 있어도 라우팅 가능 (user_room 우선).
        return bool(
            self.sio
            and self.chat_id
            and self.message_id
            and (self.user_id or self.session_id)
        )

    async def _call(self, command: str, args: Dict[str, Any]) -> str:
        if not self._is_ready():
            return json.dumps(
                {"ok": False, "error": "UI bridge not available in this context"},
                ensure_ascii=False,
            )
        result = await _send_ui_command(
            self.sio,
            self.session_id,
            self.user_id,
            self.chat_id,
            self.message_id,
            command,
            args,
        )
        return json.dumps(result, ensure_ascii=False)

    def get_tools(self) -> list:
        async def fill_form_field(selector: str, value: str) -> str:
            """Fill a single form field on the user's current page.

            Use this to set the value of an input, textarea, or select element.
            The selector should be a CSS selector that targets the element.
            """
            return await self._call(
                "fill-field", {"selector": selector, "value": value}
            )

        async def fill_form(form_selector: str, data: Dict[str, Any]) -> str:
            """Fill multiple fields of a form at once.

            Call get_form_schema() from the groupware MCP first to discover
            field names. Then pass a dict of {field_name: value}.
            """
            return await self._call(
                "fill-form",
                {"form_selector": form_selector, "data": data},
            )

        async def click_element(selector: str) -> str:
            """Click a button or link on the user's current page.

            Use this to submit forms or trigger actions after confirming
            with the user.
            """
            return await self._call("click", {"selector": selector})

        async def read_form(form_selector: str) -> str:
            """Read the current values of all fields in a form.

            Useful to check what the user has already entered before
            filling or submitting.
            """
            return await self._call("read-form", {"form_selector": form_selector})

        async def highlight_element(
            selector: str, message: Optional[str] = None
        ) -> str:
            """Highlight an element on the user's page to draw attention.

            Scrolls the element into view and adds a temporary outline.
            """
            return await self._call(
                "highlight", {"selector": selector, "message": message}
            )

        async def navigate_to(url: str) -> str:
            """Navigate the user's page to a new URL.

            Returns JSON with {"ok": true, "soft": true/false}.
            - soft=true: Host handled navigation without page reload.
              You CAN continue calling tools (e.g. get_page_info, fill_form).
            - soft=false: Page was hard-reloaded, chat session is reset.
              You MUST STOP calling tools and tell the user:
              "페이지로 이동했습니다. 작업을 계속하려면 다시 요청해주세요."
            """
            return await self._call("navigate", {"url": url})

        async def get_page_info() -> str:
            """Get information about the user's current page.

            Returns the current URL, title, and a list of form IDs present on the page.
            Use this FIRST to check what page the user is on before deciding whether
            to fill a form or navigate elsewhere.
            """
            return await self._call("get-page-info", {})

        tools = [
            StructuredTool.from_function(
                coroutine=fill_form_field,
                name="fill_form_field",
                description=(
                    "Fill a single form field on the user's current web page. "
                    "Provide a CSS selector and the value to set."
                ),
                args_schema=FillFieldArgs,
            ),
            StructuredTool.from_function(
                coroutine=fill_form,
                name="fill_form",
                description=(
                    "Fill multiple fields in a form at once on the user's current page. "
                    "Use after calling get_form_schema to know the field names."
                ),
                args_schema=FillFormArgs,
            ),
            StructuredTool.from_function(
                coroutine=click_element,
                name="click_element",
                description="Click a button or link on the user's current page.",
                args_schema=ClickArgs,
            ),
            StructuredTool.from_function(
                coroutine=read_form,
                name="read_form",
                description="Read the current values of all fields in a form on the user's page.",
                args_schema=ReadFormArgs,
            ),
            StructuredTool.from_function(
                coroutine=highlight_element,
                name="highlight_element",
                description="Highlight an element on the user's page (scroll + outline).",
                args_schema=HighlightArgs,
            ),
            StructuredTool.from_function(
                coroutine=navigate_to,
                name="navigate_to",
                description=(
                    "Navigate the user's current page to a new URL. "
                    "Check the 'soft' field in the result: "
                    "soft=true means you can continue calling tools, "
                    "soft=false means page reloaded and you must stop."
                ),
                args_schema=NavigateArgs,
            ),
            StructuredTool.from_function(
                coroutine=get_page_info,
                name="get_page_info",
                description=(
                    "Get the user's current page URL and available forms. "
                    "Call this BEFORE filling forms or navigating to check where the user is."
                ),
                args_schema=NoArgs,
            ),
        ]
        return tools
