"""
Knowledge Base 파일 필터 메타데이터 AI 추출 모듈.

파일 내용을 분석하여 filter_schema에 정의된 메타데이터를 LLM으로 자동 추출합니다.
"""

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage

log = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 4000

EXTRACTION_PROMPT = """다음 문서 내용을 분석하여 요청된 메타데이터를 추출해주세요.

--- 파일 제목 ---
{filename}

--- 문서 내용 ---
{content}
--- 끝 ---

추출할 항목:
{fields}

반드시 JSON 객체로만 응답하세요. 다른 텍스트는 포함하지 마세요.
응답 형식: {example}
"""


def _build_field_description(field: dict) -> str:
    """필터 필드 하나에 대한 프롬프트 설명 문자열 생성."""
    slot = field["slot"]
    label = field.get("label", slot)
    field_type = field.get("type", "string")
    extraction_prompt = field.get("extraction_prompt", "")
    options = field.get("options", [])

    required = field.get("required", False)
    required_hint = ", required: true" if required else ""

    parts = [f'slot: "{slot}", label: "{label}", type: "{field_type}"{required_hint}']

    if required:
        parts.append("이 항목은 필수입니다. 문서에서 찾을 수 없으면 null로 응답하세요")

    if field_type == "enum" and options:
        parts.append(f"options: {json.dumps(options, ensure_ascii=False)}")
        parts.append("반드시 options 중 하나를 선택하세요")

    if field_type == "collection" and options:
        parts.append(f"options: {json.dumps(options, ensure_ascii=False)}")
        parts.append("해당하는 값을 모두 선택하여 JSON 배열로 반환하세요")

    if field_type == "int":
        parts.append("숫자로 추출하세요")

    if field_type == "date":
        parts.append("YYYY-MM-DD 형식으로 추출하세요")

    if extraction_prompt:
        parts.append(f"지시사항: {extraction_prompt}")

    return "{" + ", ".join(parts) + "}"


def _validate_value(value: Any, field: dict) -> Optional[Any]:
    """추출된 값을 필드 타입에 맞게 검증/변환."""
    if value is None or value == "":
        return None

    field_type = field.get("type", "string")
    options = field.get("options", [])

    if field_type == "collection" and options:
        # Multi-value: LLM returns a list, validate each against options
        values = value if isinstance(value, list) else [value]
        validated = []
        for v in values:
            str_v = str(v).strip()
            matched = None
            for opt in options:
                if opt == str_v:
                    matched = opt
                    break
            if not matched:
                for opt in options:
                    if opt.lower() == str_v.lower():
                        matched = opt
                        break
            if not matched:
                for opt in options:
                    if str_v.lower() in opt.lower() or opt.lower() in str_v.lower():
                        matched = opt
                        break
            if matched and matched not in validated:
                validated.append(matched)
        return validated if validated else None

    if field_type == "enum" and options:
        str_value = str(value).strip()
        # 정확히 일치하는 옵션 찾기
        for opt in options:
            if opt == str_value:
                return opt
        # 대소문자 무시 매칭
        for opt in options:
            if opt.lower() == str_value.lower():
                return opt
        # 부분 매칭
        for opt in options:
            if str_value.lower() in opt.lower() or opt.lower() in str_value.lower():
                return opt
        return None

    if field_type == "int":
        try:
            # 문자열에서 숫자 추출
            if isinstance(value, (int, float)):
                return int(value)
            match = re.search(r"-?\d+", str(value))
            if match:
                return int(match.group())
            return None
        except (ValueError, TypeError):
            return None

    if field_type == "date":
        str_value = str(value).strip()
        # YYYY-MM-DD 패턴 매칭
        match = re.search(r"\d{4}-\d{2}-\d{2}", str_value)
        if match:
            return match.group()
        return None

    # string 타입은 그대로
    return str(value).strip() if value else None


def _parse_json_response(response_text) -> dict:
    """LLM 응답에서 JSON 객체 파싱."""
    # LangChain AIMessage.content는 str 또는 list[dict] (멀티파트 응답)
    if isinstance(response_text, list):
        # 텍스트 부분만 추출
        text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in response_text
        ).strip()
    else:
        text = str(response_text).strip()

    # ```json ... ``` 또는 ``` ... ``` 제거
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # { ... } 블록 추출 시도
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


async def extract_file_metadata(
    app,
    file_content: str,
    filter_schema: list[dict],
    model_id: str = "",
    model_config: Optional[dict] = None,
    filename: str = "",
) -> dict[str, Any]:
    """
    LLM을 사용하여 파일 내용에서 필터 메타데이터를 추출합니다.

    Args:
        app: FastAPI application
        file_content: 파일 텍스트 내용
        filter_schema: 필터 스키마 목록 (extraction_prompt가 있는 항목만 처리)
        model_id: 사용할 LLM 모델 ID (model_config 없을 때 사용)
        model_config: 미리 resolve된 모델 설정 (백그라운드 태스크용)
        filename: 파일 제목 (추출 프롬프트에서 참조)

    Returns:
        dict: {slot_name: extracted_value, ...}
    """
    from extension_modules.utils.llm import create_llm, create_llm_from_app

    # extraction_prompt가 있는 필터만 추출 대상
    target_fields = [f for f in filter_schema if f.get("extraction_prompt", "").strip()]

    if not target_fields:
        return {}

    # LLM 생성: model_config가 있으면 직접 사용, 없으면 app에서 조회
    llm = None
    if model_config:
        llm = create_llm(model_config, json_mode=True, temperature=0.1)
    elif model_id:
        llm = create_llm_from_app(app, model_id, json_mode=True, temperature=0.1)

    if not llm:
        log.error(f"Failed to create LLM for model: {model_id or model_config}")
        return {}

    # 파일 내용 자르기
    truncated_content = file_content[:MAX_CONTENT_CHARS]
    if len(file_content) > MAX_CONTENT_CHARS:
        truncated_content += "\n... (truncated)"

    # 필드 설명 구성
    field_descriptions = []
    example_obj = {}
    for i, field in enumerate(target_fields, 1):
        field_descriptions.append(f"{i}. {_build_field_description(field)}")
        example_obj[field["slot"]] = f"<{field.get('label', field['slot'])}>"

    prompt = EXTRACTION_PROMPT.format(
        filename=filename or "(제목 없음)",
        content=truncated_content,
        fields="\n".join(field_descriptions),
        example=json.dumps(example_obj, ensure_ascii=False),
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        raw_result = _parse_json_response(response.content)

        if not raw_result:
            log.warning("Failed to parse LLM response for metadata extraction")
            return {}

        # 값 검증 및 변환 — 모든 target field에 대해 결과 포함
        # 추출되지 않은 필드도 None으로 포함하여 기존 수동 입력값을 덮어씀
        validated = {}
        for field in target_fields:
            slot = field["slot"]
            if slot in raw_result:
                validated_value = _validate_value(raw_result[slot], field)
                validated[slot] = validated_value  # None이어도 포함
            else:
                validated[slot] = None  # LLM이 응답하지 않은 필드도 명시적 None

        log.info(f"Extracted metadata: {validated}")
        return validated

    except Exception as e:
        log.exception(f"Error extracting metadata via LLM: {e}")
        return {}
