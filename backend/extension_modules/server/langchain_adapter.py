"""
LangChain Adapter Module

도구 스펙을 LangChain StructuredTool로 변환하는 유틸리티.
"""

import inspect
from typing import Any, Callable, Dict, List, Optional, Type

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model


def json_schema_to_pydantic_field(name: str, schema: dict) -> tuple[Type, Any]:
    """
    JSON Schema 속성을 Pydantic Field로 변환

    Args:
        name: 필드 이름
        schema: JSON Schema 속성

    Returns:
        (타입, Field) 튜플
    """
    json_type = schema.get("type", "string")
    description = schema.get("description", "")
    default = schema.get("default", ...)

    # JSON Schema 타입 → Python 타입 매핑
    type_mapping = {
        "string": str,
        "str": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    python_type = type_mapping.get(json_type, str)

    # enum 처리
    if "enum" in schema:
        # Literal 사용 가능하지만 단순화를 위해 str 유지
        pass

    # nullable 처리
    if schema.get("nullable", False):
        python_type = Optional[python_type]

    if default is ...:
        return (python_type, Field(description=description))
    else:
        return (python_type, Field(default=default, description=description))


def json_schema_to_pydantic_model(name: str, parameters: dict) -> Type[BaseModel]:
    """
    JSON Schema parameters를 Pydantic 모델로 변환

    Args:
        name: 모델 이름
        parameters: JSON Schema parameters 객체

    Returns:
        동적 생성된 Pydantic 모델 클래스
    """
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", []))

    field_definitions = {}

    for prop_name, prop_schema in properties.items():
        python_type, field = json_schema_to_pydantic_field(prop_name, prop_schema)

        # required가 아니면 Optional로 변경
        if prop_name not in required and field.default is ...:
            field = Field(default=None, description=field.description)
            if not str(python_type).startswith("typing.Optional"):
                python_type = Optional[python_type]

        field_definitions[prop_name] = (python_type, field)

    # 동적 모델 생성
    model = create_model(f"{name}Input", **field_definitions)
    return model


def create_langchain_tool(
    name: str,
    description: str,
    parameters: dict,
    call_func: Callable,
    return_direct: bool = False,
) -> StructuredTool:
    """
    도구 정보를 LangChain StructuredTool로 변환

    Args:
        name: 도구 이름
        description: 도구 설명
        parameters: JSON Schema 형식의 파라미터 정의
        call_func: 도구 호출 함수 (sync 또는 async)
        return_direct: 결과를 직접 반환할지 여부

    Returns:
        LangChain StructuredTool
    """
    # 파라미터가 없는 경우 빈 모델 생성
    if not parameters or not parameters.get("properties"):
        args_schema = create_model(f"{name}Input")
    else:
        args_schema = json_schema_to_pydantic_model(name, parameters)

    # 동기/비동기 함수 구분하여 적절한 파라미터 사용
    if inspect.iscoroutinefunction(call_func):
        tool = StructuredTool.from_function(
            coroutine=call_func,
            name=name,
            description=description or f"Tool: {name}",
            args_schema=args_schema,
            return_direct=return_direct,
        )
    else:
        tool = StructuredTool.from_function(
            func=call_func,
            name=name,
            description=description or f"Tool: {name}",
            args_schema=args_schema,
            return_direct=return_direct,
        )

    return tool


def create_langchain_tools_from_specs(
    specs: List[Dict[str, Any]],
    call_func_factory: Callable[[str], Callable],
) -> List[StructuredTool]:
    """
    도구 스펙 목록을 LangChain Tool 목록으로 변환

    Args:
        specs: 도구 스펙 목록 (name, description, parameters)
        call_func_factory: 도구 이름을 받아 호출 함수를 반환하는 팩토리

    Returns:
        LangChain StructuredTool 목록
    """
    tools = []

    for spec in specs:
        name = spec.get("name")
        if not name:
            continue

        description = spec.get("description", "")
        parameters = spec.get("parameters", {})

        call_func = call_func_factory(name)

        tool = create_langchain_tool(
            name=name,
            description=description,
            parameters=parameters,
            call_func=call_func,
        )
        tools.append(tool)

    return tools
