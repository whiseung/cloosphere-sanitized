"""Phase 4 — DB 기반 cross-category 엣지 파생.

링크 카탈로그에 정의된 cross-category 엣지 타입(`src_category` ≠ `dst_category`)
에 대해, LLM이 DDL + DOC 메모리를 보고 join SQL을 생성하고, 그 SQL을 dbsphere
SQL runner로 실행해서 term ↔ term 엣지를 파생한다.

흐름:
  1) plan_db_derivations — LLM 콜 N개 (cross edge type 수만큼)
  2) cleanup_previous_derivation_edges — 재실행 시 이전 결과 제거
  3) execute_db_derivation — 각 plan별 SQL 실행 + term lookup + edge upsert

Phase 3 (`kb_extract`) 이후 `_finalize_parent` 가 chain으로 호출한다.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Callable, Optional

from extension_modules.utils.llm import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.dbsphere import DbSpheres
from open_webui.models.glossary import Glossaries
from open_webui.models.knowledge_graph import (
    EdgeSource,
    KGEdge,
    KGNode,
    KnowledgeGraphs,
    NodeType,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


_PAGE_SIZE = 5000
# 안전장치: plan 하나가 이 행수를 넘기면 abort (정상 use case 는 안 닿음)
_HARD_CAP_ROWS_PER_PLAN = 10_000_000


# ─── JSON helpers ─────────────────────────────────────────────────
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
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _is_select_only(sql: str) -> bool:
    """SELECT 로 시작하는 쿼리만 허용 (mutation 차단)."""
    if not sql:
        return False
    stripped = sql.strip().rstrip(";")
    # 괄호로 감싸진 CTE 허용
    while stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    # 첫 단어가 SELECT 또는 WITH 여야
    first = stripped.upper().split(None, 1)[0] if stripped else ""
    return first in ("SELECT", "WITH")


# ─── Plan generation (LLM) ────────────────────────────────────────
_PLAN_SYSTEM_PROMPT = """당신은 데이터베이스 스키마를 읽고 두 카테고리의 엔티티를 잇는
JOIN SQL 을 작성하는 전문가입니다.

## 입력
- 엣지 타입 정보 (key, display_name, description): 어떤 관계를 만드는지 의미 파악.
- 두 카테고리가 각각 매핑된 (테이블, 컬럼) 쌍. 컬럼은 보통 name 성격(PK 아님).
- 두 테이블 및 junction 테이블들의 DDL (PK/FK 정보 포함).
- 관련된 문서 메모리 (테이블 간 관계 서술).

## 임무
엣지 타입의 설명(description)을 참고해서, src_category 의 name 값과 dst_category 의
name 값을 행 단위로 잇는 SELECT SQL 을 작성하세요. description 에 "A는 B의 유효성분
을 함유한다" 같은 특정 조건이 있으면 그에 맞는 WHERE 절을 추가하세요 (예: 유효성분
플래그 컬럼 필터).

## 규칙
1. **반드시 SELECT** 만. UPDATE/INSERT/DELETE/DDL 절대 금지.
2. SELECT 결과는 정확히 두 컬럼: `src` (src_category 의 name 값), `dst` (dst_category
   의 name 값). 별칭을 반드시 `src`, `dst` 로 붙이세요.
3. junction 테이블이 있으면 그것을 사용해서 INNER JOIN. junction 이 없고 FK 가
   직접 걸려 있으면 두 테이블만 JOIN.
4. WHERE 절에 `src` 와 `dst` 가 NULL/공백이 아닌 조건 포함.
5. **방향**: src_category 와 dst_category 순서 그대로 유지. 카탈로그 항목이 이미
   부모→자식/전체→부분 방향으로 정해져 있으므로 SELECT 결과의 src/dst 매핑을
   뒤집지 마세요.
6. ORDER BY 나 LIMIT 는 넣지 마세요 (호출자가 페이지네이션을 wrap 합니다).
7. JOIN 을 찾을 수 없으면 `sql` 에 빈 문자열, `reason` 에 이유 기술.

## 출력 (JSON 만, 마크다운 금지)
{{
  "sql": "SELECT ... AS src, ... AS dst FROM ... WHERE ...",
  "reason": "어떤 junction 또는 FK 를 사용했는지, WHERE 필터 근거 포함 1~2 문장"
}}
"""


def _render_plan_context(
    edge_type: str,
    display_name: str,
    description: str,
    src_category: str,
    src_table: str,
    src_column: str,
    dst_category: str,
    dst_table: str,
    dst_column: str,
    ddl_memories: list,
    doc_hints: list,
) -> str:
    """plan 생성 LLM 에 보낼 user prompt 구성."""
    lines: list[str] = []
    lines.append("## 엣지 타입")
    lines.append(f"- key: `{edge_type}`")
    if display_name:
        lines.append(f"- 이름: {display_name}")
    if description:
        lines.append(f"- 설명: {description}")

    lines.append("\n## 매핑")
    lines.append(
        f"- src_category='{src_category}' → table=`{src_table}`, column=`{src_column}`"
    )
    lines.append(
        f"- dst_category='{dst_category}' → table=`{dst_table}`, column=`{dst_column}`"
    )

    lines.append("\n## 관련 테이블 DDL")
    for ddl in ddl_memories:
        table = getattr(ddl, "table_name", "") or ""
        if not table:
            continue
        lines.append(f"\n### {table}")
        desc = getattr(ddl, "table_description", None)
        if desc:
            lines.append(f"- 설명: {desc}")
        cols = getattr(ddl, "columns", None) or []
        if cols:
            lines.append("- 컬럼:")
            for c in cols:
                name = getattr(c, "name", "")
                dtype = getattr(c, "data_type", "")
                pk = " [PK]" if getattr(c, "is_primary_key", False) else ""
                fk_ref = ""
                if getattr(c, "is_foreign_key", False):
                    ft = getattr(c, "foreign_table", None)
                    fc = getattr(c, "foreign_column", None)
                    if ft and fc:
                        fk_ref = f" [FK → {ft}.{fc}]"
                    else:
                        fk_ref = " [FK]"
                cdesc = getattr(c, "description", None) or ""
                suffix = f" — {cdesc}" if cdesc else ""
                lines.append(f"  - {name} ({dtype}){pk}{fk_ref}{suffix}")

    if doc_hints:
        lines.append("\n## 관련 문서 힌트")
        for h in doc_hints:
            title = h.get("title") or ""
            content = h.get("content") or ""
            if title:
                lines.append(f"- [{title}] {content[:300]}")
            else:
                lines.append(f"- {content[:300]}")

    return "\n".join(lines)


async def plan_db_derivations(
    app,
    kg_id: str,
    link_id: str,
    pre_resolved_model_config: dict,
) -> list[dict]:
    """링크의 cross-category 엣지 타입별로 LLM 이 join plan 을 생성.

    반환: ``[{edge_type, src_category, dst_category, src_dbsphere_id, sql, reason}]``
    SQL 이 비어있거나 SELECT 가 아닌 plan 은 제외.
    """
    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not link or link.kg_id != kg_id:
        return []

    glossary = None
    if link.glossary_id:
        glossary = Glossaries.get_glossary_by_id(link.glossary_id)
    if not glossary:
        return []

    extraction_sources = (glossary.meta or {}).get("extraction_sources") or {}
    if not extraction_sources:
        log.info(
            f"[db_derivation] glossary {link.glossary_id[:8]} has no extraction_sources"
        )
        return []

    catalog = (link.config or {}).get("edge_types") or {}
    if not catalog:
        return []

    # cross-category 후보 추출
    cross_items: list[tuple[str, dict]] = []
    for key, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        src_cat = entry.get("src_category")
        dst_cat = entry.get("dst_category")
        if not src_cat or not dst_cat or src_cat == dst_cat:
            continue
        # dst="doc_entity" 는 LLM 속성 엣지 (Phase 4 전용), cross-category 아님.
        if dst_cat == "doc_entity":
            continue
        cross_items.append((key, entry))

    if not cross_items:
        log.info(f"[db_derivation] no cross-category entries in link {link_id[:8]}")
        return []

    llm = create_llm(
        pre_resolved_model_config, streaming=False, model_kwargs={"temperature": 0.1}
    )

    plans: list[dict] = []
    for key, entry in cross_items:
        src_cat = entry["src_category"]
        dst_cat = entry["dst_category"]
        src_info = extraction_sources.get(src_cat)
        dst_info = extraction_sources.get(dst_cat)
        if not isinstance(src_info, dict) or not isinstance(dst_info, dict):
            log.warning(
                f"[db_derivation] {key}: extraction_sources missing for "
                f"{src_cat} or {dst_cat}"
            )
            continue

        src_db = src_info.get("dbsphere_id")
        dst_db = dst_info.get("dbsphere_id")
        if not src_db or src_db != dst_db:
            log.warning(
                f"[db_derivation] {key}: cross-dbsphere not supported "
                f"(src={src_db}, dst={dst_db})"
            )
            continue

        src_table = src_info.get("table")
        src_column = src_info.get("column")
        dst_table = dst_info.get("table")
        dst_column = dst_info.get("column")
        if not (src_table and src_column and dst_table and dst_column):
            log.warning(f"[db_derivation] {key}: incomplete src/dst mapping")
            continue

        # DDL 메모리 로드 — src/dst 테이블 + 추가로 전체 (junction 후보용)
        try:
            from extension_modules.dbsphere.memory.search_memory import (
                SearchEngineDbSphereMemory,
            )

            memory = SearchEngineDbSphereMemory(
                app=app, dbsphere_id=src_db, user_id=link.user_id, embedding_func=None
            )
            all_ddls = await memory.get_table_schemas()
            relevant = [d for d in all_ddls if d.table_name in (src_table, dst_table)]
            # junction 후보: src_table 또는 dst_table 을 FK 로 참조하는 테이블
            for d in all_ddls:
                if d.table_name in (src_table, dst_table):
                    continue
                for col in d.columns or []:
                    if getattr(col, "is_foreign_key", False):
                        ft = getattr(col, "foreign_table", None)
                        if ft in (src_table, dst_table):
                            if d not in relevant:
                                relevant.append(d)
                            break
            # 관련 DDL 이 src/dst 만이면 junction 이 안 보인다는 뜻 — 상위 10개
            # 정도를 추가로 포함해 LLM 이 junction 을 힌트로 찾도록
            if len(relevant) <= 2 and len(all_ddls) > 2:
                for d in all_ddls[:10]:
                    if d not in relevant:
                        relevant.append(d)
        except Exception as e:
            log.warning(f"[db_derivation] DDL load failed for {src_db[:8]}: {e}")
            relevant = []

        # DOC 메모리 힌트 — 테이블 관계 관련 질의
        doc_hints: list[dict] = []
        try:
            query = f"relationship between {src_table} and {dst_table}"
            results = await memory.search_documentation(
                question=query, limit=5, similarity_threshold=0.0
            )
            for r in results:
                doc_hints.append(
                    {
                        "title": getattr(r, "title", None),
                        "content": getattr(r, "content", "") or "",
                    }
                )
        except Exception as e:
            log.warning(f"[db_derivation] DOC search failed: {e}")

        user_prompt = _render_plan_context(
            edge_type=key,
            display_name=entry.get("display_name") or key,
            description=entry.get("description") or "",
            src_category=src_cat,
            src_table=src_table,
            src_column=src_column,
            dst_category=dst_cat,
            dst_table=dst_table,
            dst_column=dst_column,
            ddl_memories=relevant,
            doc_hints=doc_hints,
        )

        log.info(
            f"[db_derivation] planning {key} ({src_cat}→{dst_cat}) "
            f"prompt_chars={len(user_prompt)}"
        )
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=_PLAN_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as e:
            log.exception(f"[db_derivation] LLM plan call failed for {key}: {e}")
            continue

        raw = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        parsed = _extract_json(raw)
        if not parsed:
            log.warning(f"[db_derivation] {key}: invalid JSON — {raw[:200]}")
            continue

        sql = (parsed.get("sql") or "").strip()
        reason = (parsed.get("reason") or "").strip()
        if not sql:
            log.info(f"[db_derivation] {key}: empty sql — {reason}")
            continue
        if not _is_select_only(sql):
            log.warning(f"[db_derivation] {key}: non-SELECT rejected — {sql[:200]}")
            continue

        plans.append(
            {
                "edge_type": key,
                "src_category": src_cat,
                "dst_category": dst_cat,
                "src_dbsphere_id": src_db,
                "src_table": src_table,
                "dst_table": dst_table,
                "sql": sql,
                "reason": reason or None,
            }
        )

    return plans


# ─── Cleanup ──────────────────────────────────────────────────────
def cleanup_previous_derivation_edges(kg_id: str, link_id: str) -> int:
    """재동기화 시 이 링크가 이전에 만든 db_derivation 엣지 제거.

    ``properties.link_id`` 가 일치하는 행만 지움. JSONB 연산자가 DB 별로 달라
    Postgres/SQLite 호환을 위해 row-level 로드 후 필터링.
    """
    try:
        with get_db() as db:
            rows = (
                db.query(KGEdge)
                .filter(KGEdge.kg_id == kg_id)
                .filter(KGEdge.source == EdgeSource.DB_DERIVATION)
                .all()
            )
            to_delete_ids: list[str] = []
            for e in rows:
                props = e.properties or {}
                if isinstance(props, dict) and props.get("link_id") == link_id:
                    to_delete_ids.append(e.id)
            if not to_delete_ids:
                return 0
            db.query(KGEdge).filter(KGEdge.id.in_(to_delete_ids)).delete(
                synchronize_session=False
            )
            db.commit()
            return len(to_delete_ids)
    except Exception as e:
        log.exception(f"[db_derivation] cleanup failed for link {link_id[:8]}: {e}")
        return 0


# ─── Term lookup cache ────────────────────────────────────────────
def _build_term_lookup(
    kg_id: str, glossary_id: str, categories: set[str]
) -> dict[tuple[str, str], str]:
    """지정 카테고리들의 term 노드를 메모리 dict 로 로드.

    반환: ``{(category, label_lower): node_id}``
    """
    out: dict[tuple[str, str], str] = {}
    try:
        with get_db() as db:
            rows = (
                db.query(KGNode)
                .filter(KGNode.kg_id == kg_id)
                .filter(KGNode.node_type == NodeType.TERM)
                .filter(KGNode.id.like(f"{kg_id}__glossary__{glossary_id}__%"))
                .all()
            )
            for n in rows:
                props = n.properties or {}
                cat = (
                    (props.get("category") or "").strip()
                    if isinstance(props, dict)
                    else ""
                )
                if cat not in categories:
                    continue
                label = (n.label or "").strip().lower()
                if not label:
                    continue
                key = (cat, label)
                if key not in out:
                    out[key] = n.id
    except Exception as e:
        log.exception(f"[db_derivation] build term lookup failed: {e}")
    return out


# ─── Execution ────────────────────────────────────────────────────
async def execute_db_derivation(
    app,
    kg_id: str,
    link_id: str,
    user_id: str,
    plan: dict,
    term_lookup: dict[tuple[str, str], str],
    progress_cb: Optional[Callable[[int], None]] = None,
) -> dict:
    """단일 plan 실행 → row → term lookup → edge upsert.

    반환: ``{edges_created, rows_scanned, unmatched_rows}``
    """
    from extension_modules.dbsphere.dbsphere_state import DBConfig
    from extension_modules.dbsphere.sql_runners import create_sql_runner
    from extension_modules.knowledge_graph.sync._age_helpers import (
        age_upsert_edge,
        get_age_service,
    )
    from open_webui.routers.dbsphere import decrypt_connection_password

    edge_type = plan["edge_type"]
    src_cat = plan["src_category"]
    dst_cat = plan["dst_category"]
    db_id = plan["src_dbsphere_id"]
    inner_sql = plan["sql"].rstrip(";")

    # DBConfig + SQL runner 구성
    dbsphere = DbSpheres.get_dbsphere_by_id(db_id)
    if not dbsphere:
        raise RuntimeError(f"DbSphere not found: {db_id}")
    data = decrypt_connection_password(copy.deepcopy(dbsphere.data or {}))
    db_config = DBConfig.from_dbsphere_data(data)
    runner = create_sql_runner(db_config)
    if runner is None:
        raise RuntimeError(f"No runner for dbsphere {db_id}")

    age = get_age_service(kg_id)

    edges_created = 0
    rows_scanned = 0
    unmatched_rows = 0
    offset = 0
    page_size = _PAGE_SIZE

    while True:
        if rows_scanned >= _HARD_CAP_ROWS_PER_PLAN:
            log.warning(
                f"[db_derivation] {edge_type}: hard cap {_HARD_CAP_ROWS_PER_PLAN} "
                f"reached, stopping"
            )
            break

        # 페이징 wrapping
        paged_sql = (
            f"SELECT src, dst FROM ({inner_sql}) _cd "
            f"ORDER BY src, dst OFFSET {offset} LIMIT {page_size}"
        )
        try:
            df = await runner.run_sql(paged_sql)
        except Exception as e:
            log.exception(
                f"[db_derivation] {edge_type}: page offset={offset} failed: {e}"
            )
            break

        if df is None or df.empty:
            break

        page_rows = len(df)
        rows_scanned += page_rows

        # row 처리
        for _, row in df.iterrows():
            src_raw = row.get("src")
            dst_raw = row.get("dst")
            if src_raw is None or dst_raw is None:
                unmatched_rows += 1
                continue
            src_label = str(src_raw).strip().lower()
            dst_label = str(dst_raw).strip().lower()
            if not src_label or not dst_label:
                unmatched_rows += 1
                continue
            src_id = term_lookup.get((src_cat, src_label))
            dst_id = term_lookup.get((dst_cat, dst_label))
            if not src_id or not dst_id or src_id == dst_id:
                unmatched_rows += 1
                continue

            edge = KnowledgeGraphs.upsert_edge(
                kg_id=kg_id,
                user_id=user_id,
                src_id=src_id,
                dst_id=dst_id,
                edge_type=edge_type,
                source=EdgeSource.DB_DERIVATION,
                properties={
                    "link_id": link_id,
                    "dbsphere_id": db_id,
                    "plan_reason": plan.get("reason"),
                },
            )
            if edge:
                edges_created += 1
                if age:
                    age_upsert_edge(
                        age,
                        edge_type,
                        NodeType.TERM,
                        src_id,
                        NodeType.TERM,
                        dst_id,
                        source=EdgeSource.DB_DERIVATION,
                        properties={"link_id": link_id},
                        kg_id=kg_id,
                    )

        if progress_cb:
            try:
                progress_cb(edges_created)
            except Exception:
                pass

        if page_rows < page_size:
            break
        offset += page_size

    return {
        "edges_created": edges_created,
        "rows_scanned": rows_scanned,
        "unmatched_rows": unmatched_rows,
    }


# ─── Top-level orchestrator ───────────────────────────────────────
async def run_db_derivation_for_link(
    app,
    kg_id: str,
    link_id: str,
    user_id: str,
    pre_resolved_model_config: dict,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Phase 4 부모 진입점 — plan/cleanup/execute 를 한 번에.

    반환: 통계 dict (plans_total, edges_created, rows_scanned, unmatched_rows, errors)
    """
    plans = await plan_db_derivations(app, kg_id, link_id, pre_resolved_model_config)
    stats: dict[str, Any] = {
        "plans_total": len(plans),
        "edges_created": 0,
        "rows_scanned": 0,
        "unmatched_rows": 0,
        "errors": [],
        "plans": [],
    }
    if not plans:
        return stats

    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    glossary_id = link.glossary_id if link else None
    if not glossary_id:
        stats["errors"].append("link has no glossary_id")
        return stats

    # cleanup 이전 db_derivation 엣지
    removed = cleanup_previous_derivation_edges(kg_id, link_id)
    stats["removed_existing"] = removed

    # 모든 plan 에 등장하는 카테고리 union 으로 term lookup 캐시 1회 구축
    all_cats: set[str] = set()
    for p in plans:
        all_cats.add(p["src_category"])
        all_cats.add(p["dst_category"])
    term_lookup = _build_term_lookup(kg_id, glossary_id, all_cats)
    log.info(
        f"[db_derivation] term lookup cache: {len(term_lookup)} entries "
        f"for {len(all_cats)} categories"
    )

    for idx, plan in enumerate(plans, start=1):
        try:
            p_stats = await execute_db_derivation(
                app, kg_id, link_id, user_id, plan, term_lookup
            )
            stats["edges_created"] += p_stats["edges_created"]
            stats["rows_scanned"] += p_stats["rows_scanned"]
            stats["unmatched_rows"] += p_stats["unmatched_rows"]
            stats["plans"].append(
                {
                    "edge_type": plan["edge_type"],
                    "src_category": plan["src_category"],
                    "dst_category": plan["dst_category"],
                    **p_stats,
                }
            )
            log.info(
                f"[db_derivation] [{idx}/{len(plans)}] {plan['edge_type']}: "
                f"rows={p_stats['rows_scanned']} edges={p_stats['edges_created']} "
                f"unmatched={p_stats['unmatched_rows']}"
            )
        except Exception as e:
            log.exception(f"[db_derivation] plan {plan.get('edge_type')} failed: {e}")
            stats["errors"].append(f"{plan.get('edge_type')}: {e}")

        if progress_cb:
            try:
                progress_cb(
                    {
                        "plan_idx": idx,
                        "plan_total": len(plans),
                        "edge_type": plan["edge_type"],
                        "edges_created": stats["edges_created"],
                    }
                )
            except Exception:
                pass

    return stats
