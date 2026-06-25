"""
LLM-based Schema Extractor for DbSphere V2.

Uses LLM to generate detailed descriptions for database tables,
including column meanings, data patterns, and relationships.

Also generates sample Q&A pairs during schema extraction for few-shot learning.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from extension_modules.dbsphere.memory.models import (
    ColumnDetail,
    DDLMemory,
    InferredJoin,
    TableDetails,
)
from extension_modules.dbsphere.memory.search_memory import DDL_SCHEMA_FETCH_LIMIT
from extension_modules.dbsphere.sql_runners.base import (
    SqlRunnerBase,
    validate_sql_identifier,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from open_webui.env import SRC_LOG_LEVELS

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MODELS"])


# ===========================================================================
# join_graph full-S recompute helpers (Option C) — pure, no I/O.
#
# The always-injected join_graph is a rendered VIEW over a normalized list of
# relationship rows. The row shape is forward-compatible with the future
# RelationshipMeta canonical model (same field names + relationship_type
# literals), so when that lands the builder input becomes a type swap, not a
# re-derivation. See dev-plans/dbsphere-relationship-graph-redesign §Δ.
# ===========================================================================

# relationship_type literals — align with the future RelationshipMeta tiers.
REL_VERIFIED_FK = "verified_fk"
REL_INFERRED_NAME = "inferred_name"


def reconstruct_table_details(
    ddl_memories: List[DDLMemory],
) -> List[TableDetails]:
    """Rebuild ``TableDetails`` from persisted ``DDLMemory`` (full-S reload).

    ``is_primary_key`` (and the rest of each ``ColumnDetail``) is preserved —
    the inference 4-gate reads it as its only structural signal. Rows with no
    table_name are skipped (defensive). Pure transform, no I/O.
    """
    details: List[TableDetails] = []
    for mem in ddl_memories:
        if not mem.table_name:
            continue
        details.append(
            TableDetails(
                table_name=mem.table_name,
                ddl=mem.ddl_statement or "",
                description=mem.table_description or "",
                columns=list(mem.columns or []),
                related_tables=list(mem.relationships or []),
            )
        )
    return details


def merge_batch_fresh(
    reloaded: List[TableDetails],
    batch: List[TableDetails],
) -> List[TableDetails]:
    """Full-S set = reloaded store ∪ batch, batch (fresh) winning on overlap.

    The batch was just extracted in-run, so its ``TableDetails`` are fresher than
    the store reload (which may predate this run for the batch tables). Keyed
    case-insensitively on table_name. Pure.
    """
    by_name: Dict[str, TableDetails] = {}
    for td in reloaded:
        by_name[td.table_name.lower()] = td
    for td in batch:
        by_name[td.table_name.lower()] = td
    return list(by_name.values())


def normalize_relationships(
    constraints: Dict[str, Dict[str, Any]],
    inferred: List[InferredJoin],
) -> List[Dict[str, Any]]:
    """Collapse verified-FK constraints + inferred joins into ONE row list.

    Row = {source_table, source_columns[], target_table, target_columns[],
    relationship_type, confidence, evidence[]} — field names/literals match the
    future RelationshipMeta (forward-compat). Cartesian-suspect composite FKs (a
    dialect returning N×N instead of 1:1, e.g. postgres information_schema) are
    split into single-column rows here so the renderer stays trivial.
    """
    rows: List[Dict[str, Any]] = []
    for entry in constraints.values():
        pairs = entry["pairs"]
        cname = entry["cname"]
        n_src = len({p[0] for p in pairs})
        n_tgt = len({p[1] for p in pairs})
        if pairs and len(pairs) == n_src == n_tgt:
            rows.append(
                {
                    "source_table": entry["source"],
                    "target_table": entry["target"],
                    "source_columns": [p[0] for p in pairs],
                    "target_columns": [p[1] for p in pairs],
                    "relationship_type": REL_VERIFIED_FK,
                    "confidence": 1.0,
                    "evidence": [cname],
                }
            )
        else:
            # cartesian-suspect → per-pair single-column rows (no over-ANDed ON).
            for sc, tc in pairs:
                rows.append(
                    {
                        "source_table": entry["source"],
                        "target_table": entry["target"],
                        "source_columns": [sc],
                        "target_columns": [tc],
                        "relationship_type": REL_VERIFIED_FK,
                        "confidence": 1.0,
                        "evidence": [cname],
                    }
                )
    for j in inferred:
        rows.append(
            {
                "source_table": j.source_table,
                "target_table": j.target_table,
                "source_columns": [sc for sc, _ in j.column_pairs],
                "target_columns": [tc for _, tc in j.column_pairs],
                "relationship_type": REL_INFERRED_NAME,
                "confidence": 0.5,
                "evidence": [j.reason] if j.reason else [],
            }
        )
    return rows


def _edge_signature(row: Dict[str, Any]) -> frozenset:
    """Direction-agnostic signature of a relationship's column equalities.

    Each ``source.col = target.col`` equality is an unordered endpoint pair
    (lowercased); the signature is the frozenset of those pairs. Two rows with
    the same signature describe the same join (equality is symmetric), so an
    inferred candidate can be deduped against a verified FK regardless of
    direction or column order.
    """
    return frozenset(
        frozenset(
            (
                f"{row['source_table'].lower()}.{sc.lower()}",
                f"{row['target_table'].lower()}.{tc.lower()}",
            )
        )
        for sc, tc in zip(row["source_columns"], row["target_columns"])
    )


def build_join_graph(
    relationships: List[Dict[str, Any]],
    *,
    inject_inferred: bool = True,
) -> str:
    """Render the compact always-inject JOIN graph from normalized rows.

    Format (one edge per line, ON inline)::

        ## JOIN Graph
        ### Verified (foreign keys)
        - SALES → CUSTOMERS  ON SALES.CUSTOMER_ID = CUSTOMERS.CUSTOMER_ID
        ### Inferred (structural candidates — not verified FK)
        - SALES → MATR_MASTER (candidate)  ON SALES.MATR_CODE = MATR_MASTER.MATR_CODE

    No cardinality label (InferredJoin carries none; M:1 synthesis is forbidden).
    No table descriptions (those live in DDL_SCHEMA). Returns "" when there is
    nothing to render (empty graph → caller injects nothing). ``inject_inferred``
    controls whether the inferred section is emitted (default ON; storage keeps
    both tiers, the same gate also applies at inject time). Inferred rows that
    duplicate a verified FK (same column equalities) are dropped — the inferred
    tier surfaces NON-FK structural joins only.
    """
    verified = [r for r in relationships if r["relationship_type"] == REL_VERIFIED_FK]
    inferred = [r for r in relationships if r["relationship_type"] == REL_INFERRED_NAME]
    if not inject_inferred:
        inferred = []
    elif verified and inferred:
        # Drop inferred candidates that merely restate a verified FK (same column
        # equalities, direction-agnostic). The inferred tier is for NON-FK
        # structural joins; echoing a verified FK as "(candidate — not verified
        # FK)" is self-contradictory and wastes always-inject tokens.
        verified_sigs = {_edge_signature(r) for r in verified}
        inferred = [r for r in inferred if _edge_signature(r) not in verified_sigs]
    if not verified and not inferred:
        return ""

    def _edge(row: Dict[str, Any], *, candidate: bool) -> str:
        on = " AND ".join(
            f"{row['source_table']}.{sc} = {row['target_table']}.{tc}"
            for sc, tc in zip(row["source_columns"], row["target_columns"])
        )
        label = " (candidate)" if candidate else ""
        return f"- {row['source_table']} → {row['target_table']}{label}  ON {on}"

    lines = ["## JOIN Graph"]
    if verified:
        lines.append("\n### Verified (foreign keys)")
        lines.extend(_edge(r, candidate=False) for r in verified)
    if inferred:
        lines.append("\n### Inferred (structural candidates — not verified FK)")
        lines.extend(_edge(r, candidate=True) for r in inferred)
    return "\n".join(lines)


# ===========================================================================
# join_graph → structured view for the FE relationship panel (#4/#5) — pure.
#
# The panel renders the SAME relationships the agent sees by PARSING the
# persisted join_graph markdown (parity, no second stored representation), then
# enriches nodes with columns/PK from DDL memory and a soft fact/dim/bridge role
# inferred from join directionality. All pure (no I/O) so the read endpoint stays
# side-effect-free and these compose with the follow-up agent `### Roles` work.
# ===========================================================================


def _strip_table_prefix(qualified: str, table: str) -> str:
    """``table.col`` → ``col`` using the known table prefix (fallback: last seg)."""
    prefix = f"{table}."
    if qualified.startswith(prefix):
        return qualified[len(prefix) :]
    return qualified.rsplit(".", 1)[-1]


def _parse_edge_line(body: str, rel_type: str) -> Optional[Dict[str, Any]]:
    """Parse one ``SRC → TGT[ (candidate)]  ON a.c = b.d[ AND ...]`` edge body.

    Inverse of :func:`build_join_graph`'s ``_edge``. Returns ``None`` for a
    malformed line (no ``ON`` / no arrow / no equality) rather than raising.
    """
    head, sep, on_clause = body.partition("  ON ")
    if not sep:
        return None
    src_part, arrow, tgt_part = head.partition(" → ")
    if not arrow:
        return None
    source_table = src_part.strip()
    target_table = tgt_part.strip()
    if target_table.endswith(" (candidate)"):
        target_table = target_table[: -len(" (candidate)")]
    source_columns: List[str] = []
    target_columns: List[str] = []
    for eq in on_clause.split(" AND "):
        left, eqsep, right = eq.partition(" = ")
        if not eqsep:
            continue
        source_columns.append(_strip_table_prefix(left.strip(), source_table))
        target_columns.append(_strip_table_prefix(right.strip(), target_table))
    if not source_columns:
        return None
    return {
        "source_table": source_table,
        "source_columns": source_columns,
        "target_table": target_table,
        "target_columns": target_columns,
        "relationship_type": rel_type,
        "confidence": 1.0 if rel_type == REL_VERIFIED_FK else 0.5,
        "evidence": [],
    }


def parse_join_graph(md: Optional[str]) -> List[Dict[str, Any]]:
    """Parse a ``build_join_graph`` markdown string back into edge rows.

    Recovers the fields the rendered view preserves — source/target tables,
    source/target columns, and ``relationship_type`` (from the section header →
    ``confidence`` 1.0/0.5). ``evidence`` is not recoverable (returns ``[]``).
    A forward-compat ``### Roles`` section (follow-up B) is ignored. Pure.
    """
    if not md:
        return []
    rows: List[Dict[str, Any]] = []
    rel_type: Optional[str] = None
    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### Verified"):
            rel_type = REL_VERIFIED_FK
            continue
        if line.startswith("### Inferred"):
            rel_type = REL_INFERRED_NAME
            continue
        if line.startswith("#"):
            # "## JOIN Graph" or any other header (e.g. "### Roles") — not an
            # edge; reset so stray "- " lines beneath it aren't parsed as joins.
            rel_type = None
            continue
        if rel_type is None or not line.startswith("- "):
            continue
        edge = _parse_edge_line(line[2:], rel_type)
        if edge is not None:
            rows.append(edge)
    return rows


# fact/dim role inference: how many distinct OUTGOING FKs a dimension may have
# (audit columns like created_by/updated_by) before it stops looking like a dim.
_AUDIT_FK_TOLERANCE = 1


def _infer_table_roles(
    edges: List[Dict[str, Any]],
    table_details: List[TableDetails],
    *,
    truncated: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Infer soft fact/dimension/bridge/unclassified roles from join direction.

    Reuses the fact→dim directionality the join inference already encodes: an
    edge ``source → target`` has ``target`` = the referenced PK = dimension side
    and ``source`` = fact side. Roles aggregate that per table over the full
    relationship set (verified + inferred):

    - ``dimension``: referenced by ≥1 table, references ≤1 (audit-FK tolerance).
    - ``fact``: references ≥2 tables, referenced by none, own surrogate PK.
    - ``bridge``: references ≥2 tables, referenced by none, composite PK = FKs
      (an M:N junction table).
    - ``unclassified``: everything else (hub with both directions, degree ≤1,
      isolated). Default — never over-classify (soft hint, not authoritative).

    ``role_confidence`` is ``high`` when the table participates in a verified FK,
    ``likely`` when only inferred edges support it (denormalized warehouses with
    no FK introspection rely on inferred edges — see #5 H1). Self-referential FKs
    are excluded from degree. ``truncated`` (schema fetch cap hit) forces every
    table to ``unclassified`` — degree over a partial graph misclassifies.

    Keyed by lowercase table name. No cardinality synthesis (Option C drops M:1).
    Pure, no I/O.
    """
    keyed = {td.table_name.lower(): td for td in table_details}
    incoming: Dict[str, set] = {t: set() for t in keyed}  # distinct sources → t
    outgoing: Dict[str, set] = {t: set() for t in keyed}  # distinct targets t → *
    out_cols: Dict[str, set] = {t: set() for t in keyed}  # t's outgoing FK columns
    verified: set = set()
    self_ref: set = set()
    for e in edges:
        s = e["source_table"].lower()
        t = e["target_table"].lower()
        if s == t:
            self_ref.add(s)
            continue  # self-loops do not count toward degree
        if s in outgoing:
            outgoing[s].add(t)
            out_cols[s].update(c.lower() for c in e["source_columns"])
        if t in incoming:
            incoming[t].add(s)
        if e["relationship_type"] == REL_VERIFIED_FK:
            verified.update((s, t))

    roles: Dict[str, Dict[str, Any]] = {}
    for tl, td in keyed.items():
        as_target = len(incoming[tl])
        as_source = len(outgoing[tl])
        pk_cols = {c.name.lower() for c in td.columns if c.is_primary_key}
        is_bridge = len(pk_cols) >= 2 and pk_cols <= out_cols[tl]
        if truncated:
            role = "unclassified"
        elif as_target >= 1 and as_source <= _AUDIT_FK_TOLERANCE:
            role = "dimension"
        elif as_source >= 2 and as_target == 0:
            role = "bridge" if is_bridge else "fact"
        else:
            role = "unclassified"
        roles[tl] = {
            "role": role,
            "role_confidence": (
                None
                if role == "unclassified"
                else ("high" if tl in verified else "likely")
            ),
            "as_target": as_target,
            "as_source": as_source,
            "self_ref": tl in self_ref,
        }
    return roles


def build_join_graph_struct(
    edges: List[Dict[str, Any]],
    table_details: List[TableDetails],
    roles: Dict[str, Dict[str, Any]],
    schema_map: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Assemble the FE relationship graph: nodes (tables + inline columns + role)
    and edges. Every extracted table is a node (isolated ones included). Columns
    are embedded inline (cheap on derive-on-read; powers the node detail panel).
    ``schema_map`` (lowercase table → schema_name) optionally fills node
    ``schema_name`` since ``TableDetails`` carries none. Pure, no I/O.
    """
    schema_map = schema_map or {}
    nodes: List[Dict[str, Any]] = []
    for td in table_details:
        tl = td.table_name.lower()
        r = roles.get(tl, {})
        nodes.append(
            {
                "table": td.table_name,
                "schema_name": schema_map.get(tl),
                "column_count": len(td.columns),
                "columns": [
                    {
                        "name": c.name,
                        "data_type": c.data_type,
                        "is_primary_key": c.is_primary_key,
                        "is_foreign_key": c.is_foreign_key,
                        "foreign_table": c.foreign_table,
                        "foreign_column": c.foreign_column,
                        "is_nullable": c.is_nullable,
                    }
                    for c in td.columns
                ],
                "role": r.get("role", "unclassified"),
                "role_confidence": r.get("role_confidence"),
                "as_target": r.get("as_target", 0),
                "as_source": r.get("as_source", 0),
                "self_ref": r.get("self_ref", False),
            }
        )
    graph_edges = [
        {
            "source_table": e["source_table"],
            "source_columns": list(e["source_columns"]),
            "target_table": e["target_table"],
            "target_columns": list(e["target_columns"]),
            "relationship_type": e["relationship_type"],
            "confidence": e["confidence"],
        }
        for e in edges
    ]
    return {"nodes": nodes, "edges": graph_edges}


@dataclass
class SampleQA:
    """Sample question-answer pair for few-shot learning."""

    question: str
    sql: str
    description: str
    table_name: str
    is_valid: bool = False  # Whether SQL execution succeeded


SCHEMA_EXTRACTION_PROMPT = """당신은 데이터베이스 스키마 분석 전문가입니다.
아래 테이블의 DDL과 샘플 데이터를 분석하여 상세 정보를 생성해주세요.

## 테이블 정보

테이블명: {table_name}

### DDL
```sql
{ddl}
```

### 컬럼 정보
{column_info}

### 샘플 데이터
{sample_data}

## 요청 사항

위 정보를 분석하여 다음 JSON 형식으로 응답해주세요:

```json
{{
    "table_description": "테이블의 목적과 역할에 대한 1-2문장 설명",
    "columns": [
        {{
            "name": "컬럼명",
            "business_meaning": "이 컬럼의 비즈니스적 의미",
            "data_pattern": "발견된 데이터 패턴 (날짜 형식, 코드값 등)"
        }}
    ],
    "data_patterns": ["발견된 주요 데이터 패턴 목록"],
    "related_tables": ["관련될 수 있는 다른 테이블명 추론 (FK 기반 또는 이름 기반)"]
}}
```

### 타임스탬프 컬럼 식별 규칙
- 시간/날짜를 나타내는 컬럼이 정수형(int, bigint 등)으로 정의된 경우, 샘플 값이 10자리(예: 1700000000)면 **유닉스 타임스탬프(초 단위)**입니다.
- `data_pattern`에 "유닉스 타임스탬프(초 단위)"임을 명시하세요.

JSON 형식으로만 응답하세요. 코드 블록이나 부가 설명은 포함하지 마세요."""


SCHEMA_SUMMARY_PROMPT = """당신은 데이터베이스 스키마 분석 전문가입니다.
아래 데이터베이스의 테이블 목록과 각 테이블의 설명을 바탕으로,
이 데이터베이스의 간결한 요약을 생성해주세요.

## 데이터베이스 테이블 정보

{tables_info}

## 요청 사항

다음 형식으로 데이터베이스 요약을 작성해주세요:
1. **전체 개요**: 이 데이터베이스가 어떤 시스템/도메인의 데이터를 관리하는지 1-2문장
2. **테이블 목록**: 각 테이블에 대해 한 줄 요약 (테이블명: 간단한 설명, 주요 컬럼)
3. **주요 관계**: 테이블 간 주요 외래 키 관계 (있는 경우만)

간결하게 작성하되, SQL 쿼리 작성에 필요한 핵심 정보를 빠짐없이 포함하세요.
마크다운 형식으로 작성하세요."""


SAMPLE_QA_GENERATION_PROMPT = """당신은 데이터베이스 전문가입니다.
아래 테이블 정보를 바탕으로 사용자가 자주 질문할 만한 샘플 질문과 SQL을 생성해주세요.

## 테이블 정보

테이블명: {table_name}
설명: {table_description}

### DDL
```sql
{ddl}
```

### 컬럼 정보
{column_info}

### 샘플 데이터
{sample_data}

## 요청 사항

이 테이블에서 사용자가 자주 질문할 만한 3-5개의 자연어 질문과 각 질문에 대한 SQL 쿼리를 생성해주세요.

### 생성 가이드라인
1. 단순 조회부터 집계, 필터링까지 다양한 패턴 포함
2. 실제 비즈니스에서 유용한 질문 위주
3. SQL은 {db_type} 문법에 맞게 작성
4. 너무 복잡한 조인 없이 단일 테이블 쿼리 위주

### 타임스탬프 처리 규칙
- 시간/날짜를 나타내는 컬럼이 정수형(int, bigint 등)으로 정의된 경우, 샘플 값이 10자리(예: 1700000000)면 **유닉스 타임스탬프(초 단위)**입니다.
- 날짜 비교 시 현재 시각도 같은 초 단위 epoch 정수로 변환하여 비교하세요 ({db_type} 문법 사용).

다음 JSON 형식으로 응답해주세요. 반드시 `queries` 키 안에 **3-5개의 항목을 모두 채운 배열**로 응답하세요 (1개만 반환하면 안 됩니다):

```json
{{
    "queries": [
        {{
            "question": "자연어 질문 1",
            "sql": "SELECT ... FROM {table_name} ...",
            "description": "이 쿼리의 용도 설명"
        }},
        {{
            "question": "자연어 질문 2",
            "sql": "SELECT ... FROM {table_name} ...",
            "description": "이 쿼리의 용도 설명"
        }}
    ]
}}
```

JSON 객체 형식으로만 응답하세요. 코드 블록이나 부가 설명은 포함하지 마세요."""


class SchemaExtractor:
    """
    LLM-based schema extractor for generating detailed table descriptions.

    Uses an LLM to analyze DDL, column information, and sample data
    to generate business-meaningful descriptions for database schemas.

    Supports two initialization modes:
    1. model_config: Dict with LLM configuration (recommended)
    2. llm_func: Legacy callback function for LLM calls
    """

    def __init__(
        self,
        sql_runner: SqlRunnerBase,
        model_config: Optional[Dict[str, Any]] = None,
        llm_func: Optional[Callable[[str], str]] = None,
        sample_row_count: int = 5,
        user_id: Optional[str] = None,
    ):
        """
        Initialize the schema extractor.

        Args:
            sql_runner: SQL runner for database operations
            model_config: LLM configuration dict from get_model_config_from_app()
                         Contains: model_id, api_config, base_url, api_key
            llm_func: [DEPRECATED] Async function to call LLM (for backward compatibility)
            sample_row_count: Number of sample rows to retrieve per table
            user_id: User ID for usage tracking (optional)
        """
        self.sql_runner = sql_runner
        self.model_config = model_config
        self.llm_func = llm_func  # Legacy support
        self.sample_row_count = sample_row_count
        self._llm: Optional[BaseChatModel] = None
        self._llm_text: Optional[BaseChatModel] = None
        self._user_id = user_id

    def _create_llm(self, json_mode: bool = True) -> Optional[BaseChatModel]:
        """Create LangChain Chat Model from config.

        json_mode=True forces a JSON-object response (structured extraction).
        Use json_mode=False for free-form/markdown output — some providers
        (OpenAI/Azure) reject response_format=json_object unless the prompt
        literally contains the word "json", so markdown prompts must not use it.
        """
        if not self.model_config:
            return None

        cached = self._llm if json_mode else self._llm_text
        if cached is not None:
            return cached

        from extension_modules.utils.llm import create_llm

        try:
            llm = create_llm(self.model_config, json_mode=json_mode)
            if json_mode:
                self._llm = llm
            else:
                self._llm_text = llm
            return llm
        except Exception as e:
            logger.error(f"Failed to create LLM: {e}")
            return None

    async def _call_llm(
        self, prompt: str, max_retries: int = 3, json_mode: bool = True
    ) -> str:
        """
        Call LLM to generate response with retry on rate limit errors.

        Uses model_config if available, falls back to llm_func for legacy support.
        """
        # Try model_config first (new approach)
        llm = self._create_llm(json_mode=json_mode)
        if llm:
            for attempt in range(max_retries):
                try:
                    response = await llm.ainvoke([HumanMessage(content=prompt)])
                    self._track_usage(response)
                    content = response.content
                    # Gemini/Vertex AI may return list of content blocks
                    if isinstance(content, list):
                        return "".join(
                            block.get("text", "")
                            if isinstance(block, dict)
                            else str(block)
                            for block in content
                        )
                    return content
                except Exception as e:
                    error_str = str(e)
                    status_code = getattr(e, "status_code", None) or (
                        429 if "429" in error_str else 0
                    )
                    if status_code == 429 and attempt < max_retries - 1:
                        wait_time = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                        logger.warning(
                            f"LLM rate limited (429), retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"LLM call via model_config failed: {e}")
                    break

        # Legacy fallback: use llm_func if provided
        if self.llm_func:
            for attempt in range(max_retries):
                try:
                    return await self.llm_func(prompt)
                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str and attempt < max_retries - 1:
                        wait_time = 2 ** (attempt + 1)
                        logger.warning(
                            f"LLM rate limited (429), retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"LLM call via llm_func failed: {e}")
                    break

        return ""

    def _track_usage(self, response) -> None:
        """Track LLM usage if user_id is available."""
        if not self._user_id:
            return
        try:
            from open_webui.models.usage import Usages

            usage = getattr(response, "usage_metadata", None)
            total_tokens = usage.get("total_tokens") if usage else None
            model_id = (
                self.model_config.get("model_id", "") if self.model_config else ""
            )
            Usages.insert_new_usage(
                user_id=self._user_id,
                chat_id=None,
                model_id=model_id,
                message_id=str(uuid.uuid4()),
                message_type="schema_extraction",
                total_tokens=total_tokens or 0,
                usage=usage,
            )
        except Exception as e:
            logger.debug(f"Failed to track schema extraction usage: {e}")

    def _has_llm(self) -> bool:
        """Check if LLM is configured."""
        return self.model_config is not None or self.llm_func is not None

    def _truncate_sample_data(
        self,
        df,
        max_cell_length: int = 100,
        max_total_chars: int = 3000,
    ) -> str:
        """
        Truncate sample data to avoid excessively long prompts.

        Args:
            df: pandas DataFrame with sample data
            max_cell_length: Maximum characters per cell
            max_total_chars: Maximum total characters for the output

        Returns:
            Truncated markdown string
        """
        if df is None or df.empty:
            return "샘플 데이터 없음"

        # Create a copy to avoid modifying original
        truncated_df = df.copy()

        # Truncate each cell
        for col in truncated_df.columns:
            truncated_df[col] = truncated_df[col].apply(
                lambda x: (
                    str(x)[:max_cell_length] + "..."
                    if isinstance(x, str) and len(str(x)) > max_cell_length
                    else x
                )
            )

        # Convert to markdown
        result = truncated_df.to_markdown()

        # Truncate total length if needed
        if len(result) > max_total_chars:
            result = result[:max_total_chars] + "\n... (truncated)"

        return result

    async def extract_table_details(
        self,
        table_name: str,
        runner: Optional[SqlRunnerBase] = None,
    ) -> Optional[TableDetails]:
        """
        Extract detailed information for a single table using LLM.

        Args:
            table_name: Name of the table to analyze
            runner: Optional per-task SQL runner. During parallel extraction a
                dedicated runner (own connection) is passed for thread safety;
                defaults to the shared ``self.sql_runner`` for sequential callers.

        Returns:
            TableDetails with LLM-generated descriptions, or None if extraction fails.
            If LLM is not configured, returns basic details without descriptions.
        """
        r = runner or self.sql_runner
        try:
            # Allow-list the catalog-derived table name before it flows into
            # introspection queries (defense-in-depth; names come from
            # get_all_tables()). Unicode-aware so Korean table names pass.
            validate_sql_identifier(table_name, kind="table")

            # 1. Get DDL
            ddl = await r.get_table_ddl(table_name)

            # 2. Get column information
            columns = await r.get_table_columns(table_name)

            # 3. If LLM is configured, use it to generate descriptions
            if self._has_llm():
                column_info = self._format_column_info(columns)

                # Get sample data for LLM context (truncated to avoid long prompts)
                samples = await r.get_random_samples(
                    table_name,
                    limit=self.sample_row_count,
                )
                sample_data = self._truncate_sample_data(samples)

                # Build prompt
                prompt = SCHEMA_EXTRACTION_PROMPT.format(
                    table_name=table_name,
                    ddl=ddl,
                    column_info=column_info,
                    sample_data=sample_data,
                )

                # Call LLM
                response = await self._call_llm(prompt)

                if response:
                    # Parse response
                    return self._parse_llm_response(table_name, ddl, columns, response)

            # No LLM configured or LLM failed - return basic details without descriptions
            logger.info(f"Saving basic schema for table: {table_name}")
            return TableDetails(
                table_name=table_name,
                ddl=ddl,
                description="",
                columns=[
                    ColumnDetail(
                        name=col.column_name,
                        data_type=col.data_type,
                        is_primary_key=col.is_primary_key,
                        is_foreign_key=col.is_foreign_key,
                        foreign_table=col.foreign_table,
                        foreign_column=col.foreign_column,
                        is_nullable=col.is_nullable,
                        default_value=col.column_default,
                    )
                    for col in columns
                ],
            )

        except Exception as e:
            logger.error(f"Failed to extract details for table {table_name}: {e}")
            return None

    def _format_column_info(self, columns: List) -> str:
        """Format column information for the prompt."""
        lines = []
        for col in columns:
            col_line = f"- {col.column_name}: {col.data_type}"
            if col.is_primary_key:
                col_line += " [PK]"
            if col.is_foreign_key:
                col_line += f" [FK -> {col.foreign_table}.{col.foreign_column}]"
            if not col.is_nullable:
                col_line += " NOT NULL"
            if col.column_default:
                col_line += f" DEFAULT {col.column_default}"
            lines.append(col_line)
        return "\n".join(lines)

    def _parse_llm_response(
        self,
        table_name: str,
        ddl: str,
        columns: List,
        response: str,
    ) -> Optional[TableDetails]:
        """Parse LLM response into TableDetails."""
        try:
            # Try to extract JSON from response
            response = response.strip()

            # Handle cases where LLM wraps JSON in code blocks
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]

            data = json.loads(response.strip())

            # Build column details with LLM descriptions
            column_details = []
            llm_columns = {c["name"]: c for c in data.get("columns", [])}

            for col in columns:
                llm_col = llm_columns.get(col.column_name, {})
                column_details.append(
                    ColumnDetail(
                        name=col.column_name,
                        data_type=col.data_type,
                        description=llm_col.get("business_meaning"),
                        is_primary_key=col.is_primary_key,
                        is_foreign_key=col.is_foreign_key,
                        foreign_table=col.foreign_table,
                        foreign_column=col.foreign_column,
                        is_nullable=col.is_nullable,
                        default_value=col.column_default,
                    )
                )

            return TableDetails(
                table_name=table_name,
                ddl=ddl,
                description=data.get("table_description", ""),
                columns=column_details,
                data_patterns=data.get("data_patterns", []),
                related_tables=data.get("related_tables", []),
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            # Return basic details without LLM descriptions
            return TableDetails(
                table_name=table_name,
                ddl=ddl,
                description="",
                columns=[
                    ColumnDetail(
                        name=col.column_name,
                        data_type=col.data_type,
                        is_primary_key=col.is_primary_key,
                        is_foreign_key=col.is_foreign_key,
                        foreign_table=col.foreign_table,
                        foreign_column=col.foreign_column,
                        is_nullable=col.is_nullable,
                        default_value=col.column_default,
                    )
                    for col in columns
                ],
            )
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return None

    async def extract_all_schemas(
        self,
        table_names: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> List[TableDetails]:
        """
        Extract detailed information for all tables (or specified tables).

        Args:
            table_names: Optional list of table names to extract.
                        If None, extracts all tables.
            progress_callback: Optional callback for progress updates.
                              Called with (table_name, current_index, total_count)

        Returns:
            List of TableDetails for all processed tables
        """
        # Get table list if not provided
        if table_names is None:
            tables = await self.sql_runner.get_all_tables()
            table_names = [t.table_name for t in tables]

        results = []
        total = len(table_names)

        for idx, table_name in enumerate(table_names):
            if progress_callback:
                progress_callback(table_name, idx + 1, total)

            details = await self.extract_table_details(table_name)
            if details:
                results.append(details)

        return results

    async def generate_sample_qa(
        self,
        table_details: TableDetails,
        db_type: str = "SQL",
        validate_sql: bool = True,
        runner: Optional[SqlRunnerBase] = None,
    ) -> List[SampleQA]:
        """
        Generate sample Q&A pairs for a table using LLM.

        Args:
            table_details: TableDetails object with schema information
            db_type: Database type for SQL syntax (e.g., "PostgreSQL", "MySQL")
            validate_sql: Whether to validate SQL by execution
            runner: Optional per-task SQL runner (own connection) used during
                parallel extraction; defaults to the shared ``self.sql_runner``.

        Returns:
            List of SampleQA objects (with is_valid=True if SQL executed successfully)
        """
        if not self._has_llm():
            logger.info("LLM not configured, skipping sample Q&A generation")
            return []

        r = runner or self.sql_runner
        try:
            # table 식별자를 sink 직전에 재검증 — 호출자가 검증을 건너뛰었더라도
            # runner introspection SQL 에 미검증 식별자가 들어가지 않도록 방어한다.
            validate_sql_identifier(table_details.table_name, kind="table")
            # Get sample data for context (truncated to avoid long prompts)
            samples = await r.get_random_samples(
                table_details.table_name,
                limit=self.sample_row_count,
            )
            sample_data = self._truncate_sample_data(samples)

            # Format column info
            column_info = self._format_column_info_for_qa(table_details.columns)

            # Build prompt
            prompt = SAMPLE_QA_GENERATION_PROMPT.format(
                table_name=table_details.table_name,
                table_description=table_details.description or "설명 없음",
                ddl=table_details.ddl,
                column_info=column_info,
                sample_data=sample_data,
                db_type=db_type,
            )

            # Call LLM
            response = await self._call_llm(prompt)
            if not response:
                return []

            # Parse response
            qa_list = self._parse_sample_qa_response(
                response,
                table_details.table_name,
            )

            # Validate SQL if requested
            if validate_sql and qa_list:
                qa_list = await self._validate_sample_queries(qa_list, runner=r)

            return qa_list

        except Exception as e:
            logger.error(
                f"Failed to generate sample Q&A for {table_details.table_name}: {e}"
            )
            return []

    def _format_column_info_for_qa(self, columns: List[ColumnDetail]) -> str:
        """Format column information for the Q&A generation prompt."""
        lines = []
        for col in columns:
            col_line = f"- {col.name} ({col.data_type})"
            if col.description:
                col_line += f": {col.description}"
            if col.is_primary_key:
                col_line += " [PK]"
            if col.is_foreign_key and col.foreign_table:
                col_line += f" [FK -> {col.foreign_table}]"
            lines.append(col_line)
        return "\n".join(lines)

    def _parse_sample_qa_response(
        self,
        response: str,
        table_name: str,
    ) -> List[SampleQA]:
        """Parse LLM response into SampleQA objects."""
        try:
            # Try to extract JSON from response
            response = response.strip()

            # Handle cases where LLM wraps JSON in code blocks
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]

            data = json.loads(response.strip())

            # json_mode forces top-level object; unwrap if array is nested
            if isinstance(data, dict):
                # Case 1: nested list (e.g. {"items": [...]} or {"final": [...]})
                unwrapped = False
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        unwrapped = True
                        break
                    # Handle stringified JSON array inside object
                    if isinstance(v, str):
                        try:
                            parsed = json.loads(v)
                            if isinstance(parsed, list):
                                data = parsed
                                unwrapped = True
                                break
                        except (json.JSONDecodeError, TypeError):
                            pass
                # Case 2: single QA object (e.g. {"question": "...", "sql": "..."})
                if not unwrapped and "question" in data and "sql" in data:
                    data = [data]

            if not isinstance(data, list):
                logger.warning("Sample Q&A response is not a list")
                return []

            qa_list = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                if "question" not in item or "sql" not in item:
                    continue

                qa_list.append(
                    SampleQA(
                        question=item["question"],
                        sql=item["sql"],
                        description=item.get("description", ""),
                        table_name=table_name,
                        is_valid=False,
                    )
                )

            return qa_list

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse sample Q&A response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to parse sample Q&A response: {e}")
            return []

    async def _validate_sample_queries(
        self,
        qa_list: List[SampleQA],
        runner: Optional[SqlRunnerBase] = None,
    ) -> List[SampleQA]:
        """Validate sample queries by executing them.

        A query is marked valid only if:
        1. It executes without raising an exception, AND
        2. It returns at least 1 row (0 rows likely indicates a wrong filter,
           e.g. timestamp * 1000 producing a far-future epoch value)
        """
        r = runner or self.sql_runner
        validated = []

        for qa in qa_list:
            try:
                test_sql = r.apply_row_limit(qa.sql, 1)

                result = await r.run_sql(test_sql)

                if result is not None and hasattr(result, "empty") and result.empty:
                    logger.warning(
                        f"SQL returned 0 rows (possible wrong filter) for: "
                        f"'{qa.question[:50]}...' — SQL: {qa.sql[:100]}"
                    )
                    qa.is_valid = False
                else:
                    qa.is_valid = True

            except Exception as e:
                logger.debug(f"SQL validation failed for '{qa.question[:30]}...': {e}")
                qa.is_valid = False

            validated.append(qa)

        valid_count = sum(1 for q in validated if q.is_valid)
        logger.info(
            f"Sample Q&A validation: {valid_count}/{len(validated)} queries valid"
        )

        return validated

    async def extract_and_save_to_memory(
        self,
        memory,  # SearchEngineDbSphereMemory instance
        table_names: Optional[List[str]] = None,
        progress_callback: Optional[Callable[..., None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        generate_sample_qa: bool = True,
        db_type: str = "SQL",
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, int]:
        """
        Extract schema details and save them to memory.

        Also generates sample Q&A pairs for few-shot learning if LLM is configured.

        Args:
            memory: SearchEngineDbSphereMemory instance
            table_names: Optional list of table names to extract
            progress_callback: Optional callback for progress updates.
                              Called with (table_name, current, total, phase, ddl_saved, qa_saved)
                              phase: "extracting", "saving_ddl", "generating_qa", "saving_qa"
            metadata: Additional metadata to store with each memory
            generate_sample_qa: Whether to generate sample Q&A pairs
            db_type: Database type for SQL syntax in Q&A generation
            should_cancel: Optional callable returning True when the user has
                           requested cancellation. Checked cooperatively per
                           table (at semaphore acquire and before Q&A) and after
                           the batch. Cannot interrupt an in-flight LLM call.

        Returns:
            Dict with counts: {"ddl_saved": N, "qa_saved": M}.
            When cancelled, also includes {"cancelled": True}.
        """
        result = {"ddl_saved": 0, "qa_saved": 0, "table_details": []}

        def _cancelled() -> bool:
            try:
                return bool(should_cancel and should_cancel())
            except Exception:
                return False

        # Get table list if not provided
        if table_names is None:
            tables = await self.sql_runner.get_all_tables()
            table_names = [t.table_name for t in tables]

        # Pre-check: bail before doing any work if cancel was already requested.
        if _cancelled():
            result["cancelled"] = True
            return result

        total = len(table_names)

        # Track completed count + currently-in-flight set so the UI can show
        # "X done, Y in progress" — important because tables run in parallel
        # via asyncio.gather, so `completed` stays at 0 for the whole first
        # wave (bar appears frozen until a table finishes).
        progress_state: dict = {"completed": 0, "in_progress": set()}

        def call_progress(table_name: str, phase: str):
            if progress_callback:
                try:
                    progress_callback(
                        table_name,
                        progress_state["completed"],
                        total,
                        phase,
                        result["ddl_saved"],
                        result["qa_saved"],
                        len(progress_state["in_progress"]),
                    )
                except TypeError:
                    # Fallback for callbacks without the in_progress arg
                    try:
                        progress_callback(
                            table_name,
                            progress_state["completed"],
                            total,
                            phase,
                            result["ddl_saved"],
                            result["qa_saved"],
                        )
                    except TypeError:
                        progress_callback(
                            table_name, progress_state["completed"], total
                        )

        # Process tables in parallel with concurrency limit
        semaphore = asyncio.Semaphore(5)

        # 추출 집합 외부 테이블은 LLM 환각이거나 사용자가 의도하지 않은 것이므로 제외.
        extracted_set = {t.lower() for t in table_names}

        async def _extract_one(table_name: str, runner):
            """Per-table work. Timed AFTER a semaphore slot is acquired.

            ``runner`` is a per-task SQL runner (its own DBAPI connection) for
            raw-connection dialects (Oracle/MSSQL/Synapse 등) that are not safe for
            the concurrent run_in_executor threads each query spawns, or the shared
            pool-based runner (Postgres/MySQL) which is already concurrency-safe.
            A per-task runner is owned and closed by the caller (``process_table``).
            """
            progress_state["in_progress"].add(table_name)
            # Phase 1: Extract schema
            call_progress(table_name, "extracting")
            details = await self.extract_table_details(table_name, runner=runner)

            if not details:
                return

            # LLM 이 추론한 related_tables 중 실제 추출된 테이블만 남김
            if details.related_tables:
                details.related_tables = [
                    t for t in details.related_tables if t.lower() in extracted_set
                ]

            try:
                # Phase 2: Save DDL
                call_progress(table_name, "saving_ddl")

                # Convert ColumnDetail to dict format expected by save_ddl_memory
                columns = [asdict(col) for col in details.columns]

                ddl_result = await memory.save_ddl_memory(
                    ddl_statement=details.ddl,
                    table_name=details.table_name,
                    columns=columns,
                    table_description=details.description,
                    relationships=details.related_tables,
                    metadata=metadata,
                )

                if ddl_result:
                    result["ddl_saved"] += 1
                    result["table_details"].append(details)
                    logger.info(f"Saved DDL memory for table: {details.table_name}")

                # Generate and save sample Q&A if enabled
                # Checkpoint 2: skip the expensive Q&A LLM call if cancelled
                # — this is the step the user actually waits on.
                if generate_sample_qa and self._has_llm() and not _cancelled():
                    # Phase 3: Generate Q&A
                    call_progress(table_name, "generating_qa")

                    qa_list = await self.generate_sample_qa(
                        table_details=details,
                        db_type=db_type,
                        validate_sql=True,
                        runner=runner,
                    )

                    # Save only valid Q&A pairs
                    valid_count = sum(1 for qa in qa_list if qa.is_valid)
                    if valid_count > 0:
                        # Phase 4: Save Q&A
                        call_progress(table_name, "saving_qa")

                    for qa in qa_list:
                        if qa.is_valid:
                            try:
                                qa_result = await memory.save_sql_memory(
                                    question=qa.question,
                                    sql=qa.sql,
                                    success=True,
                                    metadata={
                                        **(metadata or {}),
                                        "source": "schema_extraction",
                                        "origin": "schema_extraction",
                                        "table_name": qa.table_name,
                                        "description": qa.description,
                                    },
                                )
                                if qa_result:
                                    result["qa_saved"] += 1
                                    logger.debug(
                                        f"Saved sample Q&A: {qa.question[:50]}..."
                                    )
                            except Exception as e:
                                logger.warning(f"Failed to save sample Q&A: {e}")

            except Exception as e:
                logger.error(f"Failed to save DDL memory for {details.table_name}: {e}")

        async def process_table(idx: int, table_name: str):
            async with semaphore:
                # Checkpoint 1: queued tables that haven't started yet skip
                # immediately once cancellation is requested.
                if _cancelled():
                    progress_state["completed"] += 1
                    progress_state["in_progress"].discard(table_name)
                    return
                # Pool 기반 runner(Postgres/MySQL)는 pool.acquire() 로 쿼리마다 독립
                # 커넥션을 받아 이미 동시성 안전하므로 shared runner 를 그대로 재사용한다
                # — 테이블마다 새 pool 을 만들면 커넥션이 증폭되고 pool 생성/파기가 반복
                # 된다. raw single-connection runner(Oracle/MSSQL/Synapse/Snowflake/
                # Databricks 등)만 동시 to_thread 가 한 커넥션을 공유하지 않도록 task 별
                # 전용 runner 를 만든다. 슬롯 획득 후 생성하므로 동시 오픈은 Semaphore(5)
                # 이내로 유지된다.
                task_runner = None
                if not getattr(self.sql_runner, "is_pool_based", False):
                    try:
                        from extension_modules.dbsphere.sql_runners import (
                            create_sql_runner,
                        )

                        task_runner = create_sql_runner(self.sql_runner.config)
                    except Exception as e:
                        # raw-connection 방언에서 전용 runner 생성 실패 시 shared runner
                        # 로 폴백하면 동시 접근이 thread-safe 하지 않으므로 WARNING.
                        logger.warning(
                            f"Per-task runner unavailable for {table_name} ({e}); "
                            f"falling back to shared runner — concurrent access to a "
                            f"single-connection runner is not thread-safe"
                        )
                runner = task_runner or self.sql_runner
                # The 300s budget wraps only the work — AFTER acquiring a slot —
                # not the semaphore queue wait. Otherwise tables at the back of the
                # queue burn their timeout while waiting and never start (tail
                # starvation when the LLM is slow or table count is high).
                try:
                    await asyncio.wait_for(
                        _extract_one(table_name, runner), timeout=300
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        f"Table {table_name} timed out after 300s of processing, "
                        f"skipping"
                    )
                except Exception as e:
                    logger.error(f"Table {table_name} failed: {e}")
                finally:
                    # Close the per-task connection; never close the shared runner.
                    if task_runner is not None:
                        try:
                            await task_runner.close()
                        except Exception as e:
                            logger.debug(f"Per-task runner close failed: {e}")
                    progress_state["completed"] += 1
                    progress_state["in_progress"].discard(table_name)
                    # Final tick so the bar advances even if the next table's
                    # "extracting" phase doesn't fire yet.
                    call_progress(table_name, "saving_qa")

        # Hold the search engine open across the whole batch.
        # Each save_*/search_* call would otherwise enter+exit its own engine
        # context and close the shared client, breaking the other parallel
        # tasks mid-insert.
        async with memory.session():
            tasks = [
                process_table(idx, table_name)
                for idx, table_name in enumerate(table_names)
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Checkpoint 3: if cancelled, skip the cross-table relationship
            # analysis + summary (more LLM work) and report partial result.
            if _cancelled():
                result["cancelled"] = True
                logger.info(
                    f"Schema extraction cancelled after {result['ddl_saved']} "
                    f"tables saved"
                )
                return result

            # Recompute the always-inject join_graph over the FULL extraction set
            # S (Option C): reload all DDL_SCHEMA, merge this batch, then recompute
            # verified FK (shared-runner introspection — survives the gather) +
            # inferred joins (pure, over table_details). The join_graph string +
            # full_table_details are returned in result; the persistence layer
            # (router) writes them to dbsphere.data atomically with schema_summary
            # /table_overview recomputed over the same full S. cancel was already
            # gated by Checkpoint 3 above (here = not cancelled).
            if result["ddl_saved"] > 0:
                try:
                    recompute = await self._recompute_join_graph(
                        memory, result["table_details"]
                    )
                    result["join_graph"] = recompute["join_graph"]
                    result["join_graph_truncated"] = recompute["truncated"]
                    result["full_table_details"] = recompute["full_table_details"]
                except Exception as e:
                    logger.warning(f"Failed to recompute join_graph: {e}")

        logger.info(
            f"Schema extraction complete: {result['ddl_saved']} DDL, "
            f"{result['qa_saved']} sample Q&A saved"
        )
        return result

    async def _infer_column_semantics(
        self, table_details: List[TableDetails]
    ) -> List[InferredJoin]:
        """추출된 스키마에서 fact→dim JOIN 후보를 구조 신호로 추론한다 (v1).

        verified FK 가 없는 denormalized 스키마를 위한 2차 신호. 컬럼명 동일성으로
        후보를 만들고 4개 구조 게이트(G1-PK target-is-key / G2 ubiquity /
        G5 composite-aware / G4 double-target)로 shared-attribute fan-out 을
        차단한다. ``ColumnDetail.is_primary_key`` (시스템 카탈로그 introspection,
        LLM 무오염) 만 사용 — 추가 쿼리·LLM 호출 없음(순수 구조 분석). 결과는
        verified FK 와 엄격히 분리된 2차 라벨(candidate) 후보 목록이다.

        Capability gate (data-driven): 추출 집합 전체에 PK 신호가 하나도 없으면
        (databricks/bigquery 는 PK 항상 False, Fabric Warehouse 는 NOT ENFORCED 시
        empty) 모든 후보가 G1 에서 reject 되므로 후보 생성 전에 early-exit 한다 —
        무의미한 작업 0, noise 0(false-negative-safe). 하드코딩 dialect allowlist
        대신 실측 신호(``any(is_primary_key)``)로 판정해 유지보수 비용 0.
        """
        has_pk_signal = any(
            col.is_primary_key for td in table_details for col in td.columns
        )
        if not has_pk_signal:
            logger.info(
                "No PK signal in extracted schema (dialect=%s); skipping "
                "fact→dim join inference. databricks/bigquery expose no PK "
                "introspection and Fabric Warehouse keys may be NOT ENFORCED — "
                "declare keys or backfill via information_schema to enable.",
                self._dialect_name(),
            )
            return []

        # 구조 신호 준비 + 결정론적 same-name 후보 생성 + 5-gate 순차 적용.
        # G1 단독으론 composite-member 를 통과시키므로 G5 필수(보완성). gate 순서는
        # G6(source-not-sole-PK) → G1(target-is-key) → G2(ubiquity) → G5(composite)
        # → G4(double-target).
        pk_set = self._build_pk_set(table_details)
        name_freq = self._build_name_freq(table_details)
        # ubiquity 임계 k 는 schema-size 적응(편재 기준이 큰 스키마에서 더 큼).
        # 실키(dimension PK)는 pk_anywhere 보호로 k 와 무관하게 false-negative 없음.
        k = max(3, len(table_details) // 8)

        candidates = self._generate_same_name_candidates(table_details)
        candidates = self._gate_source_not_sole_pk(candidates, pk_set)  # G6
        candidates = self._gate_target_is_key(candidates, pk_set)  # G1
        candidates = self._gate_ubiquity(candidates, name_freq, pk_set, k)  # G2
        candidates = self._gate_composite(candidates, pk_set)  # G5
        candidates = self._gate_double_target(candidates, pk_set)  # G4
        if candidates:
            logger.info(
                "Inferred %d fact→dim join candidate(s) from column semantics "
                "(dialect=%s, %d tables)",
                len(candidates),
                self._dialect_name(),
                len(table_details),
            )
        return candidates

    def _dialect_name(self) -> str:
        """진단 로그용 best-effort dialect 라벨 (절대 raise 하지 않음)."""
        try:
            from extension_modules.dbsphere.sql_runners import get_dialect_name

            return get_dialect_name(self.sql_runner.config.get_db_type_enum())
        except Exception:
            return type(self.sql_runner).__name__

    @staticmethod
    def _generate_same_name_candidates(
        table_details: List[TableDetails],
    ) -> List[InferredJoin]:
        """동일 컬럼명 쌍에서 결정론적 join 후보를 생성한다 (v1 — LLM 없음).

        매칭은 case-insensitive(Oracle UPPER vs postgres lower 혼재 대비), 출력은
        각 테이블의 원본 컬럼 표기를 복원한다. 한 컬럼명이 ≥2 개 테이블에 존재할
        때 그 테이블들 사이의 **양방향** directed candidate 를 만든다 — 어느 쪽이
        dimension(PK 보유)인지는 이 단계에서 알 수 없으므로 G1(target-is-key)이
        방향을 결정한다. 생성기는 noise 판정을 하지 않는다(생성 vs 게이트 분리).

        모든 후보는 table_details(추출 집합) 내부 컬럼만 참조하므로 cross-DB 환각·
        경계 밖 참조가 구조적으로 불가능하다. (v2 LLM cross-name 은 이 lowercase
        lookup 을 명시적 existence 검증으로 재사용해 환각을 차단한다.)
        """
        # lowercase 컬럼명 → [(원본 테이블명, 원본 컬럼명), ...] (테이블당 1회)
        occurrences: Dict[str, List[Tuple[str, str]]] = {}
        for td in table_details:
            seen: set = set()
            for col in td.columns:
                key = col.name.lower()
                if key in seen:
                    continue
                seen.add(key)
                occurrences.setdefault(key, []).append((td.table_name, col.name))

        candidates: List[InferredJoin] = []
        for key, occ in occurrences.items():
            if len(occ) < 2:
                continue  # 동일명이 ≥2 테이블에 있어야 join 후보
            for src_table, src_col in occ:
                for tgt_table, tgt_col in occ:
                    if src_table == tgt_table:
                        continue
                    candidates.append(
                        InferredJoin(
                            source_table=src_table,
                            target_table=tgt_table,
                            column_pairs=[(src_col, tgt_col)],
                            confidence="candidate",
                            reason=f"same-name column '{key}'",
                        )
                    )
        return candidates

    @staticmethod
    def _build_pk_set(table_details: List[TableDetails]) -> Dict[str, set]:
        """lowercase 테이블명 → {lowercase PK 컬럼명} 집합 (복합 PK 전 멤버 포함).

        PK 없는 테이블은 맵에서 누락(databricks/bigquery/empty-fabric) — G1 이
        그 테이블을 target 으로 하는 후보를 전부 reject 하게 만든다.
        ``is_primary_key`` 는 시스템 카탈로그 introspection 결과(LLM 무오염)이고,
        복합 PK 는 멤버 컬럼이 개별 ``is_primary_key=True`` 로 플래그된다.
        """
        pk_set: Dict[str, set] = {}
        for td in table_details:
            keys = {c.name.lower() for c in td.columns if c.is_primary_key}
            if keys:
                pk_set[td.table_name.lower()] = keys
        return pk_set

    @staticmethod
    def _gate_source_not_sole_pk(
        candidates: List[InferredJoin], pk_set: Dict[str, set]
    ) -> List[InferredJoin]:
        """G6: source 컬럼(집합)이 source 테이블의 단일컬럼 PK 전체면 reject.

        generic surrogate PK('id', single-col)는 row identity 일 뿐 outbound FK 가
        아니다 — 진짜 FK 는 source 의 non-key 컬럼(SPLR_CODE 등)이 target dim 의 PK
        를 가리킨다. 'id' 가 거의 모든 테이블에 sole PK 로 존재하면 same-name 생성이
        A.id↔B.id 의 O(N²) fan-out 을 만들고 G1(target id 도 PK)·G4(alpha tie-break)
        를 통과해 모든 테이블의 id → 알파벳 첫 id-PK 테이블로 붕괴하는 noise 가
        생긴다(예: 17 tables × id → audit_log.id). 이 게이트는 candidate 의 source
        컬럼 전체가 단일 멤버 PK 와 일치하면 차단해 그 fan-out 을 근원에서 제거한다.

        복합 PK(len>1) 멤버는 면제한다 — bridge/junction 테이블의 PK 멤버는 두 부모
        dim 의 PK 를 가리키는 정당한 FK 이므로 single-member surrogate 와 구별한다.
        G1 보다 먼저 적용해 noise 후보가 downstream gate 비용을 발생시키기 전에 제거.

        알려진 trade-off(의도적 수용): shared-PK 1:1 extension(USER_PROFILE.user_id
        가 sole PK 인 동시에 USERS.user_id 로의 정당한 FK)도 같은 구조 신호(source
        sole-PK == join 컬럼)를 가져 함께 drop 된다 — PK 멤버십·동일명만으론 surrogate
        identity 와 구별 불가. candidate-tier soft hint 이고 target 도메인(reporting/DW,
        surrogate id 편재)에서 드문 패턴이라 수용. declared FK(is_foreign_key) 신호를
        gate 로 끌어와 면제하는 정식 보강은 G4 신호확장 사이클로 이연(backlog).
        """
        kept: List[InferredJoin] = []
        for c in candidates:
            sk = pk_set.get(c.source_table.lower(), set())
            if len(sk) == 1 and all(src.lower() in sk for src, _ in c.column_pairs):
                continue  # single-col surrogate PK source → row identity, not FK
            kept.append(c)
        return kept

    @staticmethod
    def _gate_target_is_key(
        candidates: List[InferredJoin], pk_set: Dict[str, set]
    ) -> List[InferredJoin]:
        """G1: target 컬럼이 target 테이블의 PK 멤버일 때만 통과 (structural).

        non-key parent pointer(FMPF 상수, PLANT_CODE 순수속성, PAR_OBJ_ID 등)를
        차단 — 진짜 relationship 의 target 은 dimension 의 PK 이고, shared-attribute
        noise 의 target 은 양쪽 non-key 라는 구조적 비대칭을 이용한다. 복합 PK 의
        부분 멤버도 '키 멤버'이므로 여기선 통과하고, 완전성(전체 cover)은
        G5(composite-aware)가 판정한다(보완성 — G1 단독은 composite-half 통과).
        """
        kept: List[InferredJoin] = []
        for c in candidates:
            keys = pk_set.get(c.target_table.lower())
            if not keys:
                continue  # target 에 PK 없음 → reject
            if all(tgt.lower() in keys for _, tgt in c.column_pairs):
                kept.append(c)
        return kept

    @staticmethod
    def _build_name_freq(table_details: List[TableDetails]) -> Dict[str, int]:
        """lowercase 컬럼명 → 등장 테이블 수 (테이블당 1회 카운트). G2 ubiquity 입력."""
        freq: Dict[str, int] = {}
        for td in table_details:
            seen: set = set()
            for col in td.columns:
                key = col.name.lower()
                if key in seen:
                    continue
                seen.add(key)
                freq[key] = freq.get(key, 0) + 1
        return freq

    @staticmethod
    def _gate_ubiquity(
        candidates: List[InferredJoin],
        name_freq: Dict[str, int],
        pk_set: Dict[str, set],
        k: int,
    ) -> List[InferredJoin]:
        """G2: 편재 컬럼(name_freq > k)이면서 어느 테이블에서도 PK 가 아니면 suppress.

        순수 공유속성(PLANT_CODE 가 N 테이블에 편재, 어디서도 PK 아님)의 N×N
        fan-out 을 차단한다. **컬럼이 어느 테이블에선가 PK 면(PK-target candidate)
        절대 suppress 안 함** — multi-fact → single-dim(SPLR_CODE 4-fact →
        SPLR_MASTER PK)은 편재하지만 정당한 star join 이므로 false-negative 를
        방지한다. ``k`` 는 schema-size 적응(호출자가 계산).

        NOTE: 현재 pipeline 순서(G1 → G2)에서 G2 는 실효 no-op 이다 — G1
        (target-is-key)을 통과한 후보는 target 컬럼이 항상 ``pk_anywhere`` 에
        속하므로 G2 의 suppress 조건(``cols & pk_anywhere == ∅``)이 성립하지 않는다.
        순수속성 fan-out 은 G1(비-PK target reject)이, composite-half 는 G5 가
        이미 차단한다. G2 는 명시적 ubiquity 원칙 문서화 + G1 완화 시 backstop 으로
        보존한다(net noise 차단은 G1/G5 담당, 동작 동일).
        """
        pk_anywhere = {col for keys in pk_set.values() for col in keys}
        kept: List[InferredJoin] = []
        for c in candidates:
            cols = {col.lower() for pair in c.column_pairs for col in pair}
            if cols & pk_anywhere:
                kept.append(c)  # PK-anywhere → 보호(절대 suppress 안 함)
                continue
            if any(name_freq.get(col, 0) > k for col in cols):
                continue  # 비-PK + 편재 → suppress (fan-out)
            kept.append(c)
        return kept

    @staticmethod
    def _gate_composite(
        candidates: List[InferredJoin], pk_set: Dict[str, set]
    ) -> List[InferredJoin]:
        """G5: 복합 PK 는 전 멤버 cover 시만 단일 composite join, partial 은 reject.

        inferred candidate 엔 constraint_name 이 없어 verified 의 CONSTRAINT_NAME
        그룹핑을 재사용할 수 없으므로(critique C1) (source_t, target_t) 별로 target
        PK 멤버 cover 를 자체 판정한다. 단일 멤버 PK 는 각 후보가 독립적으로
        full-cover 하므로 그대로 통과 — 여러 source → 한 dim 은 별도 star join 으로
        유지(2-table 다관계 오합침 방지). 복합 PK 는 한 source 가 전 멤버를 cover
        할 때만 ``ON a.c1=b.c1 AND a.c2=b.c2`` 단일 합성, 절반만 매칭하면
        (composite-half — PLANT_CODE 단독) 전체 reject 한다.
        """
        groups: Dict[Tuple[str, str], List[InferredJoin]] = {}
        for c in candidates:
            groups.setdefault((c.source_table, c.target_table), []).append(c)

        result: List[InferredJoin] = []
        for (src_t, tgt_t), group in groups.items():
            pk = pk_set.get(tgt_t.lower(), set())
            if len(pk) <= 1:
                # 단일(또는 0) 멤버 PK: 각 후보 독립 full-cover → 그대로 통과
                result.extend(group)
                continue
            # 복합 PK: 멤버별 cover pair 수집(원본 casing 보존). 같은 PK 멤버를
            # 두 source 컬럼이 cover 하면(v2 cross-name 에서 가능, v1 same-name 에선
            # 컬럼명당 1 pair 라 불가) first-wins — silent overwrite 로 잘못된 ON
            # 절을 합성하지 않도록 명시 처리한다.
            member_to_pair: Dict[str, Tuple[str, str]] = {}
            for c in group:
                for src_c, tgt_c in c.column_pairs:
                    key = tgt_c.lower()
                    if key not in pk:
                        continue
                    if key in member_to_pair:
                        logger.debug(
                            "G5: PK member %s already covered by %s; ignoring %s",
                            tgt_c,
                            member_to_pair[key][0],
                            src_c,
                        )
                        continue
                    member_to_pair[key] = (src_c, tgt_c)
            if set(member_to_pair.keys()) >= pk:
                pairs = [member_to_pair[m] for m in sorted(pk)]
                result.append(
                    InferredJoin(
                        source_table=src_t,
                        target_table=tgt_t,
                        column_pairs=pairs,
                        confidence="candidate",
                        reason=f"composite PK cover ({len(pk)} cols)",
                    )
                )
            # partial cover → 전체 reject(아무것도 추가 안 함)
        return result

    @staticmethod
    def _gate_double_target(
        candidates: List[InferredJoin], pk_set: Dict[str, set]
    ) -> List[InferredJoin]:
        """G4: 한 source 컬럼(집합)이 여러 target 을 가리키면 PK-target 1개만 남긴다.

        double-targeting 모호성을 제거한다 — PK-target 을 우선하고(SALES.ITEM_CODE
        → ITEM_MASTER(PK) vs MATR_MASTER(속성) 중 ITEM_MASTER), 동률이면 target
        이름으로 결정론적 tie-break. 복원 코드의 ``seen`` dedup set 을 재사용해
        (source_t, source 컬럼집합) 별 첫 항목만 유지한다. source 컬럼이 다르거나
        source 테이블이 다르면(star: 여러 fact → 한 dim) dedup 대상이 아니다.
        """

        def _is_pk_target(c: InferredJoin) -> bool:
            keys = pk_set.get(c.target_table.lower())
            if not keys:
                return False
            return all(tgt.lower() in keys for _, tgt in c.column_pairs)

        # PK-target 우선 → target 이름 순(결정론적 tie-break)
        ordered = sorted(
            candidates,
            key=lambda c: (not _is_pk_target(c), c.target_table.lower()),
        )
        seen: set = set()
        kept: List[InferredJoin] = []
        for c in ordered:
            key = (
                c.source_table.lower(),
                tuple(sorted(src.lower() for src, _ in c.column_pairs)),
            )
            if key in seen:
                continue
            seen.add(key)
            kept.append(c)
        return kept

    async def _collect_verified_fks(
        self,
        table_names: List[str],
        extracted_set: set,
    ) -> Dict[str, Dict[str, Any]]:
        """Collect verified FK relationships over the given table set.

        Per-table introspection (``validate_sql_identifier`` +
        ``get_foreign_key_relationships``) grouped by CONSTRAINT_NAME so composite
        keys render as one join. Only edges whose BOTH endpoints are in
        ``extracted_set`` are kept (a relation to a non-extracted table = the user
        chose not to see it). Constraint-name-less dialects get a synthetic key
        per column-pair. Returns ``{cname: {"source", "target", "pairs"}}``.

        Per-table loop (not bulk ``None``) is deliberate: ``schema_name`` is
        allow-listed once in ``SqlRunnerBase.__init__``, ``table_name`` is
        validated here, and per-engine bulk-FK directionality is unverified —
        correctness over the bulk optimization.
        """
        constraints: Dict[str, Dict[str, Any]] = {}
        fallback_idx = 0
        for table_name in table_names:
            try:
                validate_sql_identifier(table_name, kind="table")
                fks = await self.sql_runner.get_foreign_key_relationships(table_name)
            except Exception as e:
                logger.debug(f"No FK info for {table_name}: {e}")
                continue
            for fk in fks:
                source = fk.get("source_table") or fk.get("SOURCE_TABLE", "")
                source_col = fk.get("source_column") or fk.get("SOURCE_COLUMN", "")
                target = fk.get("target_table") or fk.get("TARGET_TABLE", "")
                target_col = fk.get("target_column") or fk.get("TARGET_COLUMN", "")
                if not (source and source_col and target and target_col):
                    continue
                if (
                    source.lower() not in extracted_set
                    or target.lower() not in extracted_set
                ):
                    continue
                cname = fk.get("constraint_name") or fk.get("CONSTRAINT_NAME")
                if not cname:
                    cname = f"_fk{fallback_idx}_{source}_{target}"
                    fallback_idx += 1
                # Key by (source, cname): MySQL FK CONSTRAINT_NAME is unique only
                # PER-TABLE, so two unrelated source tables can share e.g. "fk_1" —
                # keying by bare cname would merge them into one corrupted edge, and
                # the full-S recompute makes that collision fire across the whole
                # schema every run. Composite FKs share both source + cname so they
                # still group correctly.
                entry = constraints.setdefault(
                    (source.lower(), cname),
                    {"source": source, "target": target, "cname": cname, "pairs": []},
                )
                pair = (source_col, target_col)
                if pair not in entry["pairs"]:
                    entry["pairs"].append(pair)
        return constraints

    async def _recompute_join_graph(
        self,
        memory,
        batch_table_details: Optional[List[TableDetails]] = None,
    ) -> Dict[str, Any]:
        """Full-S recompute of the always-inject join_graph (Option C).

        Invariant: ``join_graph`` is a pure function of the CURRENT full
        extraction set S. We reload the entire DDL_SCHEMA set, merge the
        just-extracted batch (fresh wins), then recompute verified FK + inferred
        joins over S — so a partial re-extract never drops the relationships of
        previously-extracted tables.

        Runs inside the caller's ``memory.session()``. Returns the rendered
        ``join_graph`` string (both tiers; the inferred gate is applied at inject
        time), ``full_table_details`` (for schema_summary/table_overview recompute
        by the persistence layer over the same full S), and a ``truncated`` flag.
        No DOCUMENTATION doc is saved — relationships now live in
        ``dbsphere.data["join_graph"]``.

        FK introspection uses the shared ``self.sql_runner`` (alive after the
        gather); inference is pure over ``table_details`` — both safe w.r.t. the
        PR3 per-task-runner lifecycle.
        """
        ddl_memories = await memory.get_table_schemas(None)
        truncated = len(ddl_memories) >= DDL_SCHEMA_FETCH_LIMIT
        reloaded = reconstruct_table_details(ddl_memories)
        full_details = merge_batch_fresh(reloaded, list(batch_table_details or []))
        full_names = [td.table_name for td in full_details]
        extracted_set = {n.lower() for n in full_names}

        constraints = await self._collect_verified_fks(full_names, extracted_set)

        inferred = await self._infer_column_semantics(full_details)
        inferred = [
            j
            for j in inferred
            if j.source_table.lower() in extracted_set
            and j.target_table.lower() in extracted_set
        ]

        rows = normalize_relationships(constraints, inferred)
        join_graph = build_join_graph(rows)

        # E1: purge the legacy fixed-id relationship DOCUMENTATION doc (pre-Option
        # -C). It would otherwise double-surface via similarity retrieval until the
        # dbsphere is re-extracted. Idempotent; random-id orphans are handled by the
        # E2 retrieve-stage filter.
        try:
            await memory.delete_relationship_graph_doc()
        except Exception as e:
            logger.debug("Legacy relationship doc purge skipped: %s", e)

        logger.info(
            "Recomputed join_graph over full S (%d tables): %d verified FK "
            "constraint(s), %d inferred candidate(s)%s",
            len(full_names),
            len(constraints),
            len(inferred),
            " [TRUNCATED]" if truncated else "",
        )
        return {
            "join_graph": join_graph,
            "full_table_details": full_details,
            "truncated": truncated,
        }

    @staticmethod
    def generate_table_overview(
        table_details_list: List[TableDetails],
    ) -> str:
        """Generate a lightweight table-level overview (no column details).

        Used for run_sql tool description so the LLM knows what tables
        are available without overwhelming the prompt with column details.

        Args:
            table_details_list: List of extracted table details

        Returns:
            Brief overview string, one line per table
        """
        if not table_details_list:
            return ""

        lines = []
        for td in table_details_list:
            desc = td.description or "No description"
            lines.append(f"- {td.table_name}: {desc}")

        return "\n".join(lines)

    async def generate_schema_summary(
        self,
        table_details_list: List[TableDetails],
    ) -> Optional[str]:
        """Generate a concise database summary from extracted table details."""
        if not self._has_llm() or not table_details_list:
            return None

        lines = []
        for td in table_details_list:
            table_line = f"### {td.table_name}"
            if td.description:
                table_line += f"\n설명: {td.description}"

            col_parts = []
            for col in td.columns:
                part = f"{col.name} ({col.data_type})"
                if col.is_primary_key:
                    part += " [PK]"
                if col.is_foreign_key and col.foreign_table:
                    part += f" [FK → {col.foreign_table}]"
                if col.description:
                    part += f" — {col.description}"
                col_parts.append(part)

            table_line += "\n컬럼: " + ", ".join(col_parts)

            if td.related_tables:
                table_line += f"\n관련 테이블: {', '.join(td.related_tables)}"

            lines.append(table_line)

        tables_info = "\n\n".join(lines)
        prompt = SCHEMA_SUMMARY_PROMPT.format(tables_info=tables_info)

        try:
            # Markdown output — must NOT use json_object response format.
            summary = await self._call_llm(prompt, json_mode=False)
            return summary.strip() if summary else None
        except Exception as e:
            logger.error(f"Failed to generate schema summary: {e}")
            return None


def create_schema_extractor_with_config(
    sql_runner: SqlRunnerBase,
    model_config: Optional[Dict[str, Any]] = None,
    sample_row_count: int = 5,
) -> SchemaExtractor:
    """
    Factory function to create a SchemaExtractor with model config.

    Args:
        sql_runner: SQL runner for database operations
        model_config: LLM configuration from get_model_config_from_app()
        sample_row_count: Number of sample rows per table

    Returns:
        Configured SchemaExtractor instance

    Example:
        >>> from extension_modules.utils.llm import get_model_config_from_app
        >>> model_config = get_model_config_from_app(request.app, "gpt-4o")
        >>> extractor = create_schema_extractor_with_config(
        ...     sql_runner=sql_runner,
        ...     model_config=model_config,
        ...     sample_row_count=5,
        ... )
    """
    return SchemaExtractor(
        sql_runner=sql_runner,
        model_config=model_config,
        sample_row_count=sample_row_count,
    )


# Backward compatibility: keep the old factory function
async def create_schema_extractor(
    sql_runner: SqlRunnerBase,
    model_id: str,
    app,
    sample_row_count: int = 5,
) -> SchemaExtractor:
    """
    [DEPRECATED] Factory function to create a SchemaExtractor with LLM integration.

    Use create_schema_extractor_with_config() instead.

    Args:
        sql_runner: SQL runner for database operations
        model_id: LLM model ID to use for extraction
        app: FastAPI application instance (for accessing LLM services)
        sample_row_count: Number of sample rows per table

    Returns:
        Configured SchemaExtractor instance
    """
    from extension_modules.utils.llm import get_model_config_from_app

    model_config = get_model_config_from_app(app, model_id)

    return SchemaExtractor(
        sql_runner=sql_runner,
        model_config=model_config,
        sample_row_count=sample_row_count,
    )
