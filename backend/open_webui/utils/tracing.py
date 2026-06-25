"""
Tracing Utilities

LangSmith 스타일 트레이싱을 위한 컨텍스트 관리자 및 유틸리티.
요청 단위로 TraceContext를 생성하고, 중첩된 Run을 추적합니다.
"""

import contextvars
import logging
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Any, Callable, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.message_trace import (
    MessageTraceCreateForm,
    MessageTraces,
    RunStatus,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

# 비동기 태스크별 독립 스택 — 동시 도구 호출 시 공유 _run_stack 오염 방지
# asyncio.gather로 생성되는 각 Task는 contextvars를 복사하므로 태스크간 격리됨.
_trace_local_stack: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "_trace_local_stack", default=None
)


def _get_effective_stack(shared_stack: list[str]) -> list[str]:
    """로컬 스택(동시 도구 호출용)이 있으면 반환, 없으면 공유 스택 반환."""
    local = _trace_local_stack.get(None)
    return local if local is not None else shared_stack


def _truncate_data(data: Any, max_size: int = 0) -> Any:
    """데이터 반환 (잘림 없음 - 검증용으로 전체 데이터 저장)"""
    # max_size=0 이면 잘림 없이 전체 반환
    return data


class TraceRun:
    """개별 Run 추적 객체"""

    def __init__(
        self,
        trace_context: "TraceContext",
        run_id: str,
        run_type: str,
        name: str,
        parent_run_id: Optional[str] = None,
        dotted_order: str = "1",
    ):
        self.trace_context = trace_context
        self.run_id = run_id
        self.run_type = run_type
        self.name = name
        self.parent_run_id = parent_run_id
        self.dotted_order = dotted_order
        self.start_time = int(time.time() * 1000)

        self._inputs: Optional[dict] = None
        self._outputs: Optional[dict] = None
        self._token_usage: Optional[dict] = None
        self._error: Optional[str] = None
        self._model_id: Optional[str] = None
        self._meta: Optional[dict] = None

    def set_inputs(self, inputs: dict):
        """입력 데이터 설정"""
        self._inputs = _truncate_data(inputs, self.trace_context.inputs_max_size)

    def set_outputs(self, outputs: dict):
        """출력 데이터 설정"""
        self._outputs = _truncate_data(outputs, self.trace_context.inputs_max_size)

    def set_token_usage(self, usage: dict):
        """토큰 사용량 설정"""
        self._token_usage = usage

    def set_error(self, error: str):
        """에러 설정"""
        self._error = error

    def set_model_id(self, model_id: str):
        """모델 ID 설정"""
        self._model_id = model_id

    def set_meta(self, meta: dict):
        """메타데이터 설정"""
        self._meta = meta

    def complete(self, outputs: Optional[dict] = None, error: Optional[str] = None):
        """Run 완료 처리"""
        if outputs:
            self.set_outputs(outputs)
        if error:
            self.set_error(error)

        MessageTraces.complete_trace(
            trace_id=self.run_id,
            outputs=self._outputs,
            token_usage=self._token_usage,
            error=self._error,
        )


class TraceContext:
    """
    트레이스 컨텍스트 관리자

    하나의 사용자 요청에서 생성되는 모든 Run을 추적합니다.
    스택 구조로 parent_run_id를 관리하고, dotted_order를 자동 생성합니다.
    """

    def __init__(
        self,
        trace_id: str,
        user_id: str,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        enabled: bool = True,
        inputs_max_size: int = 10000,
    ):
        self.trace_id = trace_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.enabled = enabled
        self.inputs_max_size = inputs_max_size

        self._run_stack: list[str] = []  # parent_run_id 스택
        self._order_counters: dict[str, int] = {"root": 0}  # dotted_order 카운터

    def _get_next_order(self, parent_run_id: Optional[str]) -> str:
        """다음 dotted_order 생성.

        숫자를 3자리 zero-pad하여 문자열 정렬 시 올바른 순서 보장.
        예: "001", "002", ... "010", "011"
        """
        key = parent_run_id or "root"

        if key not in self._order_counters:
            self._order_counters[key] = 0

        self._order_counters[key] += 1
        counter = self._order_counters[key]

        padded = f"{counter:03d}"
        if parent_run_id:
            # 부모의 dotted_order 찾기
            parent_order = None
            for run_id, order in self._run_orders.items():
                if run_id == parent_run_id:
                    parent_order = order
                    break

            if parent_order:
                return f"{parent_order}.{padded}"

        return padded

    def _init_run_orders(self):
        """Run 순서 매핑 초기화"""
        if not hasattr(self, "_run_orders"):
            self._run_orders: dict[str, str] = {}

    @contextmanager
    def start_run(
        self,
        run_type: str,
        name: str,
        inputs: Optional[dict] = None,
        model_id: Optional[str] = None,
        meta: Optional[dict] = None,
        push_stack: bool = True,
    ):
        """
        Run 시작/종료 컨텍스트 매니저 (동기)

        Args:
            push_stack: True이면 실행 스택에 push하여 하위 run의 부모가 됨.
                        False이면 push하지 않음 (leaf 노드용, 동시 실행 시 안전).

        Usage:
            with trace_ctx.start_run("llm", "gpt-4") as run:
                run.set_inputs({"messages": [...]})
                response = await call_llm(...)
                run.set_outputs({"response": response})
                run.set_token_usage(usage)
        """
        if not self.enabled:
            yield None
            return

        self._init_run_orders()

        run_id = str(uuid.uuid4())
        stack = _get_effective_stack(self._run_stack)
        parent_run_id = stack[-1] if stack else None
        dotted_order = self._get_next_order(parent_run_id)

        self._run_orders[run_id] = dotted_order

        # DB에 trace 레코드 생성
        form_data = MessageTraceCreateForm(
            trace_id=self.trace_id,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
            chat_id=self.chat_id,
            message_id=self.message_id,
            user_id=self.user_id,
            run_type=run_type,
            name=name,
            status=RunStatus.RUNNING.value,
            inputs=_truncate_data(inputs, self.inputs_max_size) if inputs else None,
            model_id=model_id,
            meta=meta,
        )

        db_trace = MessageTraces.create_trace(form_data)

        if not db_trace:
            log.warning(f"Failed to create trace for run: {name}")
            yield None
            return

        run = TraceRun(
            trace_context=self,
            run_id=db_trace.id,
            run_type=run_type,
            name=name,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
        )

        if push_stack:
            stack.append(db_trace.id)

        try:
            yield run
        except Exception as e:
            run.set_error(str(e))
            raise
        finally:
            if push_stack:
                s = _get_effective_stack(self._run_stack)
                if s and s[-1] == db_trace.id:
                    s.pop()
            run.complete()

    @asynccontextmanager
    async def start_run_async(
        self,
        run_type: str,
        name: str,
        inputs: Optional[dict] = None,
        model_id: Optional[str] = None,
        meta: Optional[dict] = None,
        push_stack: bool = True,
    ):
        """
        Run 시작/종료 비동기 컨텍스트 매니저

        Args:
            push_stack: True이면 실행 스택에 push하여 하위 run의 부모가 됨.
                        False이면 push하지 않음 (leaf 노드용, 동시 실행 시 안전).

        Usage:
            async with trace_ctx.start_run_async("llm", "gpt-4") as run:
                run.set_inputs({"messages": [...]})
                response = await call_llm(...)
                run.set_outputs({"response": response})
        """
        if not self.enabled:
            yield None
            return

        self._init_run_orders()

        run_id = str(uuid.uuid4())
        stack = _get_effective_stack(self._run_stack)
        parent_run_id = stack[-1] if stack else None
        dotted_order = self._get_next_order(parent_run_id)

        self._run_orders[run_id] = dotted_order

        # DB에 trace 레코드 생성
        form_data = MessageTraceCreateForm(
            trace_id=self.trace_id,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
            chat_id=self.chat_id,
            message_id=self.message_id,
            user_id=self.user_id,
            run_type=run_type,
            name=name,
            status=RunStatus.RUNNING.value,
            inputs=_truncate_data(inputs, self.inputs_max_size) if inputs else None,
            model_id=model_id,
            meta=meta,
        )

        db_trace = MessageTraces.create_trace(form_data)

        if not db_trace:
            log.warning(f"Failed to create trace for run: {name}")
            yield None
            return

        run = TraceRun(
            trace_context=self,
            run_id=db_trace.id,
            run_type=run_type,
            name=name,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
        )

        if push_stack:
            stack.append(db_trace.id)

        try:
            yield run
        except Exception as e:
            run.set_error(str(e))
            raise
        finally:
            if push_stack:
                s = _get_effective_stack(self._run_stack)
                if s and s[-1] == db_trace.id:
                    s.pop()
            run.complete()

    def begin_run(
        self,
        run_type: str,
        name: str,
        inputs: Optional[dict] = None,
        model_id: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> Optional["TraceRun"]:
        """
        Run 수동 시작 (스트리밍 응답용)

        스트리밍 응답처럼 컨텍스트 매니저를 사용할 수 없는 경우,
        begin_run으로 시작하고 end_run으로 완료합니다.

        Usage:
            run = trace_ctx.begin_run("llm", "gpt-4", inputs={...})
            try:
                # 스트리밍 처리
                async for chunk in stream:
                    ...
            finally:
                trace_ctx.end_run(run, outputs={...})
        """
        if not self.enabled:
            return None

        self._init_run_orders()

        run_id = str(uuid.uuid4())
        stack = _get_effective_stack(self._run_stack)
        parent_run_id = stack[-1] if stack else None
        dotted_order = self._get_next_order(parent_run_id)

        self._run_orders[run_id] = dotted_order

        form_data = MessageTraceCreateForm(
            trace_id=self.trace_id,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
            chat_id=self.chat_id,
            message_id=self.message_id,
            user_id=self.user_id,
            run_type=run_type,
            name=name,
            status=RunStatus.RUNNING.value,
            inputs=_truncate_data(inputs, self.inputs_max_size) if inputs else None,
            model_id=model_id,
            meta=meta,
        )

        db_trace = MessageTraces.create_trace(form_data)

        if not db_trace:
            log.warning(f"Failed to create trace for run: {name}")
            return None

        run = TraceRun(
            trace_context=self,
            run_id=db_trace.id,
            run_type=run_type,
            name=name,
            parent_run_id=parent_run_id,
            dotted_order=dotted_order,
        )

        stack.append(db_trace.id)
        return run

    def end_run(
        self,
        run: Optional["TraceRun"],
        outputs: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        """
        Run 수동 완료 (스트리밍 응답용)

        begin_run으로 시작한 run을 완료합니다.
        """
        if run is None:
            return

        stack = _get_effective_stack(self._run_stack)
        if run.run_id in stack:
            stack.remove(run.run_id)

        run.complete(outputs=outputs, error=error)


def create_trace_context(
    user_id: str,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    enabled: bool = True,
    inputs_max_size: int = 10000,
) -> TraceContext:
    """TraceContext 생성 헬퍼"""
    return TraceContext(
        trace_id=str(uuid.uuid4()),
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        enabled=enabled,
        inputs_max_size=inputs_max_size,
    )


def get_trace_context(request) -> Optional[TraceContext]:
    """Request에서 TraceContext 가져오기"""
    return getattr(request.state, "trace_context", None)


def set_trace_context(request, trace_context: TraceContext):
    """Request에 TraceContext 설정"""
    request.state.trace_context = trace_context


def trace_run(
    run_type: str,
    name: Optional[str] = None,
    capture_inputs: bool = True,
    capture_outputs: bool = True,
):
    """
    함수 트레이싱 데코레이터

    Usage:
        @trace_run(RunType.TOOL, "web_search")
        async def search_web(query: str) -> dict:
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # request 객체 찾기
            request = None
            for arg in args:
                if hasattr(arg, "state"):
                    request = arg
                    break

            if "request" in kwargs:
                request = kwargs["request"]

            trace_ctx = get_trace_context(request) if request else None

            if not trace_ctx or not trace_ctx.enabled:
                return await func(*args, **kwargs)

            run_name = name or func.__name__

            inputs = None
            if capture_inputs:
                inputs = {
                    "args": [str(a) for a in args[:3]],  # 처음 3개 인자만
                    "kwargs": {k: str(v)[:200] for k, v in list(kwargs.items())[:5]},
                }

            async with trace_ctx.start_run_async(
                run_type, run_name, inputs=inputs
            ) as run:
                if run is None:
                    return await func(*args, **kwargs)

                result = await func(*args, **kwargs)

                if capture_outputs and result is not None:
                    if isinstance(result, dict):
                        run.set_outputs(result)
                    else:
                        run.set_outputs({"result": str(result)[:1000]})

                return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # request 객체 찾기
            request = None
            for arg in args:
                if hasattr(arg, "state"):
                    request = arg
                    break

            if "request" in kwargs:
                request = kwargs["request"]

            trace_ctx = get_trace_context(request) if request else None

            if not trace_ctx or not trace_ctx.enabled:
                return func(*args, **kwargs)

            run_name = name or func.__name__

            inputs = None
            if capture_inputs:
                inputs = {
                    "args": [str(a) for a in args[:3]],
                    "kwargs": {k: str(v)[:200] for k, v in list(kwargs.items())[:5]},
                }

            with trace_ctx.start_run(run_type, run_name, inputs=inputs) as run:
                if run is None:
                    return func(*args, **kwargs)

                result = func(*args, **kwargs)

                if capture_outputs and result is not None:
                    if isinstance(result, dict):
                        run.set_outputs(result)
                    else:
                        run.set_outputs({"result": str(result)[:1000]})

                return result

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
