"""
Knowledge Filter Builder

KB meta의 filter_schema + 사용자 필터값 → Azure AI Search OData 필터 문자열 생성.

Usage:
    from extension_modules.search_engine.filter_builder import build_knowledge_filter

    odata_filter = build_knowledge_filter(
        collection_ids=["kb-id-1", "kb-id-2"],
        filter_schema=[
            {"label": "부서",  "slot": "f_str_1",  "type": "enum", "options": ["재무팀", "개발팀", "인사팀"]},
            {"label": "작성일", "slot": "f_date_1", "type": "date"},
            {"label": "연도",  "slot": "f_int_1",  "type": "int"},
        ],
        filter_values={"부서": "재무팀", "연도": 2024},
    )
    # → "collection eq 'kb-id-1' and f_str_1 eq '재무팀' and f_int_1 eq 2024"
"""

import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def build_knowledge_filter(
    collection_ids: List[str],
    filter_schema: List[Dict[str, Any]],
    filter_values: Dict[str, Any],
) -> str:
    """
    collection 필터 + 사용자 정의 필터 → OData 필터 문자열 생성.

    Args:
        collection_ids: 검색 대상 knowledge_id 목록
        filter_schema: KB meta.filter_schema 리스트
                       [{"label": "부서", "slot": "f_str_1", "type": "string"}, ...]
        filter_values: LLM이 추출한 필터값 {"부서": "재무팀", "연도": 2024}

    Returns:
        OData 필터 문자열. 필터 없으면 collection 필터만 반환.
    """
    parts = []

    # 1. collection 필터
    if collection_ids:
        if len(collection_ids) == 1:
            parts.append(f"collection eq '{_escape(collection_ids[0])}'")
        else:
            col_parts = " or ".join(
                f"collection eq '{_escape(c)}'" for c in collection_ids
            )
            parts.append(f"({col_parts})")

    # 2. 사용자 정의 필터
    if filter_schema and filter_values:
        label_to_field = {item["label"]: item for item in filter_schema}
        # Slot 중복 가드 (F1) — 같은 slot 이 여러 label 에 매핑되면 첫 적용만 통과.
        # 두 번째 이상은 OData filter 에서 AND 충돌 (`f_str_1 eq A AND f_str_1 eq B`)
        # 을 일으켜 결과 0건이 됨.
        used_slots: set[str] = set()
        for label, value in filter_values.items():
            if label not in label_to_field:
                continue
            field = label_to_field[label]
            slot = field.get("slot", "")
            ftype = field.get("type", "string")
            if not slot or value is None or value == "":
                continue
            if slot in used_slots:
                log.warning(
                    "[build_knowledge_filter] slot '%s' already used by another label; "
                    "skipping label=%r value=%r to avoid AND-conflict",
                    slot,
                    label,
                    value,
                )
                continue

            odata_expr = _build_field_filter(slot, ftype, value)
            if odata_expr:
                parts.append(odata_expr)
                used_slots.add(slot)

    return " and ".join(parts)


def _build_field_filter(slot: str, ftype: str, value: Any) -> Optional[str]:
    """단일 필드 OData 표현식 생성"""
    if ftype in ("enum", "string"):  # enum/string 모두 eq 비교 (f_str_* 슬롯)
        escaped = _escape(str(value))
        return f"{slot} eq '{escaped}'"

    elif ftype == "int":
        try:
            int_val = int(value)
            return f"{slot} eq {int_val}"
        except (ValueError, TypeError):
            return None

    elif ftype == "date":
        return _build_date_filter(slot, value)

    elif ftype == "glossary":
        # Glossary terms stored as collection (multi-value) — reuse collection logic
        return _build_field_filter(slot, "collection", value)

    elif ftype == "collection":
        # Collection (multi-value): any() lambda for OData
        if isinstance(value, list):
            # Multiple values → OR inside any()
            conditions = [
                f"{slot}/any(x: x eq '{_escape(str(v))}')" for v in value if v
            ]
            if not conditions:
                return None
            if len(conditions) == 1:
                return conditions[0]
            return "(" + " and ".join(conditions) + ")"
        else:
            escaped = _escape(str(value))
            return f"{slot}/any(x: x eq '{escaped}')"

    return None


def _build_date_filter(slot: str, value: Any) -> Optional[str]:
    """날짜 필터 OData 표현식 생성.

    지원 형식:
    - 4자리 연도 (예: 2024) → 해당 연도 전체 범위
    - YYYY-MM (예: "2024-03") → 해당 월 범위
    - YYYY-MM-DD (예: "2024-03-15") → 해당 날 범위
    - ISO 8601 datetime → 정확한 날짜시간
    """
    str_val = str(value).strip()

    # 4자리 연도
    if re.match(r"^\d{4}$", str_val):
        year = int(str_val)
        return f"{slot} ge {year}-01-01T00:00:00Z and {slot} le {year}-12-31T23:59:59Z"

    # YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", str_val):
        import calendar

        parts = str_val.split("-")
        year, month = int(parts[0]), int(parts[1])
        last_day = calendar.monthrange(year, month)[1]
        return (
            f"{slot} ge {year:04d}-{month:02d}-01T00:00:00Z"
            f" and {slot} le {year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"
        )

    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", str_val):
        return f"{slot} ge {str_val}T00:00:00Z and {slot} le {str_val}T23:59:59Z"

    # ISO datetime (as-is)
    if "T" in str_val and "Z" in str_val:
        return f"{slot} eq {str_val}"

    return None


def _escape(value: str) -> str:
    """OData 문자열 값에서 단따옴표 이스케이프"""
    return value.replace("'", "''")


def build_filter_description(filter_schema: List[Dict[str, Any]]) -> str:
    """
    filter_schema → LLM용 필터 설명 문자열 생성.

    Args:
        filter_schema: KB meta.filter_schema 리스트

    Returns:
        사용 가능한 필터 목록 설명 문자열
    """
    if not filter_schema:
        return ""

    type_map = {
        "enum": "선택값",
        "string": "문자열",
        "int": "숫자",
        "date": "날짜",
        "collection": "다중값",
        "glossary": "용어집",
    }
    items = []
    for field in filter_schema:
        label = field.get("label", "")
        ftype = field.get("type", "string")
        type_name = type_map.get(ftype, ftype)
        fdesc = field.get("description", "").strip()
        options = field.get("options") or []
        entry = f"{label}({type_name})"
        if ftype == "glossary":
            glossary_name = field.get("glossary_name", "")
            if glossary_name:
                entry += (
                    f": 용어집 '{glossary_name}'에서 매칭된 용어들 (복수 선택 가능)"
                )
            elif fdesc:
                entry += f": {fdesc}"
        elif ftype == "enum" and options:
            # enum은 선택 가능한 값 목록을 명시 → LLM이 정확한 값을 선택할 수 있도록 함
            entry += f": {', '.join(str(o) for o in options)} 중 하나"
        elif ftype == "collection" and options:
            entry += (
                f": {', '.join(str(o) for o in options)} 중 하나 이상 (복수 선택 가능)"
            )
        elif fdesc:
            entry += f": {fdesc}"
        items.append(entry)

    return "사용 가능한 검색 필터:\n" + "\n".join(f"- {item}" for item in items)
