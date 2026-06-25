"""
Keep-alive utility for long-running operations.

Azure App Service 등 클라우드 환경에서 유휴 타임아웃으로 인한
Socket.IO/SSE 연결 끊김을 방지하기 위해, 긴 작업 중 주기적으로
heartbeat 이벤트를 전송합니다.

Usage:
    async with KeepAlive(event_emitter, "Searching memory..."):
        result = await long_running_operation()
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger(__name__)

# 기본 heartbeat 전송 간격 (초)
DEFAULT_INTERVAL = 15


class KeepAlive:
    """
    비동기 context manager: 긴 작업 중 주기적으로 status 이벤트를 전송합니다.

    Args:
        event_emitter: Socket.IO event emitter 함수 (async callable)
        description: 사용자에게 표시할 상태 메시지
        interval: heartbeat 전송 간격 (초, 기본 15초)
    """

    def __init__(
        self,
        event_emitter: Optional[Callable[..., Coroutine[Any, Any, Any]]],
        description: str = "Processing...",
        interval: int = DEFAULT_INTERVAL,
        detail: Optional[str] = None,
    ):
        self._event_emitter = event_emitter
        self._description = description
        self._detail = detail if detail is not None else description
        self._interval = interval
        self._task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        if self._event_emitter and self._interval > 0:
            self._task = asyncio.create_task(self._heartbeat())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return False

    async def _heartbeat(self):
        """주기적으로 status 이벤트 전송"""
        try:
            while True:
                await asyncio.sleep(self._interval)
                try:
                    await self._event_emitter(
                        {
                            "type": "status",
                            "data": {
                                "description": self._description,
                                "done": False,
                                "detail": self._detail,
                            },
                        }
                    )
                except Exception as e:
                    log.debug(f"Keep-alive heartbeat failed: {e}")
                    break
        except asyncio.CancelledError:
            pass
