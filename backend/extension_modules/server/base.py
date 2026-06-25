"""
Server Connector Base Module

워크스페이스 도구의 서버 연결을 위한 추상 베이스 클래스.
OpenAPI 및 MCP 서버를 LangChain Tool로 변환하는 공통 인터페이스 제공.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional

from langchain_core.tools import StructuredTool


@dataclass
class ToolSpec:
    """서버에서 제공하는 도구 스펙"""

    name: str
    description: str
    parameters: dict  # JSON Schema 형식
    metadata: Optional[dict] = None


class ServerConnector(ABC):
    """서버 연결 추상 클래스"""

    def __init__(
        self,
        connection_config: dict,
        token_resolver: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    ):
        """
        Args:
            connection_config: 연결 설정 (type, url, auth 등)
            token_resolver: 호출마다 fresh access_token 을 반환하는 비동기 콜백
                (사용자별 OAuth 토큰 동적 주입용). 정적 auth (bearer/api_key) 와
                동시 사용 시 resolver 결과가 우선.
        """
        self.config = connection_config
        self._token_resolver = token_resolver
        self._tools_cache: Optional[List[ToolSpec]] = None

    @property
    def connection_type(self) -> str:
        """연결 타입 반환 (openapi, mcp)"""
        return self.config.get("type", "unknown")

    @property
    def is_enabled(self) -> bool:
        """연결 활성화 여부"""
        return self.config.get("enabled", False)

    @abstractmethod
    async def connect(self) -> bool:
        """
        서버 연결 테스트

        Returns:
            연결 성공 여부
        """
        pass

    @abstractmethod
    async def list_tools(self) -> List[ToolSpec]:
        """
        사용 가능한 도구 목록 조회

        Returns:
            도구 스펙 목록
        """
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> Any:
        """
        도구 호출

        Args:
            name: 도구 이름
            arguments: 도구 인자

        Returns:
            도구 실행 결과
        """
        pass

    def _create_tool_caller(self, tool_name: str) -> Callable:
        """
        도구 호출 함수 생성

        Args:
            tool_name: 도구 이름

        Returns:
            비동기 호출 함수
        """

        async def call(**kwargs) -> Any:
            return await self.call_tool(tool_name, kwargs)

        return call

    @abstractmethod
    def to_langchain_tools(self) -> List[StructuredTool]:
        """
        LangChain StructuredTool 목록으로 변환

        Returns:
            LangChain Tool 목록
        """
        pass

    async def __aenter__(self):
        """Context manager 진입"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager 종료"""
        pass  # 필요시 오버라이드


class ServerConnectorError(Exception):
    """서버 연결 오류"""

    pass
