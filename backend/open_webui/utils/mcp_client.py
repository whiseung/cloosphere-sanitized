"""
MCP (Model Context Protocol) Client

Streamable HTTP 및 SSE 방식으로 MCP 서버와 통신하는 클라이언트.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

import httpx
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("UTILS", logging.INFO))


@dataclass
class MCPTool:
    """MCP 서버에서 제공하는 도구 정보"""

    name: str
    description: str
    input_schema: dict


class MCPClientError(Exception):
    """MCP 클라이언트 오류"""

    pass


class MCPClient:
    """
    MCP 서버와 HTTP로 통신하는 클라이언트.

    지원 모드:
    - SSE 모드: URL이 /sse로 끝나면 (supergateway 등)
      - SSE 연결 유지하면서 POST /message로 요청, SSE로 응답 수신
    - Streamable HTTP 모드: 그 외 URL (mcp-proxy 등)
      - POST {url}: 모든 요청, 세션 ID 헤더로 관리
    """

    def __init__(
        self,
        connection_config: dict,
        token_resolver: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    ):
        """
        Args:
            connection_config: 연결 설정 (url, auth_type, key, headers).
            token_resolver: 호출마다 fresh access_token 을 반환하는 비동기 콜백.
                지정되면 매 요청 시 resolver() 결과로 Authorization 헤더가 동적
                갱신된다 (사용자별 OAuth 토큰 주입용). 만료 자동 갱신은 resolver
                책임. None 반환 시 Authorization 헤더가 제거된다.
        """
        self.url = connection_config.get("url", "")
        # 요청 타임아웃(초). 기본 30 (하위호환). 느린(생성형) MCP 도구는
        # connection_config 에 timeout 을 키워 지정 (예: {"timeout": 180}).
        try:
            self._timeout = float(connection_config.get("timeout") or 30)
        except (TypeError, ValueError):
            self._timeout = 30.0
        self._request_id = 0
        self._session_id: str | None = None
        self._endpoint_url: str | None = None
        self._initialized = False
        self._token_resolver = token_resolver

        # SSE 모드용
        self._sse_client: httpx.AsyncClient | None = None
        self._sse_response = None
        self._sse_task: asyncio.Task | None = None
        self._pending_responses: dict[int, asyncio.Future] = {}
        self._sse_connected = asyncio.Event()

        if not self.url:
            raise MCPClientError("MCP server URL is required")

        # SSE 모드 감지 (URL이 /sse로 끝나면)
        parsed = urlparse(self.url)
        self._is_sse_mode = parsed.path.rstrip("/").endswith("/sse")

        if self._is_sse_mode:
            base_path = parsed.path.rstrip("/")
            if base_path.endswith("/sse"):
                base_path = base_path[:-4]
            self._base_url = f"{parsed.scheme}://{parsed.netloc}{base_path}"
            self._sse_url = self.url
            log.info(f"MCP SSE mode: sse={self._sse_url}, base={self._base_url}")
        else:
            self._base_url = self.url
            log.info(f"MCP Streamable HTTP mode: url={self.url}")

        # Build headers with auth
        self.headers = dict(connection_config.get("headers", {}))
        auth_type = connection_config.get("auth_type", "none")
        key = connection_config.get("key", "")

        if auth_type == "bearer" and key:
            self.headers["Authorization"] = f"Bearer {key}"
        elif auth_type == "api_key" and key:
            self.headers["X-API-Key"] = key

    def _next_id(self) -> int:
        """다음 요청 ID 생성"""
        self._request_id += 1
        return self._request_id

    async def _resolve_headers(self) -> dict:
        """매 호출마다 fresh 헤더 빌드. token_resolver 가 있으면 그 결과로
        Authorization 을 덮어쓴다. 정적 self.headers (auth_type=bearer/api_key
        모드에서 박힌 것) 와 token_resolver 가 동시에 있으면 resolver 결과 우선."""
        out = dict(self.headers)
        if self._token_resolver is not None:
            try:
                token = await self._token_resolver()
            except Exception as e:
                log.warning(f"MCP token_resolver failed: {e}")
                token = None
            if token:
                out["Authorization"] = f"Bearer {token}"
            else:
                # 토큰 미해결 — 정적 Authorization 도 제거해 의도 안 한 인증 방지.
                out.pop("Authorization", None)
        return out

    async def _sse_listener(self) -> None:
        """SSE 스트림을 백그라운드에서 수신"""
        try:
            async for line in self._sse_response.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue

                    # endpoint URL 파싱 (세션 연결 시)
                    if data_str.startswith("/") or (
                        data_str.startswith("http") and "sessionId=" in data_str
                    ):
                        if "sessionId=" in data_str:
                            if data_str.startswith("/"):
                                self._endpoint_url = f"{self._base_url}{data_str}"
                            else:
                                self._endpoint_url = data_str
                            self._session_id = data_str.split("sessionId=")[1].split(
                                "&"
                            )[0]
                            log.info(
                                f"SSE endpoint: {self._endpoint_url}, sessionId: {self._session_id}"
                            )
                            self._sse_connected.set()
                        continue

                    # JSON-RPC 응답 파싱
                    try:
                        data = json.loads(data_str)
                        request_id = data.get("id")
                        if request_id and request_id in self._pending_responses:
                            future = self._pending_responses.pop(request_id)
                            if not future.done():
                                future.set_result(data)
                    except json.JSONDecodeError:
                        continue

        except asyncio.CancelledError:
            log.debug("SSE listener cancelled")
        except Exception as e:
            log.error(f"SSE listener error: {e}")
            # 모든 대기 중인 요청에 에러 전달
            for future in self._pending_responses.values():
                if not future.done():
                    future.set_exception(MCPClientError(f"SSE connection lost: {e}"))

    async def _connect_sse(self) -> None:
        """SSE 스트림에 연결하고 백그라운드 리스너 시작"""
        if not self._is_sse_mode:
            return

        log.info(f"Connecting to SSE stream: {self._sse_url}")

        self._sse_client = httpx.AsyncClient(timeout=None)  # SSE는 타임아웃 없음

        try:
            sse_headers = await self._resolve_headers()
            self._sse_response = await self._sse_client.send(
                self._sse_client.build_request(
                    "GET",
                    self._sse_url,
                    headers={
                        "Accept": "text/event-stream",
                        "Cache-Control": "no-cache",
                        **sse_headers,
                    },
                ),
                stream=True,
            )
            self._sse_response.raise_for_status()

            # 백그라운드 리스너 시작
            self._sse_task = asyncio.create_task(self._sse_listener())

            # endpoint URL을 받을 때까지 대기 (최대 10초)
            try:
                await asyncio.wait_for(self._sse_connected.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                raise MCPClientError("Timeout waiting for SSE endpoint")

        except httpx.HTTPStatusError as e:
            raise MCPClientError(f"SSE connection failed: {e.response.status_code}")
        except Exception as e:
            raise MCPClientError(f"SSE connection error: {str(e)}")

    async def _close_sse(self) -> None:
        """SSE 연결 종료"""
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None

        if self._sse_response:
            await self._sse_response.aclose()
            self._sse_response = None

        if self._sse_client:
            await self._sse_client.aclose()
            self._sse_client = None

    def _parse_sse_response(self, text: str, request_id: int) -> dict | None:
        """SSE 응답에서 JSON-RPC 결과 파싱 (Streamable HTTP용)"""
        result = None
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str:
                    try:
                        data = json.loads(data_str)
                        if data.get("id") == request_id:
                            result = data
                            break
                    except json.JSONDecodeError:
                        continue
        return result

    async def _send_request(self, method: str, params: dict) -> dict:
        """JSON-RPC 요청 전송"""
        request_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        if self._is_sse_mode:
            return await self._send_request_sse(request_id, request)
        else:
            return await self._send_request_streamable(request_id, request)

    async def _send_request_sse(self, request_id: int, request: dict) -> dict:
        """SSE 모드: POST로 요청하고 SSE 스트림에서 응답 대기"""
        if not self._endpoint_url:
            raise MCPClientError("SSE endpoint not initialized")

        # 응답 대기용 Future 생성
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_responses[request_id] = future

        try:
            req_headers = await self._resolve_headers()
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._endpoint_url,
                    json=request,
                    headers={
                        "Content-Type": "application/json",
                        **req_headers,
                    },
                )
                # 202 Accepted 또는 200 OK
                if response.status_code not in (200, 202):
                    raise MCPClientError(
                        f"HTTP error {response.status_code}: {response.text}"
                    )

            # SSE 스트림에서 응답 대기 (self._timeout 초)
            result = await asyncio.wait_for(future, timeout=self._timeout)

            if "error" in result:
                error = result["error"]
                raise MCPClientError(
                    error.get("message", f"MCP error code: {error.get('code')}")
                )

            return result.get("result", {})

        except asyncio.TimeoutError:
            self._pending_responses.pop(request_id, None)
            raise MCPClientError("Timeout waiting for response")
        except Exception:
            self._pending_responses.pop(request_id, None)
            raise

    async def _send_request_streamable(self, request_id: int, request: dict) -> dict:
        """Streamable HTTP 모드: POST 요청"""
        try:
            base_headers = await self._resolve_headers()
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                request_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    **base_headers,
                }

                if self._session_id:
                    request_headers["Mcp-Session-Id"] = self._session_id

                request_url = self.url
                if self._session_id:
                    separator = "&" if "?" in self.url else "?"
                    request_url = f"{self.url}{separator}sessionId={self._session_id}"

                response = await client.post(
                    request_url,
                    json=request,
                    headers=request_headers,
                )
                response.raise_for_status()

                # 세션 ID 저장
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id

                content_type = response.headers.get("content-type", "")

                if "text/event-stream" in content_type:
                    result = self._parse_sse_response(response.text, request_id)
                    if result is None:
                        raise MCPClientError("No valid response found in SSE stream")
                else:
                    result = response.json()

                if "error" in result:
                    error = result["error"]
                    raise MCPClientError(
                        error.get("message", f"MCP error code: {error.get('code')}")
                    )

                return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise MCPClientError(
                f"HTTP error {e.response.status_code}: {e.response.text}"
            )
        except httpx.RequestError as e:
            raise MCPClientError(f"Connection error: {str(e)}")
        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {str(e)}")

    async def initialize(self) -> dict:
        """MCP 서버 초기화"""
        if self._is_sse_mode and not self._endpoint_url:
            await self._connect_sse()

        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cloosphere", "version": "1.0.0"},
            },
        )
        self._initialized = True
        return result

    async def list_tools(self) -> list[MCPTool]:
        """사용 가능한 도구 목록 조회"""
        result = await self._send_request("tools/list", {})
        return [
            MCPTool(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {}),
            )
            for tool in result.get("tools", [])
        ]

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """도구 호출"""
        return await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_sse()


# MCP 프리셋
MCP_PRESETS = [
    {
        "id": "custom",
        "name": "Custom MCP Server",
        "description": "Connect to your own MCP server",
        "connection": {
            "type": "mcp",
            "url": "",
            "headers": {},
            "enabled": True,
        },
    },
    {
        "id": "groupware-demo",
        "name": "Groupware Demo",
        "description": "Demo groupware MCP server for interactive form filling and board queries",
        "connection": {
            "type": "mcp",
            "url": "http://localhost:5001/mcp",
            "headers": {},
            "enabled": True,
        },
    },
    {
        "id": "google-workspace",
        "name": "Google Workspace (Gmail · Calendar)",
        "description": (
            "Self-hosted Google Workspace MCP in external OAuth passthrough mode "
            "(services/GoogleWorkspaceMCP). Each user's own Google SSO token is "
            "injected per call — no key needed."
        ),
        "connection": {
            # 끝 슬래시 없는 /mcp 사용. /mcp/ 는 307 redirect 인데 MCPClient 는
            # POST redirect 를 따라가지 않아(follow_redirects=False) 연결이 깨진다.
            "type": "mcp",
            "url": "http://localhost:8000/mcp",
            "auth_type": "oauth_google",
            "headers": {},
            "enabled": True,
        },
    },
]
