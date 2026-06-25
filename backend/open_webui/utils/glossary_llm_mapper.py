"""LLM-aided 변환 룰 추론 + 적용.

Raw XLSX/CSV (예: 포트코드처럼 컬럼 합성·템플릿이 필요한 자료) 를 glossary entry 로
변환하는 deterministic 룰을 LLM 으로 추론한다. LLM 은 룰만 만들고 변환은 backend
의 순수 함수가 수행 — 결과 reproducibility + 보안 (eval 없음).

룰 스펙 (간결, JSON-safe):

```
{
  "mapping": {
    "term":        {"kind": "column", "source": "Place Name(English)", "transform": "title_case"},
    "synonyms":    {"kind": "concat_list", "sources": [
                       {"kind": "template", "template": "{CN}{Place}"},
                       {"kind": "column",   "source":  "Place"},
                       {"kind": "column",   "source":  "Place Name(English)"}
                   ]},
    "description": {"kind": "template", "template": "UN/LOCODE: {CN}{Place} ({Place Name(English)})"},
    "example":     {"kind": "constant", "value": ""},
    "category":    {"kind": "constant", "value": "포트코드"}
  },
  "rationale": "포트코드 표 — CN+Place 가 UN/LOCODE 5자리 코드..."
}
```

지원 spec kind:
- ``column``           — row[source]. 옵션 ``transform`` (title_case | upper | lower | trim).
- ``template``         — ``"{header}..."`` 안의 placeholder 가 row 의 컬럼 값으로 치환.
- ``constant``         — 고정값 (모든 row 에 동일).
- ``concat``           — sources 의 spec 들을 ``join`` 으로 합쳐 단일 string.
- ``concat_list``      — sources 의 spec 들을 각각 평가해 list of string (synonyms 용).
- ``split``            — row[source] 를 separator 로 분할 → list[str] (concat_list source 에서만 의미).
                         leaf spec. source 는 column 이름 (string) 만. separator 는 literal (정규식 X).
- ``skip``             — 해당 field 비움.

placeholder 안전: ``{<header_name>}`` 만 치환. 다른 패턴은 literal.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

log = logging.getLogger(__name__)

_VALID_KINDS = {
    "column",
    "template",
    "constant",
    "concat",
    "concat_list",
    "split",
    "skip",
}
_VALID_TRANSFORMS = {"title_case", "upper", "lower", "trim", "none"}
_FIELDS = ("term", "synonyms", "description", "example", "category")
_LIST_FIELDS = {"synonyms"}  # synonyms 는 list, 나머지는 string


# ============================================================
# Rule application
# ============================================================


def apply_rule(rule: dict, row: dict[str, Any]) -> dict:
    """단일 row 에 변환 룰 적용. 결과: GlossaryEntry-compatible dict."""
    mapping = rule.get("mapping") or {}
    entry: dict[str, Any] = {
        "term": "",
        "synonyms": [],
        "description": "",
        "example": "",
    }
    for field in _FIELDS:
        spec = mapping.get(field)
        if not spec:
            continue
        try:
            value = _eval_spec(spec, row)
        except Exception as e:
            log.warning("rule eval 실패 field=%s: %s", field, e)
            value = None
        if value is None:
            continue
        if field in _LIST_FIELDS:
            # synonyms — list of unique non-empty strings
            if isinstance(value, list):
                entry[field] = [str(v).strip() for v in value if str(v).strip()]
            elif isinstance(value, str) and value.strip():
                entry[field] = [value.strip()]
        else:
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value if v is not None)
            entry[field] = str(value).strip()

    if not entry.get("term"):
        return entry  # 호출자가 skip 처리
    # synonyms 에서 primary term 제거
    entry["synonyms"] = [
        s for s in entry.get("synonyms", []) if s and s != entry["term"]
    ]
    # category 는 위 루프에서 이미 평가됨. 빈 값이면 entry 에서 제거 (uncategorized).
    if not entry.get("category"):
        entry.pop("category", None)
    return entry


def _eval_spec(spec: Any, row: dict[str, Any]) -> Any:
    """단일 spec 평가. 결과 = string | list[string] | None."""
    if not isinstance(spec, dict):
        return None
    kind = spec.get("kind")
    if kind not in _VALID_KINDS:
        return None
    if kind == "skip":
        return None
    if kind == "constant":
        return spec.get("value", "")
    if kind == "column":
        source = spec.get("source")
        raw = row.get(source, "") if source else ""
        value = "" if raw is None else str(raw)
        transform = spec.get("transform") or "none"
        return _apply_transform(value, transform)
    if kind == "template":
        template = str(spec.get("template") or "")
        return _render_template(template, row)
    if kind == "concat":
        sources = spec.get("sources") or []
        joiner = spec.get("join", "")
        parts = [str(_eval_spec(s, row) or "") for s in sources]
        return joiner.join(p for p in parts if p)
    if kind == "concat_list":
        sources = spec.get("sources") or []
        out: list[str] = []
        for s in sources:
            v = _eval_spec(s, row)
            if isinstance(v, list):
                out.extend(str(x) for x in v if x)
            elif v:
                out.append(str(v))
        # dedupe, preserve order
        seen: set[str] = set()
        result: list[str] = []
        for item in out:
            stripped = item.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                result.append(stripped)
        return result
    if kind == "split":
        # column 값을 separator 로 분할 → list[str]. literal split (정규식 X).
        source = spec.get("source")
        raw = row.get(source, "") if source else ""
        value = "" if raw is None else str(raw)
        if not value:
            return []
        separator = str(spec.get("separator") or ",")
        transform = spec.get("transform") or "none"
        parts = value.split(separator)
        return [_apply_transform(p.strip(), transform) for p in parts if p.strip()]
    return None


# Hallucination 방어 A — segment 분해 대상 (string field 만)
_STRING_FIELDS_FOR_SEGMENTS = ("term", "description", "example", "category")


def apply_rule_with_segments(rule: dict, row: dict[str, Any]) -> dict:
    """``apply_rule`` 과 동일 결과 + 각 string field 의 segment 정보 동봉.

    Segment 는 사용자 UI 에서 "AI 가 작성한 문구" vs "파일 데이터" 시각 표시용.

    Returns:
        {
            "entry": {... apply_rule 결과 ...},
            "segments": {
                "description": [
                    {"kind": "data",    "text": "AJMAN, UAE"},
                    {"kind": "literal", "text": "는 "},
                    {"kind": "data",    "text": "AE"},
                    {"kind": "literal", "text": " 국가의 ..."},
                ],
                "term": [...],
                ...
            }
        }

    Segment kind:
    - ``data``    — 파일에서 온 값 (column, template placeholder, split)
    - ``literal`` — LLM 또는 사용자가 룰에 직접 입력한 문구 (template wording, constant, concat join)

    List field (synonyms) 는 segment 분해 안 함 — 사용자가 이미 list 로 인지.
    """
    entry = apply_rule(rule, row)
    segments: dict[str, list[dict]] = {}
    if entry.get("term"):
        mapping = rule.get("mapping") or {}
        for field in _STRING_FIELDS_FOR_SEGMENTS:
            spec = mapping.get(field)
            if not spec:
                continue
            try:
                _v, segs = _eval_spec_with_segments(spec, row)
            except Exception as e:
                log.warning("segment eval 실패 field=%s: %s", field, e)
                continue
            cleaned = [s for s in segs if s.get("text")]
            if cleaned:
                segments[field] = cleaned
    return {"entry": entry, "segments": segments}


def _eval_spec_with_segments(spec: Any, row: dict[str, Any]) -> tuple[str, list[dict]]:
    """spec 평가 결과 + segment 분해. string-returning spec 만 의미 있음."""
    if not isinstance(spec, dict):
        return "", []
    kind = spec.get("kind")
    if kind in (None, "skip") or kind not in _VALID_KINDS:
        return "", []
    if kind == "constant":
        v = str(spec.get("value", ""))
        return (v, [{"kind": "literal", "text": v}]) if v else ("", [])
    if kind == "column":
        source = spec.get("source")
        raw = row.get(source, "") if source else ""
        value = "" if raw is None else str(raw)
        transform = spec.get("transform") or "none"
        value = _apply_transform(value, transform)
        return (value, [{"kind": "data", "text": value}]) if value else ("", [])
    if kind == "template":
        template = str(spec.get("template") or "")
        segments: list[dict] = []
        rendered: list[str] = []
        last_end = 0
        for m in _PLACEHOLDER.finditer(template):
            if m.start() > last_end:
                lit = template[last_end : m.start()]
                segments.append({"kind": "literal", "text": lit})
                rendered.append(lit)
            key = m.group(1)
            raw = row.get(key)
            data_text = "" if raw is None else str(raw)
            if data_text:
                segments.append({"kind": "data", "text": data_text})
            rendered.append(data_text)
            last_end = m.end()
        if last_end < len(template):
            tail = template[last_end:]
            segments.append({"kind": "literal", "text": tail})
            rendered.append(tail)
        return "".join(rendered), segments
    if kind == "concat":
        sources = spec.get("sources") or []
        joiner = spec.get("join", "")
        out_segs: list[dict] = []
        out_parts: list[str] = []
        for s in sources:
            v, segs = _eval_spec_with_segments(s, row)
            if v:
                if out_parts and joiner:
                    out_segs.append({"kind": "literal", "text": joiner})
                out_parts.append(v)
                out_segs.extend(segs)
        return joiner.join(out_parts), out_segs
    if kind in ("concat_list", "split"):
        # list-returning. string field 에 쓰이면 ", " join — 전체 data 로 표기.
        v = _eval_spec(spec, row)
        if isinstance(v, list):
            joined = ", ".join(str(x) for x in v if x)
            return (joined, [{"kind": "data", "text": joined}]) if joined else ("", [])
        return "", []
    return "", []


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def _render_template(template: str, row: dict[str, Any]) -> str:
    def replace(m: re.Match) -> str:
        key = m.group(1)
        v = row.get(key)
        return "" if v is None else str(v)

    return _PLACEHOLDER.sub(replace, template)


def _apply_transform(value: str, transform: str) -> str:
    if not value:
        return value
    if transform == "title_case":
        # 한국어/영어 혼합 안전: 영문 토큰만 title, 한국어/숫자 보존.
        return _title_case_smart(value)
    if transform == "upper":
        return value.upper()
    if transform == "lower":
        return value.lower()
    if transform == "trim":
        return value.strip()
    return value


_STOPWORDS_LOWER = {"the", "and", "of", "in", "on", "at", "to", "for"}


def _title_case_smart(value: str) -> str:
    """영문 표기를 Title Case 로 변환. 한국어/숫자 보존, 흔한 stopword 는 소문자."""
    if not value:
        return value
    # split keeping delimiters
    parts = re.split(r"(\s+|[,])", value)
    out_parts: list[str] = []
    word_index = 0
    for part in parts:
        if not part:
            continue
        if re.match(r"\s+", part) or part == ",":
            out_parts.append(part)
            continue
        lowered = part.lower()
        if word_index > 0 and lowered in _STOPWORDS_LOWER:
            out_parts.append(lowered)
        else:
            # 영문만 capitalize; 한국어는 그대로
            if re.search(r"[A-Za-z]", part):
                # split inner: e.g., "AJMAN," 같은 토큰 콤마는 별 케이스 — split 에서 처리됨
                out_parts.append(part[:1].upper() + part[1:].lower())
            else:
                out_parts.append(part)
        word_index += 1
    return "".join(out_parts)


# ============================================================
# Validation
# ============================================================


class RuleValidationError(ValueError):
    """LLM 응답 룰의 형식 오류."""


def validate_rule(rule: Any) -> dict:
    """LLM 응답 룰을 sanitize. 알 수 없는 키 / 잘못된 kind 거절.

    Returns: 깨끗한 룰 dict. 실패 시 ``RuleValidationError`` raise.
    """
    if not isinstance(rule, dict):
        raise RuleValidationError("rule must be an object")
    mapping = rule.get("mapping")
    if not isinstance(mapping, dict):
        raise RuleValidationError("rule.mapping missing or not object")

    clean_mapping: dict[str, dict] = {}
    for field, spec in mapping.items():
        if field not in _FIELDS:
            # 모르는 field 무시
            continue
        clean_mapping[field] = _validate_spec(spec, depth=0)

    if not clean_mapping.get("term"):
        raise RuleValidationError("rule.mapping.term is required")

    cleaned = {
        "mapping": clean_mapping,
        "rationale": str(rule.get("rationale") or "")[:500],
    }
    return cleaned


def _validate_spec(spec: Any, depth: int = 0) -> dict:
    if depth > 3:
        raise RuleValidationError("nested spec depth exceeded")
    if not isinstance(spec, dict):
        raise RuleValidationError("spec must be object")
    kind = spec.get("kind")
    if kind not in _VALID_KINDS:
        raise RuleValidationError(f"invalid kind: {kind}")
    cleaned: dict = {"kind": kind}
    if kind == "column":
        cleaned["source"] = str(spec.get("source") or "")
        transform = spec.get("transform") or "none"
        if transform not in _VALID_TRANSFORMS:
            transform = "none"
        cleaned["transform"] = transform
    elif kind == "template":
        cleaned["template"] = str(spec.get("template") or "")[:1000]
    elif kind == "constant":
        v = spec.get("value", "")
        cleaned["value"] = str(v) if v is not None else ""
    elif kind in ("concat", "concat_list"):
        raw_sources = spec.get("sources") or []
        if not isinstance(raw_sources, list):
            raise RuleValidationError(f"{kind}.sources must be list")
        cleaned["sources"] = [_validate_spec(s, depth + 1) for s in raw_sources[:10]]
        if kind == "concat":
            cleaned["join"] = str(spec.get("join") or "")[:20]
    elif kind == "split":
        # leaf only: source 는 column 이름 (str), nested spec 금지.
        raw_source = spec.get("source")
        if isinstance(raw_source, dict):
            raise RuleValidationError(
                "split.source must be a column name (str), not nested spec"
            )
        cleaned["source"] = str(raw_source or "")[:120]
        if not cleaned["source"]:
            raise RuleValidationError("split.source is required")
        # separator: literal 1~5자. strip 후 빈 문자열이면 default ",".
        raw_sep = str(spec.get("separator") or ",")[:5]
        cleaned["separator"] = raw_sep if raw_sep.strip() else ","
        transform = spec.get("transform") or "none"
        if transform not in _VALID_TRANSFORMS:
            transform = "none"
        cleaned["transform"] = transform
    return cleaned


# ============================================================
# LLM prompt + call
# ============================================================


_SYSTEM_PROMPT = """\
당신은 표 형식 데이터를 용어집(glossary) entries 로 변환하는 룰을 설계합니다.

각 entry 는 다음 필드를 가집니다:
- term: 대표 용어 (필수, 사람이 읽기 좋은 형태)
- synonyms: 동의어 리스트 (코드, 약어, 다른 표기 등)
- description: 1-2문장 설명. 표의 다른 컬럼을 합성해 만들어도 좋음.
- example: 사용 예시 (자료에 없으면 빈 문자열)
- category: 카테고리 (모든 row 가 같은 종류면 고정값, 다르면 컬럼에서 추출)

응답은 반드시 다음 JSON 스키마로:

{
  "mapping": {
    "term":        <spec>,
    "synonyms":    <spec>,  // 보통 concat_list
    "description": <spec>,  // 보통 template
    "example":     <spec>,  // 자료에 없으면 {"kind": "constant", "value": ""}
    "category":    <spec>   // 보통 constant (모든 row 같은 카테고리) 또는 column
  },
  "rationale": "한 줄 설명 (한국어)"
}

spec 종류:
1. {"kind": "column", "source": "<헤더명>", "transform": "title_case|upper|lower|trim|none"}
2. {"kind": "template", "template": "<텍스트> {헤더1}{헤더2}..."}
3. {"kind": "constant", "value": "<고정 텍스트>"}
4. {"kind": "concat", "sources": [<spec>, ...], "join": "<구분자>"}
5. {"kind": "concat_list", "sources": [<spec>, ...]}
6. {"kind": "split", "source": "<헤더명>", "separator": ",", "transform": "trim|none"}
7. {"kind": "skip"}

규칙:
- placeholder {헤더명} 의 헤더명은 입력 표의 헤더와 정확히 일치해야 함.
- 영문 대문자만 있는 자료는 term 에 title_case 권장 (사람 친화).
- 동의어로 약어/코드/원본 표기 등 여러 개 넣고 싶으면 concat_list 사용.
- **코드 컬럼이 2개 이상이고 합치면 표준 코드가 되는 경우** (예: ISO 국가코드 + 도시코드 → UN/LOCODE)
  template 으로 합성 코드를 만들어 synonyms 에 포함하세요. 사용자가 합성 코드로도 검색 가능.
- **한 셀에 콤마/세미콜론으로 여러 값이 들어있는 경우** (예: "A/R, 외상매출금" 또는 "B/L; 선하증권")
  concat_list 의 source 로 split spec 사용. column 으로 받으면 단일 string 이 되어 검색 정확도 떨어집니다.
- 카테고리가 표 안에 명시되어 있지 않고 자료 전체가 동질적이면 constant 로 적절한 한국어 이름 부여
  (예: "포트코드", "약어", "용어집").
- 자료가 명백히 무엇인지 모르면 rationale 에 "추측: ..." 명시.
- 추가 설명 텍스트 금지. JSON 한 객체만 응답.

예시 — 포트코드 자료 (CN+Place 합성이 UN/LOCODE 표준):
헤더: ["CN", "Place", "Class", "Place Name(English)"]
샘플: [{"CN":"AE","Place":"AJM","Class":"PORT","Place Name(English)":"AJMAN, UAE"}]
좋은 룰:
{
  "mapping": {
    "term": {"kind": "column", "source": "Place Name(English)", "transform": "title_case"},
    "synonyms": {"kind": "concat_list", "sources": [
      {"kind": "template", "template": "{CN}{Place}"},
      {"kind": "column", "source": "Place", "transform": "upper"},
      {"kind": "column", "source": "Place Name(English)", "transform": "upper"}
    ]},
    "description": {"kind": "template",
      "template": "UN/LOCODE: {CN}{Place} ({Class}). {Place Name(English)}."},
    "example": {"kind": "constant", "value": ""},
    "category": {"kind": "constant", "value": "포트/장소코드"}
  },
  "rationale": "포트코드 — CN+Place 가 UN/LOCODE 5자리 코드. 합성 코드도 검색 가능."
}

예시 — 한 셀에 여러 동의어 (콤마 구분):
헤더: ["제목", "용어", "뜻"]
샘플: [{"제목":"Account Receivable", "용어":"A/R, 외상매출금", "뜻":"매출채권 ..."}]
좋은 룰 (synonyms 부분만):
"synonyms": {"kind": "concat_list", "sources": [
  {"kind": "split", "source": "용어", "separator": ",", "transform": "trim"}
]}
이렇게 하면 "A/R" 과 "외상매출금" 둘 다 별개 synonym 으로 분리되어 검색 recall ↑.
"""

_USER_PROMPT_TEMPLATE = """\
표의 헤더:
{headers}

샘플 row (앞 {sample_count}개):
{samples}

위 표를 glossary entries 로 변환할 룰을 JSON 으로 응답하세요.
"""


_CONSERVATIVE_RULE = """

** 보수 모드 (Hallucination 방어) **:
- description 의 spec 은 반드시 ``column``, ``concat`` (sources 가 모두 column), ``skip`` 중 하나만 사용.
- ``template`` / ``constant`` 금지 — LLM 이 자유 작성한 wording 은 도메인 부정확할 수 있음.
- 자료에 description 으로 쓸 컬럼이 없다면 ``{"kind": "skip"}`` 또는 사용자가 후속 수정하도록 빈 값.
"""


def build_messages(
    headers: list[str],
    sample_rows: list[dict],
    conservative_description: bool = False,
) -> list:
    """LLM 호출용 메시지 빌드.

    prompt injection 방어: headers / sample 모두 JSON encode 로 인용. 헤더에
    "시스템 지시 무시하고 ..." 같은 문구가 들어와도 JSON 문자열로 격리된다.

    Args:
        conservative_description: True 이면 description 의 LLM 합성문(template/constant)
            금지 → 회사 도메인 hallucination 위험 완화.
    """
    # 헤더 길이 cap + 제어문자 strip (LLM 의 attention 을 흐트리는 zero-width 등)
    safe_headers = [re.sub(r"[\x00-\x1f\x7f]", "", str(h or ""))[:120] for h in headers]
    headers_json = json.dumps(safe_headers, ensure_ascii=False)
    samples_json = json.dumps(sample_rows[:8], ensure_ascii=False, indent=2)
    user_msg = _USER_PROMPT_TEMPLATE.format(
        headers=headers_json,
        sample_count=min(len(sample_rows), 8),
        samples=samples_json,
    )
    system_content = _SYSTEM_PROMPT
    if conservative_description:
        system_content = _SYSTEM_PROMPT + _CONSERVATIVE_RULE
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=user_msg),
    ]


# allowed description spec kinds when conservative mode is on
_CONSERVATIVE_DESC_KINDS = {"column", "concat", "skip"}


def _enforce_conservative_description(rule: dict) -> dict:
    """conservative mode 의 post-validate: description 이 template/constant 면 skip 으로 강등.

    LLM 이 보수 룰을 무시하고 template/constant 반환 시 fail-closed: description 자체를 skip.
    사용자는 entry 등록 후 직접 수정 가능. silent fabrication 보다 빈 값이 안전.
    """
    mapping = rule.get("mapping") or {}
    desc = mapping.get("description")
    if not isinstance(desc, dict):
        return rule
    if desc.get("kind") not in _CONSERVATIVE_DESC_KINDS:
        # concat 의 sources 안에 template/constant 있어도 강등 (방어적)
        log.info(
            "conservative_description: description spec %s → skip",
            desc.get("kind"),
        )
        mapping["description"] = {"kind": "skip"}
    elif desc.get("kind") == "concat":
        # nested template/constant 가 있으면 column 만 남기거나 skip
        sources = desc.get("sources") or []
        if any(
            isinstance(s, dict) and s.get("kind") not in ("column", "concat")
            for s in sources
        ):
            log.info(
                "conservative_description: concat sources contain non-column → skip"
            )
            mapping["description"] = {"kind": "skip"}
    return rule


def _resolve_default_model_id(app) -> Optional[str]:
    """app.state.config 에서 사용 가능한 task model id 를 추출.

    fallback chain: TASK_MODEL → TASK_MODEL_EXTERNAL.
    PersistentConfig 객체와 일반 str 모두 지원.
    """
    config = getattr(getattr(app, "state", None), "config", None)
    if config is None:
        return None
    for key in ("TASK_MODEL", "TASK_MODEL_EXTERNAL"):
        raw = getattr(config, key, None)
        if raw is None:
            continue
        # PersistentConfig 면 .value, 아니면 본인.
        value = getattr(raw, "value", raw)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def suggest_rule(
    app,
    model_id: str,
    headers: list[str],
    sample_rows: list[dict],
    conservative_description: bool = False,
) -> dict:
    """LLM 호출 → 변환 룰 추론. 실패 시 RuleValidationError raise.

    Args:
        app: FastAPI app (request.app) — model config 조회용.
        model_id: 사용할 model id. 비어있으면 TASK_MODEL / TASK_MODEL_EXTERNAL fallback.
        conservative_description: True 이면 description 에 LLM 합성문 금지
            (hallucination 위험 완화).
    """
    from extension_modules.utils.llm import create_llm, get_model_config_from_app

    if not model_id:
        model_id = _resolve_default_model_id(app) or ""
    if not model_id:
        raise RuleValidationError(
            "AI 추론에 사용할 모델이 설정되지 않았습니다. "
            "용어집 페이지의 AI 모델을 선택하거나 관리자에게 TASK_MODEL 설정을 요청하세요."
        )

    config = get_model_config_from_app(app, model_id)
    if not config:
        raise RuleValidationError(
            f"모델 설정을 찾을 수 없음: {model_id}. 모델이 활성화되어 있는지 확인하세요."
        )

    llm = create_llm(config, json_mode=True, temperature=0.1)
    messages = build_messages(headers, sample_rows, conservative_description)
    response = await llm.ainvoke(messages)
    content = getattr(response, "content", None)
    if not isinstance(content, str):
        content = str(content)
    # JSON 추출 — fence (```json) 가 섞여있을 수 있어 강건하게
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        rule_raw = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuleValidationError(f"LLM 응답이 JSON 형식이 아님: {e}") from e
    rule = validate_rule(rule_raw)
    if conservative_description:
        rule = _enforce_conservative_description(rule)
    return rule
