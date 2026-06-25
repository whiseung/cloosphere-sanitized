"""KB 청크 단위 백그라운드 워커 (Slice 10).

전체 KB 추출을 청크 단위 task로 fan-out해서 Redis Streams 컨슈머가
병렬로 LLM 호출하게 만든다. 각 task는 max_retries=3 으로 재시도되고,
parent job(KGExtractJob)의 progress_current 카운터가 모든 청크 완료 시
finalization을 트리거한다.

흐름:
1. router에서 `enqueue_kb_extract()` 호출 → 모든 pending 청크에 대해
   `kg_kb_chunk` task publish + parent job 생성 (progress_total = chunk count)
2. 컨슈머가 task를 잡고 `process_kb_chunk_task()` 실행
3. 각 task: LLM 호출 → 엔티티 추출 → KG 업데이트 → counter ++
4. counter == total → 한 워커가 finalization 잡고 state 저장 + 재인덱싱
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from extension_modules.knowledge_graph.sync._age_helpers import (
    age_upsert_edge,
    age_upsert_node,
    get_age_service,
)
from extension_modules.knowledge_graph.sync.kb_sync import (
    _entity_node_id,
    _extract_json,
    _normalize_entity_label,
)
from extension_modules.utils.llm import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import (
    EdgeSource,
    EdgeType,
    KnowledgeGraphs,
    NodeType,
    normalize_edge_label,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def _record_processed_chunk(
    kg_id: str, knowledge_id: str, chunk_id: str, llm_config: Optional[Dict[str, Any]]
) -> None:
    """성공한 청크 1개를 kg_extract_state.processed_chunks 에 원자적 append.

    실패하거나 permanent_failure 된 청크는 여길 안 거치므로 다음 incremental
    sync 에서 다시 pending 으로 잡힌다. 이전엔 finalize 시점에 chunks_per_kb
    (계획 목록) 를 통으로 저장해서 실패 청크까지 박제되던 버그가 있었다.
    """
    try:
        model_id = (llm_config or {}).get("model_id", "") if llm_config else ""
        KnowledgeGraphs.append_processed_chunks(
            kg_id=kg_id,
            kb_id=knowledge_id,
            chunk_ids=[chunk_id],
            model_id=model_id,
        )
    except Exception as e:
        log.warning(
            f"[kb_chunk_worker] append_processed_chunks failed for "
            f"chunk={chunk_id[:8]}: {e}"
        )


# ─── Stage B: Schematized anchor-centric extraction ────────────────
# 청크당 LLM 은 "primary_anchor + attributes + cross_references" 스키마로 응답.
# 앵커가 없는 청크는 LLM 호출 자체를 skip 한다.


_STAGE_B_SYSTEM_PROMPT = """You are a domain-specific knowledge extractor for this knowledge graph.

Knowledge graph: {kg_name}
Domain: {kg_description}

This chunk is part of a document that the pipeline has already matched to the following **anchors** (canonical terms from the knowledge graph's glossary). Your job is to find the ONE anchor this chunk actually discusses, and extract its attributes.

Anchors available for this chunk (term node IDs with labels and categories):
{anchors_block}

{edge_types_block}

Output a single JSON object with this exact shape (no markdown, no commentary):
{{
  "primary_anchor_id": "<exact anchor id from the list above, or null if none is the subject of this chunk>",
  "attributes": [
    {{
      "slot": "<edge type name>",
      "value": "<short noun phrase, 30 chars or less>",
      "confidence": 0.0,
      "evidence": "<short original text snippet supporting this>"
    }}
  ],
  "cross_references": [
    {{
      "from_id": "<anchor id>",
      "to_label": "<label of another anchor in the list OR a new entity name>",
      "type": "<edge type name>",
      "confidence": 0.0
    }}
  ]
}}

Rules:
1. If this chunk does not specifically describe any anchor, return primary_anchor_id = null with empty arrays.
2. `slot` and `type` MUST come from the allowed edge types listed above. If nothing fits, drop that single attribute — but still extract other attributes that DO fit.
3. `value` must be a concise noun phrase (1-5 words). Prefer specific terms over bare single words ("간장애 환자" over "환자", "1일 3회" over "3회"). Skip pure boilerplate ("본 제품", "이 약", "상기 환자"). Stand-alone generic words are OK only when they are the actual attribute (e.g. target_population=소아).
4. Skip attributes where confidence < 0.6. Skip the entire extraction if the chunk is navigation/copyright/TOC/index text.
5. Limit: max 8 attributes and max 5 cross_references per chunk.
6. Use the same language as the source text for `value` (Korean if Korean source).
"""


def _format_anchors_block(anchors: list[dict]) -> str:
    lines = []
    for a in anchors[:40]:  # 안전 상한
        label = a.get("label") or a.get("entity_label") or ""
        node_id = a.get("node_id") or a.get("entity_node_id") or ""
        category = a.get("category") or ""
        if not (label and node_id):
            continue
        if category:
            lines.append(f'- id="{node_id}" label="{label}" category="{category}"')
        else:
            lines.append(f'- id="{node_id}" label="{label}"')
    return "\n".join(lines) if lines else "(none)"


def _format_edge_types_block(
    edge_types: Dict[str, dict],
    locked: bool = False,
) -> str:
    """카탈로그를 카테고리별로 그룹화해서 프롬프트 블록으로 변환.

    그룹:
    - 각 카테고리 (intra): `category` 필드 있는 항목
    - 범용 (category 없고 src/dst_category 도 없음)
    - cross-category 는 여기서 제외 (cross_references 경로 전용)
    """
    if not edge_types:
        if locked:
            return (
                "Edge type catalog is empty and locked. Do NOT extract any "
                "attributes or cross_references — return empty arrays."
            )
        return "Edge types already in use: (none yet — you may propose new snake_case names)"

    # 그룹화
    by_category: dict[str, list[tuple[str, dict]]] = {}
    universal: list[tuple[str, dict]] = []
    for name, info in edge_types.items():
        info = info or {}
        cat = info.get("category")
        src_cat = info.get("src_category")
        dst_cat = info.get("dst_category")
        if src_cat and dst_cat and src_cat != dst_cat and dst_cat != "doc_entity":
            # cross-category (두 term category 간) 는 Phase 3 전용.
            # dst="doc_entity" 는 속성 엣지라 cross 가 아님 — 유지.
            continue
        if cat:
            by_category.setdefault(cat, []).append((name, info))
        else:
            universal.append((name, info))

    def _format_entry(name: str, info: dict) -> str:
        display = info.get("display_name") or ""
        desc = info.get("description") or ""
        suffix_parts = []
        if display and display != name:
            suffix_parts.append(display)
        if desc:
            suffix_parts.append(desc)
        if suffix_parts:
            return f"- {name} — {' / '.join(suffix_parts)}"
        return f"- {name}"

    lines: list[str] = []
    if locked:
        lines.append(
            "Allowed edge types (STRICT — use ONLY these snake_case keys, "
            "do NOT invent new ones):"
        )
    else:
        lines.append("Edge types already in use (reuse these when the meaning fits):")

    # 카테고리별 그룹
    for cat in sorted(by_category.keys()):
        lines.append(f"\n### If primary_anchor category is '{cat}':")
        for name, info in sorted(by_category[cat], key=lambda x: x[0])[:30]:
            lines.append(_format_entry(name, info))

    if universal:
        lines.append("\n### Universal (any anchor category):")
        for name, info in sorted(universal, key=lambda x: x[0])[:30]:
            lines.append(_format_entry(name, info))

    if locked:
        lines.append(
            "\nIMPORTANT: Use the edge type from the section matching the primary_anchor's "
            "category. Universal types can be used for any anchor. If no listed edge type "
            "fits an observation, drop that observation."
        )
    return "\n".join(lines)


def _apply_schematized_extraction(
    kg_id: str,
    knowledge_id: str,
    user_id: str,
    chunk_id: str,
    parsed: Dict[str, Any],
    anchor_id_set: set[str],
    anchor_label_to_id: Dict[str, str],
    min_confidence: float,
    allowed_edge_types: Optional[set[str]] = None,
    edge_type_catalog: Optional[Dict[str, dict]] = None,
    anchor_category_by_id: Optional[Dict[str, str]] = None,
    provenance_node_id: Optional[str] = None,
) -> Dict[str, int]:
    """LLM schematized JSON 을 KG 에 upsert.

    - primary_anchor_id 검증 → 실패 시 전체 drop (앵커 없는 청크는 버림)
    - attributes[]: 각 slot 은 엣지 레지스트리에 등록될 예정, value 는 doc_entity 노드
    - cross_references[]: 앵커↔앵커 또는 앵커↔신규 doc_entity

    ``allowed_edge_types`` 가 주어지면 (locked 카탈로그) 해당 set 에 없는
    slot/type 은 폴백 없이 drop 한다.

    ``edge_type_catalog`` + ``anchor_category_by_id`` 가 주어지면 카테고리
    scope 필터링도 수행:
    - attribute slot 의 카탈로그 entry 가 ``category`` 를 가지고 있고,
      primary_anchor 의 카테고리와 다르면 drop (scope mismatch)
    - cross-category 항목(src/dst_category 있음)은 attributes 경로에서는 사용 불가
      (Phase 4 db_derivation 전용)

    리턴: {attributes_applied, cross_refs_applied, dropped_unknown_slot,
           dropped_scope_mismatch, new_edge_types}
    """
    primary_id = parsed.get("primary_anchor_id")
    if not primary_id or primary_id not in anchor_id_set:
        return {
            "attributes_applied": 0,
            "cross_refs_applied": 0,
            "dropped_unknown_slot": 0,
            "dropped_scope_mismatch": 0,
            "new_edge_types": [],
        }

    # anchor 의 카테고리 식별
    anchor_category: Optional[str] = None
    if anchor_category_by_id:
        anchor_category = anchor_category_by_id.get(primary_id)

    attrs_applied = 0
    xrefs_applied = 0
    dropped_unknown_slot = 0
    dropped_scope_mismatch = 0
    edge_labels_used: dict[str, str] = {}  # {normalized: evidence}

    # Provenance 엣지 대상: 항상 DOCUMENT (provenance_node_id 필수).
    # CHUNK 노드는 더 이상 KG 에 만들지 않는다.
    if not provenance_node_id:
        return {
            "attributes_applied": 0,
            "cross_refs_applied": 0,
            "dropped_unknown_slot": 0,
            "dropped_scope_mismatch": 0,
            "new_edge_types": [],
        }
    _prov_age = get_age_service(kg_id)
    _prov_target_nid = provenance_node_id  # always DOCUMENT nid

    # ── attributes: anchor → doc_entity(value) ──
    for attr in parsed.get("attributes", []) or []:
        slot_raw = (attr.get("slot") or "").strip()
        value = (attr.get("value") or "").strip()
        confidence = float(attr.get("confidence", 0) or 0)
        evidence = (attr.get("evidence") or "").strip()[:300]
        if not slot_raw or not value or confidence < min_confidence:
            continue
        if len(value) > 80:
            value = value[:80]

        slot = normalize_edge_label(slot_raw) or EdgeType.HAS_FEATURE
        if allowed_edge_types is not None and slot not in allowed_edge_types:
            dropped_unknown_slot += 1
            continue
        # 카테고리 scope 검증 — 카탈로그 항목의 category 필드가 있으면
        # anchor category 와 일치해야 함. cross-category 항목(src/dst 있음)은
        # attribute 경로에서는 drop (Phase 4 전용).
        if edge_type_catalog is not None:
            entry = edge_type_catalog.get(slot) or {}
            entry_src = entry.get("src_category")
            entry_dst = entry.get("dst_category")
            if (
                entry_src
                and entry_dst
                and entry_src != entry_dst
                and entry_dst != "doc_entity"
            ):
                dropped_scope_mismatch += 1
                continue
            entry_cat = entry.get("category")
            if entry_cat and anchor_category and entry_cat != anchor_category:
                dropped_scope_mismatch += 1
                continue
        edge_labels_used.setdefault(slot, evidence)

        # slot 별 namespace — 같은 value 라도 slot 이 다르면 별개 노드.
        value_label = f"{slot}::{value}"
        node_id = _entity_node_id(kg_id, knowledge_id, value_label)

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
            label=value,
            properties={
                "slot": slot,
                "confidence": confidence,
            },
            source_ref={
                "kind": "kb",
                "knowledge_id": knowledge_id,
                "slot": slot,
                "chunk_ids": existing_chunks[-20:],
            },
        )
        if not node:
            continue
        # label → id 매핑에도 저장 (cross_ref 에서 참조 가능)
        anchor_label_to_id.setdefault(_normalize_entity_label(value), node_id)
        # AGE 그래프에도 노드 등록 — 이후의 slot edge 가 dst 로 이 노드를 참조하므로
        # AGE 에 없으면 edge upsert 가 silent fail. SQL 만 채우고 AGE 비워두는 패턴은
        # KnowledgeGraphs.upsert_edge 와 동일 — 호출자(여기) 가 명시적으로 짝맞춰야 한다.
        if _prov_age is not None:
            age_upsert_node(
                _prov_age,
                NodeType.DOC_ENTITY,
                node_id,
                value,
                {"slot": slot, "confidence": confidence},
                kg_id=kg_id,
            )

        # 사용자 요구 topology: term → [mentions] → document → [slot] → doc_entity.
        # 즉 엣지의 src 는 primary_anchor (term) 가 아니라 document 여야 한다.
        # term 은 properties.primary_term_id 로 기록해 추적성 유지.
        slot_edge_props = {
            "relation_label": slot_raw,
            "primary_term_id": primary_id,
            "from_chunk": chunk_id,
            "evidence": evidence,
        }
        edge = KnowledgeGraphs.upsert_edge(
            kg_id=kg_id,
            user_id=user_id,
            src_id=_prov_target_nid,  # document
            dst_id=node_id,  # doc_entity
            edge_type=slot,
            source=EdgeSource.LLM_EXTRACT,
            weight=confidence,
            properties=slot_edge_props,
        )
        if edge:
            attrs_applied += 1
            # AGE 그래프에도 동일 엣지 작성 — KGEdge SQL 만 채우고 그래프를 비워두면
            # kg_neighbors / kg_cypher 같은 그래프 트래버설이 slot 엣지를 못 본다.
            # weight 는 age_upsert_edge 시그니처에 없으므로 properties 로 전달.
            if _prov_age is not None:
                age_upsert_edge(
                    _prov_age,
                    slot,
                    NodeType.DOCUMENT,
                    _prov_target_nid,
                    NodeType.DOC_ENTITY,
                    node_id,
                    source=EdgeSource.LLM_EXTRACT,
                    properties={**slot_edge_props, "weight": confidence},
                    kg_id=kg_id,
                )

    # ── cross_references: anchor → anchor(또는 새 doc_entity) ──
    for xref in parsed.get("cross_references", []) or []:
        from_id = (xref.get("from_id") or "").strip()
        to_label = (xref.get("to_label") or "").strip()
        rtype_raw = (xref.get("type") or "").strip()
        confidence = float(xref.get("confidence", 0) or 0)
        if not from_id or from_id not in anchor_id_set:
            continue
        if not to_label or confidence < min_confidence:
            continue

        rtype = normalize_edge_label(rtype_raw) or EdgeType.HAS_FEATURE
        if allowed_edge_types is not None and rtype not in allowed_edge_types:
            dropped_unknown_slot += 1
            continue
        # cross-category 엣지 타입은 Phase 4 db_derivation 전용 — 여기서 drop
        if edge_type_catalog is not None:
            entry = edge_type_catalog.get(rtype) or {}
            if (
                entry.get("src_category")
                and entry.get("dst_category")
                and entry.get("src_category") != entry.get("dst_category")
                and entry.get("dst_category") != "doc_entity"
            ):
                dropped_scope_mismatch += 1
                continue
        edge_labels_used.setdefault(rtype, "")

        to_norm = _normalize_entity_label(to_label)
        to_id = anchor_label_to_id.get(to_norm)
        if not to_id:
            # 새 doc_entity 노드로 등록
            to_id = _entity_node_id(kg_id, knowledge_id, to_label)
            KnowledgeGraphs.upsert_node(
                kg_id=kg_id,
                user_id=user_id,
                node_id=to_id,
                node_type=NodeType.DOC_ENTITY,
                label=to_label,
                properties={"confidence": confidence},
                source_ref={
                    "kind": "kb",
                    "knowledge_id": knowledge_id,
                    "chunk_ids": [chunk_id],
                },
            )
            anchor_label_to_id[to_norm] = to_id
            # SQL 과 짝맞춰 AGE 에도 노드 등록 (위 attributes 분기와 동일 이유).
            if _prov_age is not None:
                age_upsert_node(
                    _prov_age,
                    NodeType.DOC_ENTITY,
                    to_id,
                    to_label,
                    {"confidence": confidence},
                    kg_id=kg_id,
                )

        if _prov_target_nid == to_id:
            continue

        # cross-ref 도 src 를 document 로 변경 (topology 일관성)
        xref_props = {
            "relation_label": rtype_raw,
            "primary_term_id": from_id,
            "from_chunk": chunk_id,
        }
        edge = KnowledgeGraphs.upsert_edge(
            kg_id=kg_id,
            user_id=user_id,
            src_id=_prov_target_nid,
            dst_id=to_id,
            edge_type=rtype,
            source=EdgeSource.LLM_EXTRACT,
            weight=confidence,
            properties=xref_props,
        )
        if edge:
            xrefs_applied += 1
            # AGE 에도 동일 엣지 — dst 는 anchor 매칭 시 doc_entity 가 아닐 수 있어
            # 실제 노드 type 을 조회해 정확한 라벨로 작성 (kb_sync.py:1383 동일 패턴).
            if _prov_age is not None:
                to_node = KnowledgeGraphs.get_node_by_id(to_id)
                to_type = to_node.node_type if to_node else NodeType.DOC_ENTITY
                age_upsert_edge(
                    _prov_age,
                    rtype,
                    NodeType.DOCUMENT,
                    _prov_target_nid,
                    to_type,
                    to_id,
                    source=EdgeSource.LLM_EXTRACT,
                    properties={**xref_props, "weight": confidence},
                    kg_id=kg_id,
                )

    return {
        "attributes_applied": attrs_applied,
        "cross_refs_applied": xrefs_applied,
        "dropped_unknown_slot": dropped_unknown_slot,
        "dropped_scope_mismatch": dropped_scope_mismatch,
        "new_edge_types": list(edge_labels_used.keys()),
    }


async def process_kb_chunk_task(app, task_id: str, payload: Dict[str, Any]) -> None:
    """단일 KB 청크에 대해 Stage B schematized 추출 → KG upsert → progress 갱신.

    앵커(file_anchors) 가 없으면 LLM 호출 자체를 skip (도메인 외 청크).
    실패 시 예외를 raise 해서 컨슈머 retry 로직에 위임.
    """
    kg_id: str = payload["kg_id"]
    knowledge_id: str = payload["knowledge_id"]
    user_id: str = payload["user_id"]
    chunk_id: str = payload["chunk_id"]
    chunk_content: str = payload["chunk_content"]
    file_anchors: list = payload.get("file_anchors") or []
    edge_types: Dict[str, dict] = payload.get("edge_types") or {}
    edge_types_locked: bool = bool(payload.get("edge_types_locked"))
    llm_config: dict = payload["llm_config"]
    min_confidence: float = float(payload.get("min_confidence", 0.6))
    kg_name: Optional[str] = payload.get("kg_name")
    kg_description: Optional[str] = payload.get("kg_description")
    job_id: Optional[str] = payload.get("job_id")
    provenance_node_id: Optional[str] = payload.get("provenance_node_id")

    # ─── Cancel 감지 ───
    if job_id and KnowledgeGraphs.is_job_cancelled(job_id):
        log.info(
            f"[kb_chunk_worker] chunk={chunk_id[:8]} skipped — job {job_id} cancelled"
        )
        KnowledgeGraphs.increment_job_progress(job_id, delta=1, failure_delta=1)
        _maybe_finalize(app, job_id, kg_id, knowledge_id)
        return

    # ─── 가드: 내용이 너무 짧거나 앵커가 없으면 LLM skip ───
    if not chunk_content or len(chunk_content) < 50:
        # 의미 있는 내용 없음 → success로 간주. processed_chunks 에는 저장해둬야
        # 다음 incremental sync 가 이 빈 청크를 또 LLM 에 보내지 않는다.
        _record_processed_chunk(kg_id, knowledge_id, chunk_id, llm_config)
        if job_id:
            KnowledgeGraphs.increment_job_progress(job_id, delta=1, success_delta=1)
            _maybe_finalize(app, job_id, kg_id, knowledge_id)
        return

    if not file_anchors:
        # 이 파일에 확정된 앵커가 없음 → 도메인 외 문서로 간주. LLM 호출 스킵.
        # 이것도 processed_chunks 에 기록해야 다음 sync 에서 재시도 안 함.
        log.debug(
            f"[kb_chunk_worker] chunk={chunk_id[:8]} skipped — no anchors for file"
        )
        _record_processed_chunk(kg_id, knowledge_id, chunk_id, llm_config)
        if job_id:
            KnowledgeGraphs.increment_job_progress(job_id, delta=1, success_delta=1)
            _maybe_finalize(app, job_id, kg_id, knowledge_id)
        return

    # ─── LLM 호출 (schematized) ───
    llm = create_llm(llm_config, streaming=False, model_kwargs={"temperature": 0.0})
    system_prompt = _STAGE_B_SYSTEM_PROMPT.format(
        kg_name=kg_name or "(unnamed)",
        kg_description=kg_description or "(no description)",
        anchors_block=_format_anchors_block(file_anchors),
        edge_types_block=_format_edge_types_block(edge_types, locked=edge_types_locked),
    )
    user_prompt = f"Source chunk id: {chunk_id}\n\nText:\n{chunk_content}\n"

    # Hard timeout — Stage B 단일 청크 추출이 5 분을 넘기면 hung 상태로 간주하고
    # 해당 청크 task 만 실패로 처리 (worker slot 해제, 다음 청크 계속 진행).
    import asyncio as _asyncio

    response = await _asyncio.wait_for(
        llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        ),
        timeout=300.0,
    )
    raw_content = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw_content, list):
        parts: list[str] = []
        for blk in raw_content:
            if isinstance(blk, dict):
                t = blk.get("text") or blk.get("content")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(blk, str):
                parts.append(blk)
        content_resp = "".join(parts)
    else:
        content_resp = raw_content if isinstance(raw_content, str) else str(raw_content)

    parsed = _extract_json(content_resp)
    if not parsed:
        raise ValueError(
            f"Invalid JSON from LLM for chunk {chunk_id[:20]}: {content_resp[:120]}"
        )

    # ─── KG 에 적용 ───
    anchor_id_set: set[str] = set()
    anchor_label_to_id: Dict[str, str] = {}
    anchor_category_by_id: Dict[str, str] = {}
    for a in file_anchors:
        node_id = a.get("node_id") or a.get("entity_node_id")
        label = a.get("label") or a.get("entity_label")
        cat = a.get("category")
        if node_id:
            anchor_id_set.add(node_id)
            if cat:
                anchor_category_by_id[node_id] = cat
        if node_id and label:
            anchor_label_to_id[_normalize_entity_label(label)] = node_id

    allowed_set: Optional[set[str]] = (
        set(edge_types.keys()) if edge_types_locked else None
    )
    stats = _apply_schematized_extraction(
        kg_id=kg_id,
        knowledge_id=knowledge_id,
        user_id=user_id,
        chunk_id=chunk_id,
        parsed=parsed,
        anchor_id_set=anchor_id_set,
        anchor_label_to_id=anchor_label_to_id,
        min_confidence=min_confidence,
        allowed_edge_types=allowed_set,
        edge_type_catalog=edge_types,
        anchor_category_by_id=anchor_category_by_id,
        provenance_node_id=provenance_node_id,
    )

    # ─── 엣지 타입 레지스트리 upsert (이번 청크에서 처음 본 것) ───
    for new_type in stats.get("new_edge_types") or []:
        if new_type not in edge_types:
            try:
                KnowledgeGraphs.register_edge_type(
                    kg_id=kg_id,
                    name=new_type,
                    description=None,
                )
            except Exception as e:
                log.warning(
                    f"[kb_chunk_worker] register_edge_type({new_type}) failed: {e}"
                )

    log.info(
        f"[kb_chunk_worker] chunk={chunk_id[:8]} done: "
        f"+{stats['attributes_applied']} attrs, "
        f"+{stats['cross_refs_applied']} xrefs, "
        f"types={stats.get('new_edge_types') or []}"
    )

    # 성공한 청크만 processed_chunks 에 원자적 append. finalize 의 chunks_per_kb
    # 통째로 저장 방식은 실패 청크까지 박제되는 버그가 있어서 per-worker append
    # 로 변경.
    _record_processed_chunk(kg_id, knowledge_id, chunk_id, llm_config)

    if job_id:
        KnowledgeGraphs.increment_job_progress(job_id, delta=1, success_delta=1)
        _maybe_finalize(app, job_id, kg_id, knowledge_id)


async def handle_chunk_permanent_failure(
    app, task_id: str, payload: Dict[str, Any], error: str
) -> None:
    """3회 재시도 실패 → 청크는 영구 실패로 마킹. 카운터는 그래도 증가
    (안 그러면 job이 영원히 finalize 안 됨)."""
    job_id = payload.get("job_id")
    if job_id:
        KnowledgeGraphs.increment_job_progress(job_id, delta=1, failure_delta=1)
        _maybe_finalize(app, job_id, payload.get("kg_id"), payload.get("knowledge_id"))
    log.error(
        f"[kb_chunk_worker] chunk {payload.get('chunk_id', '?')[:8]} "
        f"permanently failed after retries: {error}"
    )


# 백그라운드 reindex task 핸들을 garbage collection 으로부터 보호하기 위한 strong-ref set
_BG_REINDEX_TASKS: set = set()


def _maybe_finalize(
    app, job_id: str, kg_id: Optional[str], knowledge_id: Optional[str]
) -> None:
    """카운터 증가 후 try_claim — 마지막 워커만 True를 받아 finalize 실행.

    주의: processed_chunks 는 각 성공 워커가 직접 append 하므로 finalize 에서는
    건드리지 않는다. 여기서는 KG stats 갱신과 재인덱싱, 소켓 알림만 담당.
    """
    claimed = KnowledgeGraphs.try_claim_job_finalization(job_id)
    if not claimed:
        return

    log.info(f"[kb_chunk_worker] finalizing job {job_id}")

    params = (claimed.params or {}) if claimed else {}
    if not kg_id:
        kg_id = params.get("kg_id")

    if kg_id:
        # KG stats 갱신 (node/edge count + last_synced_at)
        try:
            from extension_modules.knowledge_graph import KGService

            svc = KGService.load(kg_id)
            if svc:
                svc.refresh_stats()
        except Exception as e:
            log.exception(f"[kb_chunk_worker] stats refresh failed: {e}")

    # 3. 재인덱싱 (semantic search 가용 시)
    # app=None (테스트/스텁 컨텍스트)이거나 search engine 미설정이면 graceful skip.
    if app is None:
        log.info("[kb_chunk_worker] skip reindex: app=None (test/stub context)")
    elif kg_id:
        try:
            from extension_modules.knowledge_graph import KGNodeIndexService

            nodes = KnowledgeGraphs.get_nodes(kg_id, node_type="doc_entity", limit=2000)
            if nodes:
                import asyncio

                index_service = KGNodeIndexService(app)
                # GC 방지: 백그라운드 태스크 핸들을 모듈 전역에 유지
                task = asyncio.create_task(index_service.index_nodes(kg_id, nodes))
                _BG_REINDEX_TASKS.add(task)
                task.add_done_callback(_BG_REINDEX_TASKS.discard)
        except Exception as e:
            log.exception(f"[kb_chunk_worker] reindex failed: {e}")

    # 4. Socket.IO 실시간 알림 — 사용자가 폴링 없이 즉시 갱신 확인 가능
    try:
        import asyncio

        from open_webui.socket.main import send_notification_to_user

        asyncio.ensure_future(
            send_notification_to_user(
                user_id=claimed.user_id,
                event_type="kg-job-completed",
                data={
                    "job_id": job_id,
                    "kg_id": kg_id,
                    "kind": claimed.kind,
                    "status": claimed.status,
                    "stats": claimed.stats,
                },
            )
        )
    except Exception as e:
        log.warning(f"[kb_chunk_worker] socket notification failed (non-fatal): {e}")

    log.info(f"[kb_chunk_worker] job {job_id} finalized: stats={claimed.stats}")
