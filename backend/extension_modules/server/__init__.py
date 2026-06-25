"""
Server Connector Module

워크스페이스 도구의 서버(OpenAPI, MCP)를 LangChain Tool로 변환하는 모듈.

Usage:
    from extension_modules.server import get_connector, get_langchain_tools

    # 방법 1: Factory 함수 사용
    connection_config = {"type": "mcp", "url": "...", "enabled": True}
    tools = await get_langchain_tools(connection_config)

    # 방법 2: Connector 직접 사용
    connector = get_connector(connection_config)
    async with connector:
        tools = await connector.get_langchain_tools()
        result = await connector.call_tool("tool_name", {"arg": "value"})
"""

from typing import Awaitable, Callable, List, Optional

from langchain_core.tools import StructuredTool

from .base import ServerConnector, ServerConnectorError, ToolSpec
from .langchain_adapter import (
    create_langchain_tool,
    create_langchain_tools_from_specs,
    json_schema_to_pydantic_model,
)
from .mcp_connector import MCPServerConnector
from .openapi_connector import OpenAPIServerConnector


def get_connector(
    connection_config: dict,
    token_resolver: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
) -> ServerConnector:
    """
    연결 설정에 따라 적절한 Connector 반환

    Args:
        connection_config: 연결 설정 딕셔너리
            - type: "openapi" 또는 "mcp"
            - url: 서버 URL
            - enabled: 활성화 여부
            - auth_type: 인증 타입 (none, bearer, api_key, oauth_microsoft, oauth_google)
            - key: 인증 키
            - headers: 추가 헤더 (MCP)
            - path: OpenAPI 스펙 경로 (OpenAPI)
        token_resolver: oauth_* auth_type 사용 시 호출마다 사용자 토큰을 반환
            하는 비동기 콜백.

    Returns:
        ServerConnector 인스턴스

    Raises:
        ServerConnectorError: 지원하지 않는 연결 타입
    """
    conn_type = connection_config.get("type", "").lower()

    if conn_type == "mcp":
        return MCPServerConnector(connection_config, token_resolver=token_resolver)
    elif conn_type == "openapi":
        return OpenAPIServerConnector(connection_config, token_resolver=token_resolver)
    else:
        raise ServerConnectorError(f"Unsupported connection type: {conn_type}")


async def get_langchain_tools(connection_config: dict) -> List[StructuredTool]:
    """
    연결 설정으로 LangChain Tool 목록 가져오기 (편의 함수)

    Args:
        connection_config: 연결 설정

    Returns:
        LangChain StructuredTool 목록

    Raises:
        ServerConnectorError: 연결 또는 도구 로드 실패
    """
    if not connection_config.get("enabled", False):
        return []

    connector = get_connector(connection_config)
    async with connector:
        return await connector.get_langchain_tools()


async def get_langchain_tools_from_tool_connection(
    tool_connection,
) -> List[StructuredTool]:
    """
    ToolConnection 모델에서 LangChain Tool 목록 가져오기

    Args:
        tool_connection: ToolConnectionModel 인스턴스

    Returns:
        LangChain StructuredTool 목록
    """
    if not tool_connection or not tool_connection.data:
        return []

    connection_config = tool_connection.data.get("connection", {})
    return await get_langchain_tools(connection_config)


__all__ = [
    # Base classes
    "ServerConnector",
    "ServerConnectorError",
    "ToolSpec",
    # Connectors
    "MCPServerConnector",
    "OpenAPIServerConnector",
    # Factory functions
    "get_connector",
    "get_langchain_tools",
    "get_langchain_tools_from_tool_connection",
    # Adapter utilities
    "create_langchain_tool",
    "create_langchain_tools_from_specs",
    "json_schema_to_pydantic_model",
]
