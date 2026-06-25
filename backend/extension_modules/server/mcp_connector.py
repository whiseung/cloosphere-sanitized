"""
MCP Server Connector Module

MCP (Model Context Protocol) 서버에 연결하고 LangChain Tool로 변환.
"""

import logging
from typing import Any, Awaitable, Callable, List, Optional

from langchain_core.tools import StructuredTool
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.mcp_client import MCPClient, MCPClientError

from .base import ServerConnector, ServerConnectorError, ToolSpec
from .langchain_adapter import create_langchain_tools_from_specs

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("EXTENSION", logging.INFO))


def _mcp_tool_metadata(tool: Any) -> dict:
    """MCP Tool → ToolSpec.metadata.

    도구가 선언한 annotations(readOnlyHint/destructiveHint)를 추출해 둔다.
    classify_tool_action 이 이름 휴리스틱보다 우선해 이 값을 쓴다(선언된 경우).
    softeria M365 처럼 annotation 이 없는 서버는 그대로 이름 휴리스틱으로 폴백.
    """
    md: dict = {"source": "mcp"}
    ann = getattr(tool, "annotations", None)
    if ann is not None:
        ro = getattr(ann, "readOnlyHint", None)
        de = getattr(ann, "destructiveHint", None)
        if ro is not None:
            md["readOnlyHint"] = ro
        if de is not None:
            md["destructiveHint"] = de
    return md


class MCPServerConnector(ServerConnector):
    """MCP 서버 연결 및 LangChain Tool 변환"""

    def __init__(
        self,
        connection_config: dict,
        token_resolver: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    ):
        """
        Args:
            connection_config: MCP 연결 설정
                - url: MCP 서버 URL
                - auth_type: 인증 타입 (none, bearer, api_key, oauth_microsoft, oauth_google)
                - key: 인증 키 (bearer/api_key 모드)
                - headers: 추가 헤더
            token_resolver: 호출마다 fresh access_token 반환하는 비동기 콜백
                (oauth_* 모드에서 사용자별 토큰 동적 주입).
        """
        super().__init__(connection_config, token_resolver=token_resolver)
        self._client: MCPClient | None = None
        self._initialized = False

    async def connect(self) -> bool:
        """MCP 서버 연결 테스트 (initialize 호출)"""
        try:
            self._client = MCPClient(self.config, token_resolver=self._token_resolver)
            await self._client.initialize()
            self._initialized = True
            log.info(f"MCP server connected: {self.config.get('url')}")
            return True
        except MCPClientError as e:
            log.error(f"MCP connection failed: {e}")
            raise ServerConnectorError(f"MCP connection failed: {e}")
        except Exception as e:
            log.exception(f"Unexpected error connecting to MCP server: {e}")
            raise ServerConnectorError(f"MCP connection error: {e}")

    async def list_tools(self) -> List[ToolSpec]:
        """MCP 서버에서 도구 목록 조회. connection_config.enabled_tools (이름 배열)
        이 비어있지 않으면 그 안에 포함된 도구만 통과 — admin 이 화이트리스트로
        LLM 노출 도구를 제한하는 용도. 빈 배열/미지정이면 전체 노출."""
        if self._tools_cache is not None:
            return self._tools_cache

        if not self._client:
            self._client = MCPClient(self.config, token_resolver=self._token_resolver)

        try:
            mcp_tools = await self._client.list_tools()
            enabled = self.config.get("enabled_tools")
            allow: set | None = None
            if isinstance(enabled, list) and enabled:
                allow = {name for name in enabled if isinstance(name, str)}
            self._tools_cache = [
                ToolSpec(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.input_schema,
                    metadata=_mcp_tool_metadata(tool),
                )
                for tool in mcp_tools
                if allow is None or tool.name in allow
            ]
            return self._tools_cache
        except MCPClientError as e:
            log.error(f"Failed to list MCP tools: {e}")
            raise ServerConnectorError(f"Failed to list MCP tools: {e}")

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """MCP 도구 호출"""
        if not self._client:
            self._client = MCPClient(self.config, token_resolver=self._token_resolver)

        try:
            result = await self._client.call_tool(name, arguments)

            # MCP 응답 형식 처리
            content = result.get("content", [])
            is_error = result.get("isError", False)

            # content가 배열이면 텍스트만 추출
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                content = "\n".join(text_parts) if text_parts else content

            if is_error:
                return f"Error: {content}"

            return content

        except MCPClientError as e:
            log.error(f"MCP tool call failed: {e}")
            return f"Error: {e}"
        except Exception as e:
            log.exception(f"Unexpected error calling MCP tool: {e}")
            return f"Error: {e}"

    def to_langchain_tools(self) -> List[StructuredTool]:
        """MCP 도구를 LangChain Tool로 변환"""
        if self._tools_cache is None:
            raise ServerConnectorError("Tools not loaded. Call list_tools() first.")

        specs = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools_cache
        ]

        def call_func_factory(tool_name: str):
            async def call(**kwargs) -> Any:
                return await self.call_tool(tool_name, kwargs)

            return call

        return create_langchain_tools_from_specs(specs, call_func_factory)

    async def get_langchain_tools(self) -> List[StructuredTool]:
        """
        도구 목록 조회 후 LangChain Tool로 변환 (편의 메서드)

        Returns:
            LangChain StructuredTool 목록
        """
        await self.list_tools()
        return self.to_langchain_tools()

    async def __aenter__(self):
        """Context manager 진입"""
        if not self._initialized:
            await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager 종료"""
        # MCP HTTP는 stateless이므로 정리 불필요
        pass
