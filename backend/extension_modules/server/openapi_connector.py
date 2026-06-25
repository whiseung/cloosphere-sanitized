"""
OpenAPI Server Connector Module

OpenAPI 서버에 연결하고 LangChain Tool로 변환.
"""

import copy
import logging
from typing import Any, Dict, List, Optional

import aiohttp
import yaml
from langchain_core.tools import StructuredTool
from open_webui.env import AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA, SRC_LOG_LEVELS

from .base import ServerConnector, ServerConnectorError, ToolSpec
from .langchain_adapter import create_langchain_tools_from_specs

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("EXTENSION", logging.INFO))


class OpenAPIServerConnector(ServerConnector):
    """OpenAPI 서버 연결 및 LangChain Tool 변환"""

    def __init__(self, connection_config: dict, token_resolver=None):
        """
        Args:
            connection_config: OpenAPI 연결 설정
                - url: 서버 기본 URL
                - path: OpenAPI 스펙 경로 (기본: openapi.json)
                - auth_type: 인증 타입 (none, bearer, api_key)
                - key: 인증 키
                - spec: 인라인 OpenAPI 스펙(dict). 있으면 url/path fetch 대신 사용.
            token_resolver: 동적 토큰 주입 콜백 (현재 미활용 — 후속 작업).
        """
        super().__init__(connection_config, token_resolver=token_resolver)
        self._openapi_spec: Optional[dict] = None
        self._base_url = connection_config.get("url", "").rstrip("/")
        self._spec_path = connection_config.get("path", "openapi.json")
        # 인라인 스펙(붙여넣기/업로드) — 있으면 URL fetch 없이 그대로 사용.
        self._inline_spec = connection_config.get("spec")

    def _get_auth_headers(self) -> dict:
        """인증 헤더 생성"""
        headers = {}
        auth_type = self.config.get("auth_type", "none")
        key = self.config.get("key", "")

        if auth_type == "bearer" and key:
            headers["Authorization"] = f"Bearer {key}"
        elif auth_type == "api_key" and key:
            headers["X-API-Key"] = key

        return headers

    async def connect(self) -> bool:
        """OpenAPI 스펙 로드. 인라인 스펙이 있으면 fetch 없이 사용."""
        # 스펙 URL 이 인증 게이트 뒤에 있어 자동 fetch 가 불가한 경우
        # (붙여넣기/업로드) 인라인 스펙을 그대로 사용.
        if self._inline_spec:
            self._openapi_spec = self._inline_spec
            log.info("OpenAPI spec loaded from inline config")
            return True

        spec_url = f"{self._base_url}/{self._spec_path}"

        try:
            timeout = aiohttp.ClientTimeout(
                total=AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA
            )
            headers = {
                "Accept": "application/json",
                **self._get_auth_headers(),
            }

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(spec_url, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ServerConnectorError(
                            f"Failed to fetch OpenAPI spec: {response.status} - {error_text}"
                        )

                    # YAML 또는 JSON 파싱
                    if spec_url.lower().endswith((".yaml", ".yml")):
                        text_content = await response.text()
                        self._openapi_spec = yaml.safe_load(text_content)
                    else:
                        self._openapi_spec = await response.json()

            log.info(f"OpenAPI spec loaded from: {spec_url}")
            return True

        except aiohttp.ClientError as e:
            log.error(f"HTTP error fetching OpenAPI spec: {e}")
            raise ServerConnectorError(f"HTTP error: {e}")
        except Exception as e:
            log.exception(f"Error loading OpenAPI spec: {e}")
            raise ServerConnectorError(f"Failed to load OpenAPI spec: {e}")

    def _resolve_schema(
        self, schema: dict, components: dict, _seen: Optional[set] = None
    ) -> dict:
        """JSON Schema $ref 해결.

        _seen 은 현재 펼치는 중인 $ref 경로 집합. 순환 참조(자기참조 모델 등)를
        다시 만나면 무한 재귀 대신 얕은 placeholder 로 끊는다 — 순환 $ref 는
        유효한 OpenAPI 패턴이므로 크래시 없이 처리해야 한다.
        """
        if not schema:
            return {}
        if _seen is None:
            _seen = set()

        if "$ref" in schema:
            ref_path = schema["$ref"]
            # 이미 펼치는 중인 ref 면 순환 — 더 펼치지 않고 끊는다.
            if ref_path in _seen:
                return {"type": "object"}
            ref_parts = ref_path.strip("#/").split("/")
            resolved = components
            for part in ref_parts[1:]:  # 'components' 스킵
                resolved = resolved.get(part, {})
            return self._resolve_schema(resolved, components, _seen | {ref_path})

        resolved_schema = copy.deepcopy(schema)

        # 재귀적으로 내부 스키마 해결
        if "properties" in resolved_schema:
            for prop, prop_schema in resolved_schema["properties"].items():
                resolved_schema["properties"][prop] = self._resolve_schema(
                    prop_schema, components, _seen
                )

        if "items" in resolved_schema:
            resolved_schema["items"] = self._resolve_schema(
                resolved_schema["items"], components, _seen
            )

        return resolved_schema

    def _convert_openapi_to_tool_specs(self) -> List[ToolSpec]:
        """OpenAPI 스펙을 ToolSpec 목록으로 변환"""
        if not self._openapi_spec:
            return []

        tool_specs = []
        components = self._openapi_spec.get("components", {})

        for path, methods in self._openapi_spec.get("paths", {}).items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue

                operation_id = operation.get("operationId")
                if not operation_id:
                    continue

                description = operation.get(
                    "description", operation.get("summary", f"{method.upper()} {path}")
                )

                parameters = {"type": "object", "properties": {}, "required": []}

                # Path/Query 파라미터 추출
                for param in operation.get("parameters", []):
                    param_name = param["name"]
                    param_schema = param.get("schema", {"type": "string"})
                    parameters["properties"][param_name] = {
                        "type": param_schema.get("type", "string"),
                        "description": param.get("description", ""),
                    }
                    if param.get("required"):
                        parameters["required"].append(param_name)

                # RequestBody 추출
                request_body = operation.get("requestBody")
                if request_body:
                    content = request_body.get("content", {})
                    json_schema = content.get("application/json", {}).get("schema")
                    if json_schema:
                        resolved_schema = self._resolve_schema(json_schema, components)

                        if resolved_schema.get("properties"):
                            parameters["properties"].update(
                                resolved_schema["properties"]
                            )
                            if "required" in resolved_schema:
                                parameters["required"] = list(
                                    set(
                                        parameters["required"]
                                        + resolved_schema["required"]
                                    )
                                )
                        elif resolved_schema.get("type") == "array":
                            parameters = resolved_schema

                tool_specs.append(
                    ToolSpec(
                        name=operation_id,
                        description=description,
                        parameters=parameters,
                        metadata={
                            "source": "openapi",
                            "path": path,
                            "method": method,
                        },
                    )
                )

        return tool_specs

    async def list_tools(self) -> List[ToolSpec]:
        """OpenAPI 스펙에서 도구 목록 추출"""
        if self._tools_cache is not None:
            return self._tools_cache

        if not self._openapi_spec:
            await self.connect()

        self._tools_cache = self._convert_openapi_to_tool_specs()
        return self._tools_cache

    def _find_operation(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """operationId로 operation 찾기"""
        if not self._openapi_spec:
            return None

        for path, methods in self._openapi_spec.get("paths", {}).items():
            for method, operation in methods.items():
                if (
                    isinstance(operation, dict)
                    and operation.get("operationId") == operation_id
                ):
                    return {
                        "path": path,
                        "method": method,
                        "operation": operation,
                    }
        return None

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """OpenAPI 도구 호출"""
        if not self._openapi_spec:
            await self.connect()

        op_info = self._find_operation(name)
        if not op_info:
            return f"Error: Operation '{name}' not found"

        path = op_info["path"]
        method = op_info["method"].lower()
        operation = op_info["operation"]

        # URL 구성
        final_url = f"{self._base_url}{path}"

        # 파라미터 분류
        path_params = {}
        query_params = {}
        body_params = {}

        for param in operation.get("parameters", []):
            param_name = param["name"]
            param_in = param["in"]
            if param_name in arguments:
                if param_in == "path":
                    path_params[param_name] = arguments[param_name]
                elif param_in == "query":
                    query_params[param_name] = arguments[param_name]

        # Path 파라미터 치환
        for key, value in path_params.items():
            final_url = final_url.replace(f"{{{key}}}", str(value))

        # Query 파라미터 추가
        if query_params:
            query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
            final_url = f"{final_url}?{query_string}"

        # Body 파라미터
        if operation.get("requestBody", {}).get("content"):
            # path/query 파라미터 제외한 나머지를 body로
            param_names = {p["name"] for p in operation.get("parameters", [])}
            body_params = {k: v for k, v in arguments.items() if k not in param_names}

        headers = {
            "Content-Type": "application/json",
            **self._get_auth_headers(),
        }

        try:
            async with aiohttp.ClientSession() as session:
                request_method = getattr(session, method)

                if method in ["post", "put", "patch"]:
                    async with request_method(
                        final_url, json=body_params, headers=headers
                    ) as response:
                        if response.status >= 400:
                            text = await response.text()
                            return f"Error: HTTP {response.status} - {text}"
                        return await response.json()
                else:
                    async with request_method(final_url, headers=headers) as response:
                        if response.status >= 400:
                            text = await response.text()
                            return f"Error: HTTP {response.status} - {text}"
                        return await response.json()

        except aiohttp.ClientError as e:
            log.error(f"HTTP error calling OpenAPI tool: {e}")
            return f"Error: {e}"
        except Exception as e:
            log.exception(f"Error calling OpenAPI tool: {e}")
            return f"Error: {e}"

    def to_langchain_tools(self) -> List[StructuredTool]:
        """OpenAPI 도구를 LangChain Tool로 변환"""
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
        if not self._openapi_spec:
            await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager 종료"""
        pass
