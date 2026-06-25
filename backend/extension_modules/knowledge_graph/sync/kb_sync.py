"""KB(Knowledge Base) → KG 동기화 — LLM 엔티티/관계 추출 (Slice 7).

KB 문서의 청크들을 LLM에 분석시켜 엔티티와 관계를 추출하고 KG에 저장한다.
이게 채워지면 multi-hop 추론 쿼리(예: "ESG 위험 협력사가 만든 부품을 쓰는
제품 라인은?")가 그래프 트래버설로 가능해진다.

설계 노트:
- 비싼 LLM 호출이 많이 발생하므로 max_chunks 제한 필수.
- 엔티티 dedup은 lowercase label 기반 — 동일 엔티티가 여러 청크에서
  추출되면 source_ref에 추가 청크 ID만 기록.
- 관계는 양방향 related_to 엣지 (방향성 강한 관계는 추후 슬라이스).
- 신뢰도 threshold(0.5 미만 skip)로 노이즈 제거.
- 프롬프트는 JSON-only 응답 강제.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from extension_modules.utils.llm import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge import Knowledges
from open_webui.models.knowledge_graph import (
    EdgeSource,
    KnowledgeGraphs,
    NodeType,
    make_node_id,
    resolve_llm_edge_type,
)
from open_webui.retrieval.knowledge_service import SearchEngineKnowledge

from ._age_helpers import age_cleanup, age_upsert_edge, age_upsert_node, get_age_service
from ._kb_hierarchy import (
    add_extracted_from_edge,
    ensure_document_node,
    ensure_kb_container_node,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


SYSTEM_PROMPT_BASE = """You are an expert knowledge engineer extracting domain entities and relationships from documents.

Your task: Read the given text chunk and extract:
1. **Entities** — specific named things that are central to this knowledge graph's domain
2. **Relationships** — meaningful, domain-relevant connections between those entities

Rules:
1. Stay strictly in-domain. Extract entities that matter to the domain stated below. Skip incidental mentions (page numbers, publishers, chapter headings, copyright, authors — unless they ARE the subject).
2. Use the same language as the source text for entity names (Korean if Korean, English if English).
3. Entity `type` should be a short domain noun that describes what kind of thing it is. Pick whatever fits the domain best (e.g., for a drug-components domain: `drug`, `ingredient`, `indication`, `side_effect`, `dosage`, `mechanism`, `interaction`; for an org domain: `organization`, `product`, `person`; for a legal domain: `regulation`, `clause`, `party`).
4. Relationship `type` should be a DESCRIPTIVE domain verb (e.g., `contains`, `treats`, `causes`, `interacts_with`, `has_dosage`, `has_side_effect`, `indicated_for`, `produced_by`, `has_feature`, `regulates`, `depends_on`).
5. Confidence: 0.9+ for explicit statements, 0.7-0.9 for implied, below 0.6 → omit.
6. Limit: max 10 entities and max 15 relationships per chunk.
7. Both endpoints of every relationship MUST appear in the entities list.
8. If the chunk is clearly out-of-domain (TOC, copyright page, index, navigation, boilerplate), return empty arrays.

**Entity linking (CRITICAL):**
If an entity in the text matches one of the "Known entities" listed below, you MUST use the EXACT label from the known list (case-sensitive, character-perfect). This lets the system reuse the existing knowledge graph node instead of creating a duplicate. Only invent a new label when there is no match in the known list.

Output ONLY a JSON object with this exact shape (no markdown, no commentary):
{
  "entities": [
    {"name": "<entity name>", "type": "<domain noun>", "confidence": 0.9}
  ],
  "relationships": [
    {"from": "<entity name>", "type": "<domain verb>", "to": "<entity name>", "confidence": 0.8}
  ]
}

If no meaningful entities can be extracted, return {"entities": [], "relationships": []}.
"""


# 한 청크의 LLM 호출에 주입할 anchor 엔티티 최대 개수.
# 너무 많으면 토큰 비용 증가 + 프롬프트 가드 강도 약화.
_MAX_KNOWN_ENTITIES_HINT = 80


def _build_system_prompt(
    known_entities: list[str],
    entity_context: Optional[str] = None,
    kg_name: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> str:
    """SYSTEM_PROMPT_BASE에 KG 도메인 + known entities + 엔티티 컨텍스트를 주입.

    kg_name / kg_description 은 이 KG 가 어떤 도메인인지를 LLM 에 알려주어
    엔티티 추출을 도메인에 유의미한 것으로 좁히는 데 사용된다.
    entity_context 는 지식 연결 매칭에서 나온 파일 단위 힌트.
    """
    prompt = SYSTEM_PROMPT_BASE

    # ── 도메인 컨텍스트 (KG 이름/설명) ──
    if kg_name or kg_description:
        domain_lines = ["\n\n**DOMAIN**:"]
        if kg_name:
            domain_lines.append(f"- Knowledge graph name: {kg_name}")
        if kg_description:
            domain_lines.append(f"- Description: {kg_description}")
        domain_lines.append(
            "Every entity you extract MUST be meaningful within this domain. "
            "Ignore text that is off-topic for this domain."
        )
        prompt += "\n".join(domain_lines)

    # ── 엔티티 컨텍스트 (지식 연결에서 매칭된 엔티티) ──
    if entity_context:
        prompt += (
            f"\n\n**IMPORTANT CONTEXT**: {entity_context}\n"
            "When extracting entities and relationships, focus on features, "
            "specifications, and attributes of the identified item(s). "
            'Use relationship type "has_feature" for attributes/specs/characteristics.'
        )

    # ── Known entities ──
    if not known_entities:
        prompt += "\n\nKnown entities: (none — this is the first KB extraction or KG has no anchors yet)"
        return prompt

    truncated = known_entities[:_MAX_KNOWN_ENTITIES_HINT]
    listing = "\n".join(f"- {label}" for label in truncated)
    suffix = (
        f"\n\nKnown entities (already in the knowledge graph — reuse exact labels when matched):\n"
        f"{listing}"
    )
    if len(known_entities) > _MAX_KNOWN_ENTITIES_HINT:
        suffix += f"\n... (and {len(known_entities) - _MAX_KNOWN_ENTITIES_HINT} more not shown)"
    return prompt + suffix


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


####################
# 문서 레벨 엔티티 매칭 (지식 연결)
####################

UNCATEGORIZED = "_uncategorized_"
_CATEGORY_SAMPLE_SIZE = 8  # 카테고리 정의 생성에 쓸 랜덤 샘플 용어 개수


_CATEGORY_DEFINITION_PROMPT = """You are defining glossary categories so another system can later find documents matching each category.

Glossary name: {glossary_name}

For each category below, read the sample terms and write a concise (1–2 sentence) description explaining **what kind of entity** this category groups together. The description should be abstract enough that it applies to items not shown in the sample, but specific enough to distinguish this category from unrelated ones.

Categories:
{categories_block}

Output ONLY a JSON object in this exact shape (no markdown, no commentary):
{{"definitions": [
  {{"category": "Products", "definition": "Samsung mobile device product line (smartphones and tablets) that are released as consumer hardware SKUs."}}
]}}

Guidelines:
- Do NOT list the sample terms back; describe the *type* they represent.
- Keep each definition under 280 characters.
- Use the same language as the sample terms for the definition.
- If a category looks purely numeric or meaningless, still write a best-effort description.
"""


def _invoke_llm_text(llm, prompt: str) -> str:
    """LLM 호출 결과를 텍스트 문자열로 정규화 (Gemini list[dict] 포함)."""
    return prompt  # placeholder — not used directly; see _run_llm below


async def _run_llm(llm, prompt: str, timeout_s: float = 300.0) -> str:
    # Hard timeout — Azure OpenAI 가 가끔 hang 되면 worker slot 이 영구 점유되어
    # 상위 job 의 heartbeat 가 끊어지는 문제 방지. 5 분이면 장문 청크 + 재시도
    # latency 까지 커버하고, 그 이상은 이상 상태로 간주.
    import asyncio

    response = await asyncio.wait_for(
        llm.ainvoke([SystemMessage(content=""), HumanMessage(content=prompt)]),
        timeout=timeout_s,
    )
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):
        parts: list[str] = []
        for blk in content:
            if isinstance(blk, dict):
                t = blk.get("text") or blk.get("content")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(blk, str):
                parts.append(blk)
        content = "".join(parts)
    return content or ""


def _group_entries_by_category(entries: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for e in entries:
        cat = e.get("category") or UNCATEGORIZED
        grouped.setdefault(cat, []).append(e)
    return grouped


async def _ensure_category_definitions(
    llm,
    glossary,
    model_id: str,
) -> dict[str, dict]:
    """용어집의 카테고리 정의를 확보한다.

    1. `glossary.meta.category_definitions` 에 있으면 재사용.
    2. 없는 카테고리는 랜덤 샘플 N개 용어로 LLM 호출해서 1–2 문장 정의 생성.
    3. 결과를 glossary 에 캐시 (다음 호출부터 skip).

    Returns: {category: {definition, sample_terms, generated_at, model_id}}
    """
    import random as _random
    import time as _time

    from open_webui.models.glossary import Glossaries

    entries: list[dict] = (glossary.data or {}).get("entries") or []
    grouped = _group_entries_by_category(entries)
    if not grouped:
        return {}

    existing = Glossaries.get_category_definitions(glossary.id) or {}
    need_generate: list[tuple[str, list[str]]] = []

    for category, cat_entries in grouped.items():
        if category in existing and existing[category].get("definition"):
            continue
        terms = [
            (e.get("term") or "").strip()
            for e in cat_entries
            if (e.get("term") or "").strip()
        ]
        if not terms:
            continue
        # 랜덤 샘플 (sort 순서에 의한 단편화 방지)
        sample = (
            terms
            if len(terms) <= _CATEGORY_SAMPLE_SIZE
            else _random.sample(terms, _CATEGORY_SAMPLE_SIZE)
        )
        need_generate.append((category, sample))

    if not need_generate:
        return existing

    # 한 번의 LLM 호출로 다중 카테고리 정의 생성 (비용 절감)
    categories_block = "\n".join(
        f"- {cat}:\n    samples: {', '.join(samples)}" for cat, samples in need_generate
    )
    prompt = _CATEGORY_DEFINITION_PROMPT.format(
        glossary_name=glossary.name or "",
        categories_block=categories_block,
    )
    try:
        content = await _run_llm(llm, prompt)
        parsed = _extract_json(content) or {}
        defs = parsed.get("definitions") or []
    except Exception as e:
        log.exception(f"[doc_match] category definition LLM failed: {e}")
        defs = []

    def_by_cat: dict[str, str] = {}
    if isinstance(defs, list):
        for d in defs:
            if not isinstance(d, dict):
                continue
            name = (d.get("category") or "").strip()
            definition = (d.get("definition") or "").strip()
            if name and definition:
                def_by_cat[name] = definition

    now = int(_time.time())
    result = dict(existing)
    for category, samples in need_generate:
        definition = def_by_cat.get(category) or ""
        if not definition:
            # LLM 실패 시 샘플 용어 fallback — 매칭이 아예 멈추지 않도록.
            definition = f"A category grouping terms such as {', '.join(samples[:3])}."
        entry_def = {
            "definition": definition,
            "sample_terms": samples,
            "generated_at": now,
            "model_id": model_id,
        }
        Glossaries.set_category_definition(glossary.id, category, entry_def)
        result[category] = entry_def

    return result


async def ensure_glossary_category_definitions(
    app,
    glossary,
    pre_resolved_model_config: dict,
) -> dict[str, dict]:
    """부모 태스크가 호출: 카테고리 정의 캐시 확보 후 반환.

    이후 자식 파일 매칭 태스크들은 `glossary.meta.category_definitions` 에
    이미 저장된 값을 읽기만 하면 된다.
    """
    llm = create_llm(
        pre_resolved_model_config, streaming=False, model_kwargs={"temperature": 0.2}
    )
    model_id = (
        pre_resolved_model_config.get("id")
        or pre_resolved_model_config.get("model")
        or "unknown"
    )
    return await _ensure_category_definitions(llm, glossary, model_id)


# ---------------------------------------------------------------------------
# KB 필터 결과 → doc_entity_map 변환 (KG 구조 개편: LLM 재호출 없이 즉시 변환)
# ---------------------------------------------------------------------------


def build_doc_entity_map_from_filter(
    kg_id: str,
    glossary_id: str,
    knowledge_id: str,
) -> dict[str, list[dict]]:
    """KB glossary 필터 추출 결과를 doc_entity_map 형식으로 변환.

    KB의 ``knowledge.meta["filter_schema"]`` 에서 해당 glossary_id 를 참조하는
    glossary 타입 필드의 slot 키를 찾고, ``knowledge.data["file_metadata"]`` 에서
    각 파일별로 해당 slot 에 저장된 term 이름 목록을 읽어
    ``match_kb_file_via_glossary`` 의 반환 형식과 호환되는 doc_entity_map 을 생성.

    Returns:
        ``{file_id: [{entity_node_id, entity_label, category}]}``
        — 기존 ``link.status["doc_entity_map"]`` 과 동일 구조.
        매칭된 term 이 없는 파일은 포함하지 않는다.
    """
    from open_webui.models.glossary import Glossaries

    kb = Knowledges.get_knowledge_by_id(knowledge_id)
    if not kb:
        log.warning(f"[filter→doc_map] KB not found: {knowledge_id}")
        return {}

    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        log.warning(f"[filter→doc_map] glossary not found: {glossary_id}")
        return {}

    # ── glossary entries: term name → (entry_id, category) 매핑 ──
    entries: list[dict] = (glossary.data or {}).get("entries") or []
    term_lower_to_entry: dict[str, dict] = {}
    for e in entries:
        t = (e.get("term") or "").strip()
        if t:
            term_lower_to_entry.setdefault(t.lower(), e)

    if not term_lower_to_entry:
        return {}

    # ── filter_schema 에서 이 glossary 를 참조하는 f_col_* slot 찾기 ──
    filter_schema: list[dict] = (kb.meta or {}).get("filter_schema") or []
    glossary_slots: list[dict] = [
        f
        for f in filter_schema
        if f.get("type") == "glossary" and f.get("glossary_id") == glossary_id
    ]
    if not glossary_slots:
        log.info(
            f"[filter→doc_map] KB {knowledge_id[:8]} has no glossary filter "
            f"for glossary {glossary_id[:8]}"
        )
        return {}

    slot_keys = [f["slot"] for f in glossary_slots]

    # ── file_metadata 순회 → doc_entity_map 빌드 ──
    file_metadata: dict = (kb.data or {}).get("file_metadata") or {}
    doc_entity_map: dict[str, list[dict]] = {}

    for file_id, meta in file_metadata.items():
        if not isinstance(meta, dict):
            continue

        file_matches: list[dict] = []
        seen_entry_ids: set[str] = set()

        for slot_key in slot_keys:
            term_names: list[str] = meta.get(slot_key) or []
            if not isinstance(term_names, list):
                continue

            # slot → category 매핑 (filter_schema 에 category 가 있으면 사용)
            slot_field = next(
                (f for f in glossary_slots if f["slot"] == slot_key), None
            )
            slot_category = (slot_field or {}).get("category") if slot_field else None

            for term_name in term_names:
                entry = term_lower_to_entry.get(term_name.lower().strip())
                if not entry:
                    continue
                entry_id = entry.get("id")
                if not entry_id or entry_id in seen_entry_ids:
                    continue
                seen_entry_ids.add(entry_id)

                term_node_id = make_node_id(
                    kg_id, "glossary", glossary_id, "term", entry_id
                )
                file_matches.append(
                    {
                        "entity_node_id": term_node_id,
                        "entity_label": entry.get("term", ""),
                        "category": slot_category or entry.get("category"),
                    }
                )

        if file_matches:
            doc_entity_map[file_id] = file_matches

    log.info(
        f"[filter→doc_map] KB {knowledge_id[:8]} glossary {glossary_id[:8]}: "
        f"{len(doc_entity_map)} files, "
        f"{sum(len(v) for v in doc_entity_map.values())} total matches"
    )
    return doc_entity_map


# ── Filter → KG attribute 노드 빌드 ──
# KG 링크의 `config.extracted_filter_slots` 에 {kb_id, slot} 쌍으로 등록된
# 필터의 값들만 KG 의 doc_attr 노드로 승격하고 document 에서
# `has_{slot_suffix}` 엣지로 연결한다. 값이 링크된 glossary 의 term label 과
# 정규화 매치되면 term 노드를 재사용해 그래프가 파편화되지 않게 한다.
#
# 설계 원칙: KB 는 KG 를 모른다. KB 필터 스키마에 KG 관련 플래그가 없어야
# KG 기능을 안 쓰는 배포에서도 KB 가 그대로 작동한다. 어떤 필터를 노드로
# 올릴지는 **KG 링크 단위** 설정이다.

_SLOT_PREFIXES = ("f_str_", "f_col_", "f_int_", "f_date_", "f_glossary_")


def _slot_suffix(slot: str) -> str:
    """filter slot 키에서 prefix 를 벗긴 순수 이름. `f_str_country` → `country`.

    prefix 와 일치하지 않으면 slot 을 그대로 쓴다.
    """
    if not isinstance(slot, str):
        return ""
    for p in _SLOT_PREFIXES:
        if slot.startswith(p):
            return slot[len(p) :]
    return slot


_EDGE_SNAKE_RE = re.compile(r"[^a-zA-Z0-9]+")


def _label_to_snake(label: Optional[str]) -> Optional[str]:
    """필터 label 을 엣지 이름용 snake_case 로. ASCII 영숫자로만 정리 가능할
    때만 반환, 한글 등 non-ASCII 가 섞여 있으면 None. 숫자만 남는 경우도
    None (``has_1`` 같은 무의미 이름 방지).
    """
    if not label:
        return None
    s = _EDGE_SNAKE_RE.sub("_", str(label).strip()).strip("_").lower()
    if not s:
        return None
    # `_` 제외 영숫자만 있는지
    if not s.replace("_", "").isalnum():
        return None
    if s.replace("_", "").isdigit():
        return None
    return s


def _filter_edge_type(slot: str, label: Optional[str] = None) -> Optional[str]:
    """slot + label → 엣지 타입 이름.

    우선순위:
      1. label 이 ASCII snake 로 깔끔하게 변환되면 `has_{label_snake}` 사용
         (예: label="doc_type" → `has_doc_type`, label="Product Type" → `has_product_type`)
      2. 실패 시 slot suffix 로 fallback (예: slot="f_str_1" → `has_1`)

    LLM 이 한글 label 을 번역해 미리 생성한 이름이 있으면 상위 호출자가
    override 로 주입 — 이 함수는 기본 규칙만 안다.
    """
    snake = _label_to_snake(label)
    if snake:
        return f"has_{snake}"
    suffix = _slot_suffix(slot)
    if not suffix:
        return None
    return f"has_{suffix}"


_EDGE_NAME_SYSTEM_PROMPT = """You name knowledge-graph edges.

Given a list of KB filter labels (may be Korean, English, or mixed), propose a concise snake_case edge name in the form `has_<attr>` for each. The attribute name must be ASCII lowercase snake_case, 1-3 words, semantically translated from the label into English.

Output ONLY a JSON object in this exact shape (no markdown, no commentary):
{"edges": [{"slot": "<slot key>", "name": "has_<attr>"}, ...]}

Rules:
- Every input slot MUST appear exactly once in the output.
- `name` MUST start with `has_` and contain only [a-z0-9_].
- Keep it short and idiomatic English. Translate the semantic meaning of the label rather than transliterating it — non-English labels should be rendered as natural English terms, not romanized.
- If the label is unclear or too generic, pick a reasonable name from the filter metadata (type, sample values) provided.
"""


async def suggest_filter_edge_names(
    app,
    model_id: Optional[str],
    items: list[dict],
) -> dict[str, str]:
    """label 이 한글/비ASCII 인 slot 들만 LLM 에 배치 호출해 snake_case 엣지
    이름을 제안받는다.

    ``items``: ``[{"slot", "label", "type", "allowed_values"?}, ...]``.
    반환: ``{slot: "has_xxx"}``. LLM 호출 실패시 빈 dict.

    호출자가 이미 규칙 기반으로 생성 가능한 항목은 제외한 뒤 전달해야 한다.
    """
    if not items:
        return {}
    try:
        from extension_modules.utils.llm import (
            create_llm,
            get_model_config_from_app,
        )
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception as e:
        log.warning(f"[edge_name_llm] import failed: {e}")
        return {}

    # 모델 resolve (지정 없으면 첫 사용 가능 모델)
    config = get_model_config_from_app(app, model_id) if model_id else None
    if not config:
        try:
            available = list(getattr(app.state, "MODELS", {}).values())
            for m in available:
                mid = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
                if mid:
                    config = get_model_config_from_app(app, mid)
                    if config:
                        break
        except Exception:
            pass
    if not config:
        log.warning("[edge_name_llm] no LLM model available")
        return {}

    llm = create_llm(config, streaming=False, model_kwargs={"temperature": 0.0})

    # 사용자 프롬프트 — slot/label/type/예시값
    lines = ["Slots to name:"]
    for it in items:
        slot = it.get("slot")
        label = it.get("label") or ""
        ftype = it.get("type") or ""
        vals = it.get("allowed_values") or []
        sample = ", ".join(v for v in vals[:5] if isinstance(v, str))
        extra = f" examples: [{sample}]" if sample else ""
        lines.append(f'- slot="{slot}" label="{label}" type="{ftype}"{extra}')
    user_prompt = "\n".join(lines)

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=_EDGE_NAME_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
    except Exception as e:
        log.warning(f"[edge_name_llm] LLM call failed: {e}")
        return {}

    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        parts: list[str] = []
        for blk in raw:
            if isinstance(blk, dict):
                t = blk.get("text") or blk.get("content")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(blk, str):
                parts.append(blk)
        raw = "".join(parts)
    parsed = _extract_json(raw if isinstance(raw, str) else str(raw))
    if not parsed or not isinstance(parsed.get("edges"), list):
        log.warning(f"[edge_name_llm] invalid response: {str(raw)[:200]}")
        return {}

    out: dict[str, str] = {}
    valid_slots = {it["slot"] for it in items if it.get("slot")}
    for entry in parsed["edges"]:
        if not isinstance(entry, dict):
            continue
        slot = entry.get("slot")
        name = entry.get("name")
        if not slot or slot not in valid_slots or not isinstance(name, str):
            continue
        # sanitize
        n = _EDGE_SNAKE_RE.sub("_", name.strip()).strip("_").lower()
        if not n:
            continue
        if not n.startswith("has_"):
            n = f"has_{n}"
        # `has_` 뒤가 빈 상태/숫자뿐이면 스킵
        tail = n[4:]
        if not tail or tail.isdigit():
            continue
        out[slot] = n

    log.info(f"[edge_name_llm] suggested {len(out)}/{len(items)} names: {out}")
    return out


def _glossary_term_lookup(glossary_id: Optional[str]) -> dict[str, dict]:
    """glossary 의 term label 을 정규화 키로 인덱싱해 lookup 용 dict 반환.

    value: ``{"entry_id", "term", "category"}``. synonym 도 같은 entry 를 가리키게
    포함 — filter 값이 synonym 과 매치돼도 canonical term 노드로 귀결되게 한다.
    """
    if not glossary_id:
        return {}
    try:
        from open_webui.models.glossary import Glossaries

        g = Glossaries.get_glossary_by_id(glossary_id)
    except Exception as e:
        log.warning(f"[filter→attr] glossary lookup failed ({glossary_id[:8]}): {e}")
        return {}
    if not g:
        return {}
    entries = (g.data or {}).get("entries") or []
    out: dict[str, dict] = {}
    for e in entries:
        eid = e.get("id")
        term = (e.get("term") or "").strip()
        cat = e.get("category")
        if not eid or not term:
            continue
        base = {"entry_id": eid, "term": term, "category": cat}
        out.setdefault(_normalize_entity_label(term), base)
        for syn in e.get("synonyms") or []:
            s = (syn or "").strip()
            if s:
                out.setdefault(_normalize_entity_label(s), base)
    return out


def build_filter_attr_map(
    kg_id: str,
    knowledge_id: str,
    allowed_slots: list[str],
    glossary_id: Optional[str] = None,
    edge_name_overrides: Optional[dict[str, str]] = None,
) -> dict[str, list[dict]]:
    """사용자가 선택한 필터 slot 들의 값을 파일별로 수집해 attr 엣지 맵을 빌드.

    ``allowed_slots``: 이 KB 에서 노드로 승격할 slot 키 리스트. 비어 있으면
    아무것도 생성하지 않고 바로 반환. (링크 설정 UI 에서 사용자가 명시적으로
    체크한 slot 들이 전달된다.)

    반환 구조::

        {
          file_id: [
            {
              "node_id":   doc_attr 또는 term 노드 id,
              "label":     노드 라벨 (사용자에게 보이는 값),
              "slot":      원본 slot 키 (예: "f_str_country"),
              "edge_type": "has_country",
              "is_term":   True if 링크 glossary term 에 매치돼 재사용됨,
              "category":  term 재사용 시 해당 카테고리 (엣지 properties 용),
            },
            ...
          ]
        }

    - glossary 필터는 이미 앵커 매핑 전용이라 ``allowed_slots`` 에 있어도 **제외**.
    - value 가 list 면 원소별로 엣지 생성 (multi 필터 대응).
    - value 가 None/빈 문자열/빈 리스트면 skip.
    - int/date 값은 str 로 변환해서 라벨로 사용.
    """
    if not allowed_slots:
        return {}

    try:
        kb = Knowledges.get_knowledge_by_id(knowledge_id)
    except Exception as e:
        log.warning(f"[filter→attr] KB fetch failed ({knowledge_id[:8]}): {e}")
        return {}
    if not kb:
        return {}

    allowed_set = {s for s in allowed_slots if isinstance(s, str) and s}
    filter_schema: list[dict] = (kb.meta or {}).get("filter_schema") or []
    target_fields: list[dict] = []
    for f in filter_schema:
        if not isinstance(f, dict):
            continue
        if f.get("type") == "glossary":
            continue  # 앵커 매핑 전용
        slot = f.get("slot")
        if not slot or slot not in allowed_set:
            continue
        if not _filter_edge_type(slot, f.get("label")):
            continue
        target_fields.append(f)

    if not target_fields:
        return {}

    term_lookup = _glossary_term_lookup(glossary_id)
    file_metadata: dict = (kb.data or {}).get("file_metadata") or {}

    attr_map: dict[str, list[dict]] = {}
    for file_id, meta in file_metadata.items():
        if not isinstance(meta, dict):
            continue
        file_rows: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()  # (slot, normalized_label)
        for f in target_fields:
            slot = f["slot"]
            # 우선 링크에 저장된 LLM 제안 이름이 있으면 사용, 없으면 규칙 기반
            edge_type: Optional[str] = None
            if edge_name_overrides:
                edge_type = edge_name_overrides.get(slot)
            if not edge_type:
                edge_type = _filter_edge_type(slot, f.get("label"))
            if not edge_type:
                continue
            raw = meta.get(slot)
            if raw is None or raw == "" or raw == []:
                continue
            values: list = raw if isinstance(raw, list) else [raw]
            for v in values:
                if v is None:
                    continue
                label = str(v).strip()
                if not label:
                    continue
                norm = _normalize_entity_label(label)
                dedup_key = (slot, norm)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                # glossary term 매치 시 term 노드 재사용
                hit = term_lookup.get(norm)
                if hit:
                    node_id = make_node_id(
                        kg_id, "glossary", glossary_id, "term", hit["entry_id"]
                    )
                    file_rows.append(
                        {
                            "node_id": node_id,
                            "label": hit["term"],
                            "slot": slot,
                            "edge_type": edge_type,
                            "is_term": True,
                            "category": hit.get("category"),
                        }
                    )
                else:
                    node_id = _entity_node_id(kg_id, knowledge_id, f"{slot}::{label}")
                    file_rows.append(
                        {
                            "node_id": node_id,
                            "label": label,
                            "slot": slot,
                            "edge_type": edge_type,
                            "is_term": False,
                            "category": None,
                        }
                    )
        if file_rows:
            attr_map[file_id] = file_rows

    log.info(
        f"[filter→attr] KB {knowledge_id[:8]}: "
        f"{len(attr_map)} files, "
        f"{sum(len(v) for v in attr_map.values())} attr edges, "
        f"slots={[f['slot'] for f in target_fields]}"
    )
    return attr_map


_PUNCT_RE = re.compile(r"[\s\-_·.,;:!?()（）「」『』【】]+")


def _normalize_entity_label(name: str) -> str:
    """엔티티 라벨 정규화 (dedup 키).

    Phase 1: 단순 lower().strip() 에서 아래 규칙으로 확장
    - 공백/하이픈/언더스코어/중점 등 구두점을 단일 공백으로 치환
    - 양끝 공백 제거 + 소문자 변환

    예: "Samsung SDS", "samsung_sds", "samsung-SDS" → "samsung sds"
        "삼성 SDS", "삼성SDS" → "삼성 sds" (한글은 원본 유지)
    """
    return _PUNCT_RE.sub(" ", name).strip().lower()


def _entity_node_id(kg_id: str, knowledge_id: str, label: str) -> str:
    """엔티티 노드의 결정적 ID. 같은 KB 내에서 같은 라벨 = 같은 노드."""
    # Slice 1의 make_node_id가 한글 sanitize 처리
    return make_node_id(
        kg_id, "kb", knowledge_id, "entity", _normalize_entity_label(label)
    )


async def sync_kb_to_kg(
    app,
    kg_id: str,
    knowledge_id: str,
    user_id: str,
    pre_resolved_model_config: Optional[dict] = None,
    model_id: Optional[str] = None,
    max_chunks: Optional[int] = None,
    min_confidence: float = 0.6,
    processed_chunk_ids: Optional[set[str]] = None,
    entity_context_map: Optional[dict[str, list[dict]]] = None,
    cleanup_only: bool = False,
) -> Optional[dict]:
    """KB 문서 청크 → LLM 추출 → KG 엔티티/관계 노드/엣지.

    Incremental: `processed_chunk_ids`에 들어있는 청크 ID는 건너뛴다.
    호출자(라우터)가 KG `data.kb_extract_state`에 처리 이력을 저장하고,
    이 함수의 응답 `processed_chunk_ids` 필드에 *이번 실행에서 처리한*
    chunk_ids를 받아 union해서 다음 호출에 넘겨준다.

    Args:
        app: FastAPI app (search engine + LLM 접근용)
        kg_id: 대상 KG
        knowledge_id: 분석할 Knowledge Base ID
        user_id: 노드/엣지 owner
        pre_resolved_model_config: 백그라운드에서 안전하게 쓸 LLM config (필수)
        model_id: fallback용 (pre_resolved가 없을 때)
        max_chunks: 옵션 안전 캡. None이면 미처리 청크 *전체* 처리.
            큰 KB에서 한 번에 너무 많은 LLM 호출이 일어나는 걸 막고 싶을 때만 사용.
        min_confidence: 이 값 미만의 엔티티/관계는 skip
        processed_chunk_ids: 이미 처리한 청크 ID 집합 (이번 호출에서 skip)
        cleanup_only: True면 LLM 호출 없이 drift cleanup만 수행하고 반환.
            KB에서 파일 몇 개만 삭제했을 때 비용 없이 KG를 동기화할 때 사용.

    Returns:
        통계 dict 또는 None. `processed_chunk_ids` 필드에 *이번 호출에서*
        실제로 처리한 chunk_ids set이 들어있다 (호출자가 union 하기 위함).
    """
    # cleanup-only 모드는 LLM이 필요 없음. 그 외에는 미리 검증.
    llm = None
    if not cleanup_only:
        if not pre_resolved_model_config and not model_id:
            return {
                "knowledge_id": knowledge_id,
                "chunks_processed": 0,
                "entities_created": 0,
                "edges_created": 0,
                "errors": ["model config or model_id required"],
            }

        # LLM 준비
        try:
            llm_config = pre_resolved_model_config
            if not llm_config:
                from extension_modules.utils.llm import get_model_config_from_app

                llm_config = get_model_config_from_app(app, model_id)
            if not llm_config:
                return {
                    "knowledge_id": knowledge_id,
                    "chunks_processed": 0,
                    "entities_created": 0,
                    "edges_created": 0,
                    "errors": [f"Model config not found: {model_id}"],
                }
            llm = create_llm(
                llm_config, streaming=False, model_kwargs={"temperature": 0.2}
            )
        except Exception as e:
            return {
                "knowledge_id": knowledge_id,
                "chunks_processed": 0,
                "entities_created": 0,
                "edges_created": 0,
                "errors": [f"Failed to create LLM: {e}"],
            }

    # AGE dual-write (없으면 SQL-only)
    age = get_age_service(kg_id)

    # KB 전체 청크 fetch (incremental 처리를 위해 일단 다 가져온 뒤 필터)
    # query_by_metadata 기본 limit이 10000이라 일반 KB는 한 번에 처리 가능.
    try:
        knowledge_service = SearchEngineKnowledge(app=app, collection_name=knowledge_id)
        all_chunks = await knowledge_service.query_by_metadata({}, limit=10000)
    except Exception as e:
        return {
            "knowledge_id": knowledge_id,
            "total_chunks": 0,
            "chunks_processed": 0,
            "entities_created": 0,
            "entities_linked": 0,
            "edges_created": 0,
            "processed_chunk_ids": set(),
            "removed_chunk_ids": set(),
            "nodes_pruned": 0,
            "chunks_unlinked": 0,
            "errors": [f"Failed to fetch chunks: {e}"],
        }

    if not all_chunks:
        # 모든 청크가 사라진 케이스 — 이전에 처리한 게 있으면 그 KB의 doc_entity를
        # 전부 정리한다 (KB 비우기 시나리오).
        already = processed_chunk_ids or set()
        nodes_pruned_empty = 0
        if already:
            try:
                # 이 KB의 모든 doc_entity를 한 번에 제거 (manual 엣지 포함)
                nodes_pruned_empty = KnowledgeGraphs.delete_nodes_by_source(
                    kg_id, "kb", knowledge_id, include_manual_edges=True
                )
                if age:
                    age_cleanup(age, "source_id", knowledge_id)
                log.info(
                    f"[KB→KG] kb={knowledge_id} emptied — "
                    f"pruned {nodes_pruned_empty} doc_entity nodes"
                )
            except Exception as e:
                log.exception(
                    f"[KB→KG] failed to prune doc_entities for empty kb={knowledge_id}: {e}"
                )
        return {
            "knowledge_id": knowledge_id,
            "total_chunks": 0,
            "chunks_processed": 0,
            "entities_created": 0,
            "entities_linked": 0,
            "edges_created": 0,
            "processed_chunk_ids": set(),
            "removed_chunk_ids": already,  # 모든 청크가 사라짐
            "nodes_pruned": nodes_pruned_empty,
            "chunks_unlinked": 0,
            "errors": ["KB has no documents — all entities pruned"]
            if already
            else ["KB has no documents — upload files first"],
        }

    total_chunks = len(all_chunks)
    current_chunk_ids: set[str] = {c.id for c in all_chunks}
    already_processed = processed_chunk_ids or set()
    pending_chunks = [c for c in all_chunks if c.id not in already_processed]

    # ──────────────────────────────────────────────
    # KB Drift cleanup — 사라진 청크 감지
    # ──────────────────────────────────────────────
    # processed_chunk_ids 중 현재 KB에 더 이상 존재하지 않는 청크 = 삭제됨
    # (또는 파일 재업로드로 chunk_id가 갱신됨). 그 청크에서 추출된 doc_entity
    # 노드의 source_ref.chunk_ids 에서 제거하고, reference가 모두 사라진
    # 노드는 노드 + 엣지까지 삭제한다.
    removed_chunk_ids: set[str] = already_processed - current_chunk_ids
    nodes_pruned = 0
    chunks_unlinked = 0
    if removed_chunk_ids:
        try:
            kb_doc_entities = KnowledgeGraphs.get_nodes_by_source(
                kg_id=kg_id, source_kind="kb", source_id=knowledge_id
            )
            for entity in kb_doc_entities:
                source_ref = dict(entity.source_ref or {})
                refs: list[str] = list(source_ref.get("chunk_ids") or [])
                if not refs:
                    continue
                kept = [c for c in refs if c not in removed_chunk_ids]
                removed_for_node = len(refs) - len(kept)
                if removed_for_node == 0:
                    continue
                chunks_unlinked += removed_for_node
                if not kept:
                    # reference 0개 → 노드 삭제 (엣지까지)
                    if KnowledgeGraphs.delete_node_by_id(entity.id):
                        nodes_pruned += 1
                        # AGE dual-write
                        if age:
                            try:
                                age.delete_nodes_by_property(
                                    entity.node_type, "node_id", entity.id
                                )
                            except Exception:
                                pass
                else:
                    # reference 일부 남음 → source_ref만 갱신
                    source_ref["chunk_ids"] = kept
                    KnowledgeGraphs.upsert_node(
                        kg_id=kg_id,
                        user_id=entity.user_id,
                        node_id=entity.id,
                        node_type=entity.node_type,
                        label=entity.label,
                        properties=entity.properties,
                        source_ref=source_ref,
                    )
                    # AGE dual-write
                    if age:
                        age_upsert_node(
                            age,
                            entity.node_type,
                            entity.id,
                            entity.label,
                            entity.properties,
                            kg_id=kg_id,
                        )
        except Exception as e:
            log.exception(f"[KB→KG] drift cleanup failed for kb={knowledge_id}: {e}")

    log.info(
        f"[KB→KG] kb={knowledge_id}: {total_chunks} total, "
        f"{len(already_processed)} already processed, "
        f"{len(pending_chunks)} pending, "
        f"{len(removed_chunk_ids)} drifted (pruned {nodes_pruned} nodes / "
        f"unlinked {chunks_unlinked} chunk refs)"
    )

    # cleanup-only 모드: drift cleanup만 하고 끝낸다 (LLM 호출 없음, 무료)
    if cleanup_only:
        return {
            "knowledge_id": knowledge_id,
            "total_chunks": total_chunks,
            "chunks_processed": 0,
            "entities_created": 0,
            "entities_linked": 0,
            "edges_created": 0,
            "processed_chunk_ids": set(),
            "removed_chunk_ids": removed_chunk_ids,
            "nodes_pruned": nodes_pruned,
            "chunks_unlinked": chunks_unlinked,
            "errors": [],
        }

    if not pending_chunks:
        return {
            "knowledge_id": knowledge_id,
            "total_chunks": total_chunks,
            "chunks_processed": 0,
            "entities_created": 0,
            "entities_linked": 0,
            "edges_created": 0,
            "processed_chunk_ids": set(),
            "removed_chunk_ids": removed_chunk_ids,
            "nodes_pruned": nodes_pruned,
            "chunks_unlinked": chunks_unlinked,
            "errors": [],
        }

    # max_chunks는 옵션 안전 캡 (1회 호출에서 처리할 최대 미처리 청크 수)
    if max_chunks is not None and max_chunks > 0:
        chunks = pending_chunks[:max_chunks]
        if len(pending_chunks) > max_chunks:
            log.info(
                f"[KB→KG] kb={knowledge_id}: max_chunks={max_chunks} cap applied, "
                f"{len(pending_chunks) - max_chunks} chunks deferred to next run"
            )
    else:
        chunks = pending_chunks

    # ──────────────────────────────────────────────
    # Entity linking 시드 — KG에 이미 있는 anchor 노드들
    # ──────────────────────────────────────────────
    # KB 추출 *전에* 용어집/DbSphere/이전 KB가 동기화되어 있어야 의미가 있다.
    # 여기서 anchor 노드(term, concept, column, table, 그리고 이전에 만들어진
    # doc_entity)를 모두 fetch해서:
    #   1. LLM 프롬프트에 known entity 목록으로 주입 → coreference 유도
    #   2. 라벨 정규화 사전을 만들어, 추출 결과의 entity 라벨이 매치되면
    #      doc_entity 신규 생성 대신 *기존 노드 ID를 재사용*
    # 이게 없으면 같은 "VIP 고객"이 용어집 term + KB doc_entity로 분리되어
    # 그래프가 단편화되고 멀티홉 추론이 끊긴다.
    anchor_label_to_id: dict[str, str] = {}
    known_entity_labels: list[str] = []
    try:
        for anchor_type in (
            NodeType.TERM,
            NodeType.CONCEPT,
            NodeType.COLUMN,
            NodeType.TABLE,
            NodeType.DOC_ENTITY,
        ):
            anchor_nodes = KnowledgeGraphs.get_nodes(
                kg_id=kg_id, node_type=anchor_type, limit=2000
            )
            for n in anchor_nodes:
                key = _normalize_entity_label(n.label)
                if not key or key in anchor_label_to_id:
                    continue
                anchor_label_to_id[key] = n.id
                known_entity_labels.append(n.label)
    except Exception as e:
        log.warning(f"[KB→KG] failed to load anchor entities for linking: {e}")

    log.info(
        f"[KB→KG] entity linking seed: {len(anchor_label_to_id)} known anchors "
        f"loaded for kg={kg_id}"
    )

    # 기본 시스템 프롬프트 (entity_context 없는 버전)
    base_system_prompt = _build_system_prompt(known_entity_labels)

    # 파일별 엔티티 컨텍스트 맵 (지식 연결에서 매칭된 결과)
    # {file_id: [{"entity_node_id": ..., "entity_label": ..., "page_range": ...}]}
    _entity_map: dict[str, list[dict]] = entity_context_map or {}

    # Phase 2 계층: KB 컨테이너 노드 (doc/chunk 는 청크 루프에서 dedup)
    try:
        kb_row = Knowledges.get_knowledge_by_id(knowledge_id)
    except Exception:
        kb_row = None
    kb_nid = ensure_kb_container_node(
        kg_id=kg_id,
        knowledge_id=knowledge_id,
        user_id=user_id,
        age=age,
        kb_name=getattr(kb_row, "name", None) if kb_row else None,
        kb_description=getattr(kb_row, "description", None) if kb_row else None,
    )
    # file_id → doc_nid dedup (청크 루프 중 처음 만나면 upsert)
    _doc_nid_by_file: dict[str, str] = {}
    # file_id → 해당 파일의 청크 ordinal 카운터
    _file_chunk_counter: dict[str, int] = {}

    entities_created = 0
    entities_linked = 0  # anchor에 매치되어 새로 만들지 않은 횟수
    edges_created = 0
    chunks_processed = 0
    newly_processed_ids: set[str] = set()
    errors: list[str] = []

    for chunk in chunks:
        chunk_id = chunk.id
        content = (chunk.content or "").strip()
        if not content or len(content) < 50:
            continue

        # ── Phase 2 계층: document 노드 upsert (idempotent) ──
        # CHUNK 노드는 더 이상 만들지 않는다 — KG 는 의미 그래프, 청크 단위
        # 검색은 KB 벡터스토어가 file_id 로 hit 후 자체 처리.
        chunk_file_id_for_hier = (
            (chunk.metadata or {}).get("file_id") if chunk.metadata else None
        )
        chunk_doc_nid: Optional[str] = None
        if chunk_file_id_for_hier:
            chunk_doc_nid = _doc_nid_by_file.get(chunk_file_id_for_hier)
            if chunk_doc_nid is None:
                chunk_doc_nid = ensure_document_node(
                    kg_id=kg_id,
                    knowledge_id=knowledge_id,
                    file_id=chunk_file_id_for_hier,
                    user_id=user_id,
                    age=age,
                    kb_nid=kb_nid,
                )
                _doc_nid_by_file[chunk_file_id_for_hier] = chunk_doc_nid

        # 너무 긴 청크는 잘라서 LLM에 전달 (token cost 절감)
        if len(content) > 4000:
            content = content[:4000]

        # ── 지식 연결 엔티티 컨텍스트 결정 ──
        # 이 청크의 file_id 로 매칭된 용어 라벨을 찾고, page 범위가 있으면 해당
        # 청크의 page 와 대조해서 적절한 엔티티만 선택. 결과는 LLM system prompt
        # 의 "이 청크는 X 라는 것에 대한 문서다" 텍스트 hint 로만 사용된다.
        chunk_entity_context = None
        chunk_file_id = (chunk.metadata or {}).get("file_id")
        if chunk_file_id and chunk_file_id in _entity_map:
            file_entities = _entity_map[chunk_file_id]
            chunk_page = int((chunk.metadata or {}).get("page", -1))

            matched_for_chunk = []
            for ent in file_entities:
                page_range = ent.get("page_range")
                if page_range and chunk_page >= 0:
                    try:
                        parts = str(page_range).split("-")
                        start_page = int(parts[0].strip())
                        end_page = (
                            int(parts[-1].strip()) if len(parts) > 1 else start_page
                        )
                        if start_page <= chunk_page <= end_page:
                            matched_for_chunk.append(ent)
                    except (ValueError, IndexError):
                        matched_for_chunk.append(ent)
                else:
                    matched_for_chunk.append(ent)

            if matched_for_chunk:
                labels = [e["entity_label"] for e in matched_for_chunk]
                chunk_entity_context = (
                    f"This chunk is part of a document about: {', '.join(labels)}."
                )

        # 엔티티 컨텍스트가 있으면 확장된 프롬프트, 없으면 기본
        system_prompt = (
            _build_system_prompt(known_entity_labels, chunk_entity_context)
            if chunk_entity_context
            else base_system_prompt
        )

        prompt = f"Source chunk id: {chunk_id}\n\nText:\n{content}\n"

        try:
            import asyncio as _asyncio

            response = await _asyncio.wait_for(
                llm.ainvoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=prompt),
                    ]
                ),
                timeout=300.0,
            )
            content_resp = (
                response.content if hasattr(response, "content") else str(response)
            )
        except Exception as e:
            errors.append(f"LLM call failed for chunk {chunk_id[:20]}: {e}")
            continue

        parsed = _extract_json(content_resp)
        if not parsed:
            errors.append(
                f"Invalid JSON for chunk {chunk_id[:20]}: {content_resp[:100]}"
            )
            continue

        chunks_processed += 1
        newly_processed_ids.add(chunk_id)

        # entities
        entity_label_to_node_id: dict[str, str] = {}
        for ent in parsed.get("entities", []) or []:
            name = (ent.get("name") or "").strip()
            etype = (ent.get("type") or "concept").strip()
            confidence = ent.get("confidence", 0)
            if not name or confidence < min_confidence:
                continue

            normalized = _normalize_entity_label(name)

            # ── Entity linking: 기존 anchor 노드와 매치되면 재사용 ──
            anchor_id = anchor_label_to_id.get(normalized)
            if anchor_id:
                entity_label_to_node_id[normalized] = anchor_id
                entities_linked += 1
                # anchor 노드는 용어집/DbSphere가 owner라 properties는 건드리지
                # 않는다. (KB 멘션 추적이 필요하면 별도 source_ref 갱신 함수를
                # 만들어야 하지만, 일단 멀티홉 동작이 우선.)
                continue

            # ── 매치 없음 → 새 doc_entity 노드 생성 (기존 동작) ──
            node_id = _entity_node_id(kg_id, knowledge_id, name)
            entity_label_to_node_id[normalized] = node_id

            # upsert (이미 있으면 source_ref만 업데이트)
            existing = KnowledgeGraphs.get_node_by_id(node_id)
            existing_chunks = []
            if existing and existing.source_ref:
                existing_chunks = existing.source_ref.get("chunk_ids") or []
            if chunk_id not in existing_chunks:
                existing_chunks.append(chunk_id)

            node = KnowledgeGraphs.upsert_node(
                kg_id=kg_id,
                user_id=user_id,
                node_id=node_id,
                node_type=NodeType.DOC_ENTITY,
                label=name,
                properties={
                    "entity_type": etype,
                    "confidence": confidence,
                },
                source_ref={
                    "kind": "kb",
                    "knowledge_id": knowledge_id,
                    # 메모리 보호: 최근 20개 chunk_id만 유지 ([-20:] 로 새 chunk
                    # 도 보존; 이전 [:20] 은 21번째 chunk_id 가 잘려나가는 버그)
                    "chunk_ids": existing_chunks[-20:],
                },
            )
            if age:
                age_upsert_node(
                    age,
                    NodeType.DOC_ENTITY,
                    node_id,
                    name,
                    {
                        "entity_type": etype,
                        "confidence": confidence,
                        "source_kind": "kb",
                        "source_id": knowledge_id,
                    },
                    kg_id=kg_id,
                )

            # Phase 2 provenance: doc_entity → DOCUMENT
            if chunk_doc_nid:
                add_extracted_from_edge(
                    kg_id=kg_id,
                    user_id=user_id,
                    doc_entity_node_id=node_id,
                    doc_nid=chunk_doc_nid,
                    age=age,
                )

            if node and not existing:
                entities_created += 1
                # 새로 만든 doc_entity도 같은 KB의 다음 청크부터는 anchor로 활용
                # (LLM 프롬프트에는 못 넣지만 라벨 매치는 가능)
                anchor_label_to_id[normalized] = node_id

        # relationships
        for rel in parsed.get("relationships", []) or []:
            from_label = (rel.get("from") or "").strip()
            to_label = (rel.get("to") or "").strip()
            rtype = (rel.get("type") or "related_to").strip()
            confidence = rel.get("confidence", 0)
            if not from_label or not to_label or confidence < min_confidence:
                continue

            from_norm = _normalize_entity_label(from_label)
            to_norm = _normalize_entity_label(to_label)
            # 이번 청크의 entities에서 우선 lookup, 없으면 anchor 사전 fallback
            # (LLM이 entities 목록 누락 + relationship에만 등장시키는 케이스 방어)
            from_id = entity_label_to_node_id.get(from_norm) or anchor_label_to_id.get(
                from_norm
            )
            to_id = entity_label_to_node_id.get(to_norm) or anchor_label_to_id.get(
                to_norm
            )
            if not from_id or not to_id or from_id == to_id:
                continue

            # LLM 관계 라벨을 canonical edge type으로 변환.
            # 원본 라벨은 properties.relation_label에 보존.
            canonical_type = resolve_llm_edge_type(rtype)

            rel_props = {"relation_label": rtype, "from_chunk": chunk_id}
            edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=from_id,
                dst_id=to_id,
                edge_type=canonical_type,
                source=EdgeSource.LLM_EXTRACT,
                weight=confidence,
                properties=rel_props,
            )
            if age:
                # 실제 노드 타입 조회 (anchor 매치 시 DOC_ENTITY가 아닐 수 있음)
                from_node = KnowledgeGraphs.get_node_by_id(from_id)
                to_node = KnowledgeGraphs.get_node_by_id(to_id)
                from_type = from_node.node_type if from_node else NodeType.DOC_ENTITY
                to_type = to_node.node_type if to_node else NodeType.DOC_ENTITY
                age_upsert_edge(
                    age,
                    canonical_type,
                    from_type,
                    from_id,
                    to_type,
                    to_id,
                    source=EdgeSource.LLM_EXTRACT,
                    properties={**rel_props, "weight": confidence},
                    kg_id=kg_id,
                )
            if edge:
                edges_created += 1

    log.info(
        f"[KB→KG] knowledge_id={knowledge_id}: "
        f"{chunks_processed}/{len(chunks)} chunks processed this run, "
        f"{total_chunks} total in KB, "
        f"{entities_created} new entities, "
        f"{entities_linked} linked to existing anchors, "
        f"{edges_created} edges, "
        f"pruned {nodes_pruned} nodes / unlinked {chunks_unlinked} chunk refs, "
        f"{len(errors)} errors"
        f" (AGE={'enabled' if age else 'disabled'})"
    )
    return {
        "knowledge_id": knowledge_id,
        "total_chunks": total_chunks,
        "chunks_processed": chunks_processed,
        "entities_created": entities_created,
        "entities_linked": entities_linked,
        "edges_created": edges_created,
        "processed_chunk_ids": newly_processed_ids,
        "removed_chunk_ids": removed_chunk_ids,
        "nodes_pruned": nodes_pruned,
        "chunks_unlinked": chunks_unlinked,
        "errors": errors[:10],
    }
