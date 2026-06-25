"""
Knowledge Base 파일 필터: Glossary 용어 매칭 추출 모듈.

두 가지 추출 전략:
  1. 텍스트 매칭 (extract_glossary_terms) — LLM 없이 즉시, 결정적
  2. AI 에이전트 (extract_glossary_terms_ai) — LLM + 도구 호출, 사용자 지시사항 기반

AI 에이전트 동작:
  - 소규모 용어집 (≤200 entries): 전체 term 목록을 LLM에 직접 전달 → 문서에서 해당하는 것 선택
  - 대규모 용어집 (>200 entries): search_glossary 도구를 제공 → 에이전트가 도구 호출하며 매칭
  - 사용자 지시사항에 따라 동작 조절 (파일명만 / 첫 페이지만 / 전체 등)
"""

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

log = logging.getLogger(__name__)

GLOSSARY_MAX_CONTENT_CHARS = 50_000
AI_MAX_CONTENT_CHARS = 4000
SMALL_GLOSSARY_THRESHOLD = 200
_SEARCH_TOP_K = 5
_MAX_AGENT_ITERATIONS = 6

_WS_RE = re.compile(r"\s+")


def _strip_ws(text: str) -> str:
    """공백을 모두 제거한 소문자 문자열 반환."""
    return _WS_RE.sub("", text).lower()


# ---------------------------------------------------------------------------
# 1. 텍스트 매칭 추출
# ---------------------------------------------------------------------------


async def extract_glossary_terms(
    glossary_id: str,
    file_content: str,
    filename: str = "",
    category: Optional[str] = None,
    preloaded_entries: Optional[list[dict]] = None,
    include_synonyms: bool = False,
) -> list[str]:
    """
    파일 내용 + 파일명에서 용어집 항목을 텍스트 매칭으로 추출합니다.

    Args:
        include_synonyms: True면 동의어도 매칭 대상에 포함. 기본 False (term만 사용).
    """
    # filename 과 file_content 중 하나라도 있으면 진행 (제목 전용 추출 지원).
    has_content = bool(file_content and file_content.strip())
    has_filename = bool(filename and filename.strip())
    if not has_content and not has_filename:
        return []

    entries = preloaded_entries
    if entries is None:
        entries = _load_glossary_entries(glossary_id)

    if not entries:
        return []

    if category:
        entries = [e for e in entries if e.get("category") == category]

    truncated = file_content[:GLOSSARY_MAX_CONTENT_CHARS]
    search_text = f"{filename}\n{truncated}" if filename else truncated
    content_lower = search_text.lower()
    content_no_ws = _strip_ws(search_text)

    matched_terms: set[str] = set()
    for entry in entries:
        term = (entry.get("term") or "").strip()
        if not term:
            continue

        search_tokens = [term]
        if include_synonyms:
            synonyms = entry.get("synonyms") or []
            search_tokens.extend(s.strip() for s in synonyms if s and s.strip())

        for token in search_tokens:
            token_lower = token.lower()
            if token_lower in content_lower:
                matched_terms.add(term)
                break
            token_no_ws = _WS_RE.sub("", token_lower)
            if len(token_no_ws) >= 2 and token_no_ws in content_no_ws:
                matched_terms.add(term)
                break

    result = sorted(matched_terms)
    log.info(
        f"Glossary filter (text): matched {len(result)}/{len(entries)} terms "
        f"for glossary {glossary_id}"
    )
    return result


# ---------------------------------------------------------------------------
# 2. AI 에이전트 추출
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_DIRECT = """For each glossary term below, verify whether the term or any of its synonyms can be found **verbatim** in the document text.

Glossary: {glossary_name}
Document filename: {filename}
{category_info}
{user_instructions}

Glossary terms to verify:
{terms_block}

Verification rules:
- Check the document text (including filename, metadata/frontmatter, body) for each term and its synonyms.
- A term is verified ONLY if you can find the **exact string** of the term or one of its synonyms written somewhere in the document.
- Do NOT verify a term based on your knowledge. For example, if the document says "B2" and the glossary has "리보플라빈 (synonyms: Riboflavin, Vitamin B2)", do NOT match — "B2" alone is not the same as "Vitamin B2".
- Return the **canonical term name** (the first name), not the synonym.

Respond with ONLY a JSON object:
{{"matched_terms": ["term1", "term2", ...]}}

If no terms are verified, return {{"matched_terms": []}}.
"""

_SYSTEM_PROMPT_AGENT = """Verify which glossary terms are written in a document by searching the glossary.

Glossary: {glossary_name}
Document filename: {filename}
{category_info}
{user_instructions}

Read the document and find words/names that appear in it. Then use `search_glossary` to check if they exist in the glossary.

Verification rules:
- A term is verified ONLY if the **exact string** of the term or its synonym is written in the document.
- Do NOT verify a term based on your knowledge — only based on what is literally written in the document text.

When you are done, respond with ONLY a JSON object:
{{"matched_terms": ["term1", "term2", ...]}}

If no terms are verified, return {{"matched_terms": []}}.
"""

_SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_glossary",
        "description": "Search the glossary for terms matching a query. Returns top matching entries with term, synonyms, description, and category. Use this to verify if a word from the document exists in the glossary.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query — a term, name, or phrase from the document",
                },
            },
            "required": ["query"],
        },
    },
}


async def extract_glossary_terms_ai(
    app: Any,
    glossary_id: str,
    file_content: str,
    filename: str = "",
    extraction_prompt: str = "",
    category: Optional[str] = None,
    model_id: str = "",
    model_config: Optional[dict] = None,
    include_synonyms: bool = False,
) -> list[str]:
    """
    AI 에이전트로 용어집 용어를 추출합니다.

    - 소규모 (≤200 entries): 전체 term 목록을 직접 전달 → 1턴
    - 대규모 (>200 entries): search_glossary 도구 호출 에이전트
    """
    from extension_modules.utils.llm import create_llm, create_llm_from_app
    from open_webui.models.glossary import Glossaries

    # LLM 생성 (json_mode 없이 — 도구 호출 모드에서는 호환성 문제)
    llm = None
    if model_config:
        llm = create_llm(model_config, temperature=0.1)
    elif model_id:
        llm = create_llm_from_app(app, model_id, temperature=0.1)

    if not llm:
        log.error("Failed to create LLM for glossary AI extraction")
        return []

    # 용어집 정보 로드
    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        log.warning(f"Glossary not found: {glossary_id}")
        return []

    glossary_name = glossary.name or ""
    entries = (glossary.data or {}).get("entries") or []
    if category:
        entries = [e for e in entries if e.get("category") == category]

    if not entries:
        return []

    # 카테고리 정보
    category_info = ""
    if category:
        cat_defs = Glossaries.get_category_definitions(glossary_id) or {}
        if category in cat_defs:
            d = cat_defs[category]
            definition = d.get("definition", "") if isinstance(d, dict) else str(d)
            category_info = f"Category: {category} — {definition}"
    else:
        cat_defs = Glossaries.get_category_definitions(glossary_id) or {}
        if cat_defs:
            parts = []
            for cat, d in cat_defs.items():
                definition = d.get("definition", "") if isinstance(d, dict) else str(d)
                parts.append(f"- {cat}: {definition}")
            category_info = "Categories:\n" + "\n".join(parts)

    user_instructions = ""
    if extraction_prompt and extraction_prompt.strip():
        user_instructions = f"User instructions: {extraction_prompt.strip()}"

    # 파일 내용 구성
    truncated_content = file_content[:AI_MAX_CONTENT_CHARS]
    if len(file_content) > AI_MAX_CONTENT_CHARS:
        truncated_content += "\n... (truncated)"

    doc_message = f"--- Document content ---\n{truncated_content}\n---"

    # 소규모 용어집: 직접 매칭
    if len(entries) <= SMALL_GLOSSARY_THRESHOLD:
        return await _extract_direct(
            llm,
            entries,
            glossary_name,
            filename,
            category_info,
            user_instructions,
            doc_message,
            include_synonyms=include_synonyms,
        )

    # 대규모 용어집: 에이전트 (도구 호출)
    return await _extract_with_agent(
        app,
        llm,
        glossary_id,
        glossary_name,
        filename,
        category,
        category_info,
        user_instructions,
        doc_message,
    )


async def _extract_direct(
    llm,
    entries: list[dict],
    glossary_name: str,
    filename: str,
    category_info: str,
    user_instructions: str,
    doc_message: str,
    include_synonyms: bool = False,
) -> list[str]:
    """소규모 용어집: 전체 term 목록을 LLM에 직접 전달."""
    lines = []
    for e in entries:
        term = e.get("term", "").strip()
        if not term:
            continue
        line = f"- {term}"
        if include_synonyms and e.get("synonyms"):
            line += f" (synonyms: {', '.join(e['synonyms'])})"
        if e.get("category"):
            line += f" [{e['category']}]"
        lines.append(line)
    terms_block = "\n".join(lines)

    system = _SYSTEM_PROMPT_DIRECT.format(
        glossary_name=glossary_name,
        filename=filename or "(untitled)",
        category_info=category_info,
        user_instructions=user_instructions,
        terms_block=terms_block,
    )

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=doc_message),
            ]
        )
        result = _parse_json(response.content)
        matched = result.get("matched_terms", [])
        if not isinstance(matched, list):
            matched = []

        # 실제 용어집 term과 대조하여 검증
        valid_terms = {e.get("term", "").strip() for e in entries if e.get("term")}
        verified = [t for t in matched if t in valid_terms]

        log.info(
            f"Glossary AI (direct): {len(verified)} terms matched "
            f"from {len(entries)} entries"
        )
        return sorted(set(verified))

    except Exception as e:
        log.warning(f"Glossary AI direct extraction failed: {e}")
        return []


async def _extract_with_agent(
    app: Any,
    llm,
    glossary_id: str,
    glossary_name: str,
    filename: str,
    category: Optional[str],
    category_info: str,
    user_instructions: str,
    doc_message: str,
) -> list[str]:
    """대규모 용어집: search_glossary 도구를 제공하는 에이전트 루프."""
    from extension_modules.glossary.service import GlossaryIndexService

    glossary_service = GlossaryIndexService(app)

    system = _SYSTEM_PROMPT_AGENT.format(
        glossary_name=glossary_name,
        filename=filename or "(untitled)",
        category_info=category_info,
        user_instructions=user_instructions,
    )

    # 도구 바인딩
    llm_with_tools = llm.bind_tools(
        [_SEARCH_TOOL_SCHEMA],
        tool_choice="auto",
    )

    messages: list = [
        SystemMessage(content=system),
        HumanMessage(content=doc_message),
    ]

    for iteration in range(_MAX_AGENT_ITERATIONS):
        # 마지막 iteration 에 들어가기 직전, LLM 이 tool 호출을 추가로
        # 쏟지 못하도록 finalize 지시를 주입. API 차원에서 tool_choice="none"
        # 을 강제하는 방식은 공급자마다 다르므로 대화 메시지 레벨에서 힌트.
        if iteration == _MAX_AGENT_ITERATIONS - 1:
            messages.append(
                HumanMessage(
                    content=(
                        "This is your final turn. Do NOT call any more tools. "
                        'Respond only with the JSON object {"matched_terms": [...]}.'
                    )
                )
            )

        try:
            response: AIMessage = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            log.warning(f"Glossary AI agent LLM call failed (iter {iteration}): {e}")
            break

        messages.append(response)

        # 도구 호출이 없으면 최종 응답
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # 최종 응답에서 JSON 파싱
            result = _parse_json(response.content)
            matched = result.get("matched_terms", [])
            if not isinstance(matched, list):
                matched = []
            log.info(
                f"Glossary AI (agent): {len(matched)} terms matched "
                f"in {iteration + 1} iterations"
            )
            return sorted(set(t for t in matched if t and isinstance(t, str)))

        # 도구 호출 실행
        for tc in tool_calls:
            if tc.get("name") == "search_glossary":
                args = tc.get("args", {})
                query = args.get("query", "")
                tool_result = await _execute_search(
                    glossary_service, glossary_id, query, category
                )
                messages.append(
                    ToolMessage(
                        content=tool_result,
                        tool_call_id=tc.get("id", ""),
                    )
                )

    # max iterations 도달 — 모든 AIMessage 를 훑어 partial matched_terms 를
    # 합집합으로 회수. LLM 이 finalize 지시에도 불구하고 tool 호출을 이어갈
    # 경우를 대비한 안전망.
    log.warning(
        "Glossary AI agent: max iterations reached — recovering partial results"
    )
    collected: set[str] = set()
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content:
            result = _parse_json(msg.content)
            matched = result.get("matched_terms", [])
            if isinstance(matched, list):
                for t in matched:
                    if t and isinstance(t, str):
                        collected.add(t)
    if collected:
        log.info(
            f"Glossary AI agent: recovered {len(collected)} partial terms "
            f"from {_MAX_AGENT_ITERATIONS} iterations"
        )
        return sorted(collected)
    return []


async def _execute_search(
    glossary_service,
    glossary_id: str,
    query: str,
    category: Optional[str],
) -> str:
    """search_glossary 도구 실행."""
    if not query or not query.strip():
        return json.dumps({"results": [], "message": "Empty query"})

    try:
        search_kwargs: dict[str, Any] = {
            "query": query.strip(),
            "glossary_id": glossary_id,
            "top_k": _SEARCH_TOP_K,
        }
        if category:
            search_kwargs["category"] = category

        hits = await glossary_service.search(**search_kwargs)
        results = [
            {
                "term": h.term,
                "synonyms": h.synonyms or [],
                "description": (h.description or "")[:200],
                "category": h.category or "",
            }
            for h in hits
        ]
        return json.dumps({"results": results}, ensure_ascii=False)

    except Exception as e:
        log.warning(f"Glossary search tool error for '{query}': {e}")
        return json.dumps({"results": [], "error": str(e)})


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _parse_json(response_content: Any) -> dict:
    """LLM 응답에서 JSON 파싱."""
    if isinstance(response_content, list):
        text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in response_content
        ).strip()
    else:
        text = str(response_content).strip()

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

    # 중첩 JSON 포함 가능 — 재귀적 매칭
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


def _load_glossary_entries(glossary_id: str) -> list[dict]:
    """Glossary entries를 DB에서 로드합니다."""
    from open_webui.models.glossary import Glossaries

    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        log.warning(f"Glossary not found: {glossary_id}")
        return []

    data = glossary.data or {}
    return data.get("entries") or []


def load_glossary_entries_for_batch(
    glossary_id: str,
    category: Optional[str] = None,
) -> list[dict]:
    """배치 추출 최적화: glossary entries를 1회 로드하여 반환합니다."""
    entries = _load_glossary_entries(glossary_id)
    if category:
        entries = [e for e in entries if e.get("category") == category]
    return entries
