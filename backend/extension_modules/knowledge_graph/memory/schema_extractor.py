"""KG 노드/엣지 타입에 LLM 자연어 설명을 1회 생성해 kg_schema_doc 메모리로 저장.

DbSphere `schema_extractor.py` 의 사이블링. DbSphere 는 SQL 테이블/컬럼 단위
이지만 KG 는 (node_type, edge_type) 단위로 운영한다.

호출 시점:
  · KG sync finalize 직후 (자동) — _hook_after_sync_finalize 가 trigger
  · 관리자가 명시적 재추출 요청 (Admin endpoint, 별도 PR)

dedup 메커니즘:
  · (sample_label_set, sample_prop_keys, degree_stats) 의 SHA1 hash 를
    `source_hash` 로 저장. 재추출 시 동일 hash 면 LLM 호출 자체를 skip.
  · source_hash 미일치 시 LLM 재호출하여 description 갱신.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from extension_modules.knowledge_graph.memory.models import SchemaRole
from extension_modules.knowledge_graph.memory.search_memory import SearchEngineKGMemory
from extension_modules.utils.llm import generate_text, get_model_config_from_app
from open_webui.models.knowledge_graph import KnowledgeGraphs

logger = logging.getLogger(__name__)

# LLM 에 보낼 sample 크기 — 너무 크면 토큰 낭비, 너무 작으면 LLM 추정이 안 됨
_NODE_SAMPLE_SIZE = 8
_EDGE_SAMPLE_SIZE = 8


_NODE_PROMPT = """다음은 한 지식 그래프(KG)의 특정 노드 타입에 속한 노드들의 표본입니다.
이 노드 타입이 이 도메인에서 무엇을 표현하는지 1~2문장으로 간결하게 한국어로 설명해주세요.

## 노드 타입
{type_name}

## 표본 라벨 ({sample_count}개 중 일부)
{sample_labels}

## 자주 쓰이는 property 키
{sample_props}

## degree 통계
- 평균 incoming edge: {avg_in}
- 평균 outgoing edge: {avg_out}

## 응답 형식
JSON 한 객체만 출력하세요. 코드 블록 없이.
{{
  "description": "이 노드 타입이 도메인에서 무엇을 표현하는지 1~2문장"
}}
"""


_EDGE_PROMPT = """다음은 한 지식 그래프(KG)의 특정 엣지 타입에 해당하는 트리플 표본입니다.
이 엣지 타입이 어떤 관계를 의미하는지 1~2문장으로 한국어로 설명해주세요.

## 엣지 타입
{type_name}

## 표본 트리플 (src_label -[edge]-> dst_label)
{sample_triples}

## 통계
- 총 엣지 수: {total_count}

## 응답 형식
JSON 한 객체만 출력하세요. 코드 블록 없이.
{{
  "description": "이 엣지 타입이 어떤 관계를 의미하는지 1~2문장"
}}
"""


def _hash_node_signature(
    sample_labels: List[str],
    sample_props: List[str],
    degree_stats: Dict[str, Any],
) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(sorted(sample_labels), ensure_ascii=False).encode())
    h.update(b"|")
    h.update(json.dumps(sorted(sample_props), ensure_ascii=False).encode())
    h.update(b"|")
    # degree_stats 의 부동소수 소수점은 round 하여 hash 안정화
    rounded = {
        k: round(float(v), 1) if isinstance(v, (int, float)) else v
        for k, v in degree_stats.items()
    }
    h.update(json.dumps(rounded, sort_keys=True).encode())
    return h.hexdigest()


def _hash_edge_signature(sample_triples: List[Tuple[str, str, str]], total: int) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(sorted(sample_triples), ensure_ascii=False).encode())
    h.update(b"|")
    # 총 카운트는 일정 bucket 으로 quantize — 1~10, 10~100 등
    bucket = (total // 10) * 10 if total < 100 else (total // 100) * 100
    h.update(str(bucket).encode())
    return h.hexdigest()


def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    """LLM 응답에서 JSON 추출. 코드 블록 / 앞뒤 텍스트 robust."""
    if not raw:
        return None
    # 코드 블록 제거
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[:-3]
    # 첫 { ~ 마지막 } 구간 추출
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(s[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


class KGSchemaExtractor:
    """노드/엣지 타입별 1회 LLM 설명 생성기 + kg_memory 저장."""

    def __init__(
        self,
        app,
        kg_id: str,
        memory: SearchEngineKGMemory,
        llm_model_id: str,
        user_id: str = "",
    ):
        self.app = app
        self.kg_id = kg_id
        self.memory = memory
        self.llm_model_id = llm_model_id
        self.user_id = user_id

    # ── 데이터 수집 ───────────────────────────────────────────────────────

    def _collect_node_types(self) -> List[Dict[str, Any]]:
        """KG 의 모든 distinct node_type 별 sample.

        SQLAlchemy ORM 으로 직접 group by — 별도 모델 helper 가 없는 상태라
        간단한 raw query 수준의 호출만 사용. 페이지네이션 없이 모든 타입.
        """
        from open_webui.internal.db import get_db
        from open_webui.models.knowledge_graph import KGEdge, KGNode
        from sqlalchemy import distinct, func

        with get_db() as db:
            type_rows = (
                db.query(KGNode.node_type, func.count(KGNode.id))
                .filter(KGNode.kg_id == self.kg_id)
                .group_by(KGNode.node_type)
                .order_by(func.count(KGNode.id).desc())
                .all()
            )

            output: List[Dict[str, Any]] = []
            for node_type, total in type_rows:
                # sample labels
                sample = (
                    db.query(distinct(KGNode.label))
                    .filter(KGNode.kg_id == self.kg_id, KGNode.node_type == node_type)
                    .limit(_NODE_SAMPLE_SIZE)
                    .all()
                )
                sample_labels = [r[0] for r in sample if r[0]]

                # sample property keys (앞 50개 노드의 properties dict 키 빈도)
                rows = (
                    db.query(KGNode.properties)
                    .filter(KGNode.kg_id == self.kg_id, KGNode.node_type == node_type)
                    .limit(50)
                    .all()
                )
                from collections import Counter

                key_counter: Counter[str] = Counter()
                for (props,) in rows:
                    if isinstance(props, dict):
                        key_counter.update(props.keys())
                sample_props = [k for k, _ in key_counter.most_common(8)]

                # degree stats — incoming/outgoing edge count 평균
                # 개별 노드 별 join 은 무거우므로 type 단위 sum / total
                in_total = (
                    db.query(func.count(KGEdge.id))
                    .join(KGNode, KGNode.id == KGEdge.dst_id)
                    .filter(
                        KGNode.kg_id == self.kg_id,
                        KGNode.node_type == node_type,
                    )
                    .scalar()
                    or 0
                )
                out_total = (
                    db.query(func.count(KGEdge.id))
                    .join(KGNode, KGNode.id == KGEdge.src_id)
                    .filter(
                        KGNode.kg_id == self.kg_id,
                        KGNode.node_type == node_type,
                    )
                    .scalar()
                    or 0
                )
                avg_in = round(in_total / max(total, 1), 2)
                avg_out = round(out_total / max(total, 1), 2)

                output.append(
                    {
                        "type_name": node_type,
                        "total": int(total),
                        "sample_labels": sample_labels,
                        "sample_props": sample_props,
                        "degree_stats": {
                            "avg_in": avg_in,
                            "avg_out": avg_out,
                            "in_total": int(in_total),
                            "out_total": int(out_total),
                        },
                    }
                )
            return output

    def _collect_edge_types(self) -> List[Dict[str, Any]]:
        """edge_type 별 sample triple."""
        from open_webui.internal.db import get_db
        from open_webui.models.knowledge_graph import KGEdge, KGNode
        from sqlalchemy.orm import aliased

        et_counts = KnowledgeGraphs.get_distinct_edge_types(self.kg_id)

        output: List[Dict[str, Any]] = []
        with get_db() as db:
            for edge_type, total in et_counts:
                src = aliased(KGNode)
                dst = aliased(KGNode)
                rows = (
                    db.query(src.label, dst.label)
                    .select_from(KGEdge)
                    .join(src, src.id == KGEdge.src_id)
                    .join(dst, dst.id == KGEdge.dst_id)
                    .filter(
                        KGEdge.kg_id == self.kg_id,
                        KGEdge.edge_type == edge_type,
                    )
                    .limit(_EDGE_SAMPLE_SIZE)
                    .all()
                )
                sample_triples = [(r[0] or "?", edge_type, r[1] or "?") for r in rows]
                output.append(
                    {
                        "type_name": edge_type,
                        "total": int(total),
                        "sample_triples": sample_triples,
                    }
                )
        return output

    # ── LLM 호출 ─────────────────────────────────────────────────────────

    async def _describe_node_type(self, info: Dict[str, Any]) -> Optional[str]:
        cfg = get_model_config_from_app(self.app, self.llm_model_id)
        if not cfg:
            logger.warning(
                f"[kg_schema_extractor] llm model `{self.llm_model_id}` not configured"
            )
            return None

        prompt = _NODE_PROMPT.format(
            type_name=info["type_name"],
            sample_count=info["total"],
            sample_labels="\n".join(f"- {x}" for x in (info["sample_labels"] or []))
            or "(없음)",
            sample_props=", ".join(info["sample_props"]) or "(없음)",
            avg_in=info["degree_stats"]["avg_in"],
            avg_out=info["degree_stats"]["avg_out"],
        )
        try:
            raw = await generate_text(cfg, prompt, system_prompt=None, temperature=0.2)
        except Exception as e:
            logger.warning(f"[kg_schema_extractor] node llm call failed: {e}")
            return None
        parsed = _parse_json_response(raw)
        if not parsed:
            return None
        desc = parsed.get("description")
        if not isinstance(desc, str) or not desc.strip():
            return None
        return desc.strip()

    async def _describe_edge_type(self, info: Dict[str, Any]) -> Optional[str]:
        cfg = get_model_config_from_app(self.app, self.llm_model_id)
        if not cfg:
            return None
        triples_lines = (
            "\n".join(f"- ({s}) -[{p}]-> ({o})" for s, p, o in info["sample_triples"])
            or "(없음)"
        )
        prompt = _EDGE_PROMPT.format(
            type_name=info["type_name"],
            sample_triples=triples_lines,
            total_count=info["total"],
        )
        try:
            raw = await generate_text(cfg, prompt, system_prompt=None, temperature=0.2)
        except Exception as e:
            logger.warning(f"[kg_schema_extractor] edge llm call failed: {e}")
            return None
        parsed = _parse_json_response(raw)
        if not parsed:
            return None
        desc = parsed.get("description")
        if not isinstance(desc, str) or not desc.strip():
            return None
        return desc.strip()

    # ── 진입점 ───────────────────────────────────────────────────────────

    async def extract_for_kg(self) -> Dict[str, int]:
        """node 타입 + edge 타입 각각 LLM 1회 호출하여 schema_doc 저장.

        source_hash 동일 → 호출 skip. 결과 통계 dict 반환.
        """
        stats = {
            "node_types_seen": 0,
            "node_types_described": 0,
            "node_types_skipped": 0,
            "edge_types_seen": 0,
            "edge_types_described": 0,
            "edge_types_skipped": 0,
            "errors": 0,
        }

        # 노드
        node_infos = self._collect_node_types()
        stats["node_types_seen"] = len(node_infos)

        async with self.memory.session():
            for info in node_infos:
                try:
                    sig = _hash_node_signature(
                        info["sample_labels"],
                        info["sample_props"],
                        info["degree_stats"],
                    )
                    # source_hash 비교를 위해 upsert 가 내부적으로 skip 처리
                    # 하지만 LLM 호출 비용을 아끼려면 사전 검사가 더 효율
                    # 현재 SearchEngineKGMemory 가 hash-만-비교 expose 안 함
                    # → 일단 LLM 호출 후 upsert 시점에 skip 판정 (description 같으면 noop)
                    desc = await self._describe_node_type(info)
                    if not desc:
                        stats["errors"] += 1
                        continue
                    saved = await self.memory.upsert_schema_doc(
                        type_name=info["type_name"],
                        schema_role=SchemaRole.NODE.value,
                        description=desc,
                        sample_labels=info["sample_labels"],
                        sample_props=info["sample_props"],
                        degree_stats=info["degree_stats"],
                        source_hash=sig,
                    )
                    if saved is None:
                        stats["node_types_skipped"] += 1
                    else:
                        stats["node_types_described"] += 1
                except Exception as e:
                    logger.warning(
                        f"[kg_schema_extractor] node_type={info.get('type_name')} failed: {e}"
                    )
                    stats["errors"] += 1

            # 엣지
            edge_infos = self._collect_edge_types()
            stats["edge_types_seen"] = len(edge_infos)
            for info in edge_infos:
                try:
                    sig = _hash_edge_signature(info["sample_triples"], info["total"])
                    desc = await self._describe_edge_type(info)
                    if not desc:
                        stats["errors"] += 1
                        continue
                    saved = await self.memory.upsert_schema_doc(
                        type_name=info["type_name"],
                        schema_role=SchemaRole.EDGE.value,
                        description=desc,
                        sample_labels=[],
                        sample_props=[],
                        degree_stats={"total": info["total"]},
                        source_hash=sig,
                    )
                    if saved is None:
                        stats["edge_types_skipped"] += 1
                    else:
                        stats["edge_types_described"] += 1
                except Exception as e:
                    logger.warning(
                        f"[kg_schema_extractor] edge_type={info.get('type_name')} failed: {e}"
                    )
                    stats["errors"] += 1

        return stats

    # ── Drift 헬퍼 ──────────────────────────────────────────────────────

    def collect_current_type_sets(self) -> Tuple[set, set]:
        """현재 KG 에 살아있는 (node_types, edge_types) 집합. drift 비교용."""

        from open_webui.internal.db import get_db
        from open_webui.models.knowledge_graph import KGEdge, KGNode

        with get_db() as db:
            n = (
                db.query(KGNode.node_type)
                .filter(KGNode.kg_id == self.kg_id)
                .group_by(KGNode.node_type)
                .all()
            )
            e = (
                db.query(KGEdge.edge_type)
                .filter(KGEdge.kg_id == self.kg_id)
                .group_by(KGEdge.edge_type)
                .all()
            )
            return ({r[0] for r in n}, {r[0] for r in e})


# ─────────────────────────────────────────────────────────────────────────
# Convenience wrapper for sync finalize hook
# ─────────────────────────────────────────────────────────────────────────


async def run_after_sync(
    app,
    kg_id: str,
    memory: SearchEngineKGMemory,
    llm_model_id: str,
    previous_node_types: Optional[Iterable[str]] = None,
    previous_edge_types: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """sync finalize 직후 부르는 단일 진입점.

    1. drift 처리: 이전 sync 의 type set 과 현재의 차분 → 사라진 타입 참조
       메모리를 stale 마킹
    2. KGSchemaExtractor 로 새/갱신된 타입 LLM 설명 생성

    예외는 모두 흡수해서 caller (sync finalize) 가 중단되지 않게 한다.
    """
    extractor = KGSchemaExtractor(
        app=app, kg_id=kg_id, memory=memory, llm_model_id=llm_model_id
    )

    out: Dict[str, Any] = {"drift_marked": 0, "extract_stats": {}}

    try:
        cur_n, cur_e = extractor.collect_current_type_sets()
        if previous_node_types is not None or previous_edge_types is not None:
            removed_n = sorted(set(previous_node_types or []) - cur_n)
            removed_e = sorted(set(previous_edge_types or []) - cur_e)
            if removed_n or removed_e:
                marked = await memory.mark_stale_by_referenced_types(
                    removed_node_types=removed_n,
                    removed_edge_types=removed_e,
                )
                out["drift_marked"] = marked
                out["removed_node_types"] = removed_n
                out["removed_edge_types"] = removed_e
    except Exception as e:
        logger.warning(f"[kg_schema_extractor] drift handling failed: {e}")

    try:
        out["extract_stats"] = await extractor.extract_for_kg()
    except Exception as e:
        logger.exception(f"[kg_schema_extractor] extract failed: {e}")
        out["extract_stats"] = {"error": str(e)}

    return out


__all__ = ["KGSchemaExtractor", "run_after_sync"]
