"""Unit tests for the join_graph full-S recompute infra (Option C).

Phase B (this file, growing):
- B1: ``get_table_schemas`` fetch cap raised 100→1000 + silent-truncation warning.
- B1b: DDL_SCHEMA → DDLMemory reconstruction preserves ``is_primary_key`` (the
  substrate the full-S recompute + inference depend on).

전략: search engine 을 최소 fake 로 치환(DB·실엔진 불요) — relationship-graph
테스트의 fake 패턴과 동일 철학.
"""

from __future__ import annotations

import json
import logging

from extension_modules.dbsphere.memory.models import (
    ColumnDetail,
    DDLMemory,
    InferredJoin,
    TableDetails,
)
from extension_modules.dbsphere.memory.schema_extractor import (
    REL_INFERRED_NAME,
    REL_VERIFIED_FK,
    SchemaExtractor,
    build_join_graph,
    merge_batch_fresh,
    normalize_relationships,
    reconstruct_table_details,
)
from extension_modules.dbsphere.memory.search_memory import (
    DDL_SCHEMA_FETCH_LIMIT,
    SearchEngineDbSphereMemory,
)
from extension_modules.dbsphere.prompts import (
    _strip_inferred_from_join_graph,
    get_dbsphere_system_prompt,
)
from extension_modules.dbsphere.tools.dbsphere_info import (
    _build_dbsphere_info_content,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeDoc:
    def __init__(self, doc_id, metadata):
        self.id = doc_id
        self.metadata = metadata


class _FakeEngine:
    """Minimal search-engine double exercising the get_table_schemas filter path."""

    def __init__(self, docs, captured=None):
        self._docs = docs
        self.captured = captured if captured is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def index_exists(self):
        return True

    async def filter_by_metadata(self, filter_expr, limit):
        self.captured["filter_expr"] = filter_expr
        self.captured["limit"] = limit
        return self._docs[:limit]


def _ddl_doc(table, columns):
    return _FakeDoc(
        doc_id=f"ds-test__ddl__{table}",
        metadata={
            "table_name": table,
            "column_info_json": json.dumps(columns),
            "ddl_statement": f"CREATE TABLE {table} (...)",
            "schema_name": "public",
            "table_description": f"{table} description",
            "created_at": "2026-06-06T00:00:00Z",
        },
    )


def _mem(docs, captured=None):
    mem = SearchEngineDbSphereMemory(app=None, dbsphere_id="ds-test")
    # Inject the fake engine directly, bypassing get_configured_search_engine.
    mem._engine = _FakeEngine(docs, captured)
    return mem


# ---------------------------------------------------------------------------
# B1 — fetch cap + truncation visibility
# ---------------------------------------------------------------------------
async def test_fetch_cap_is_1000():
    captured = {}
    mem = _mem([_ddl_doc("orders", [{"name": "id", "data_type": "int"}])], captured)
    await mem.get_table_schemas(None)
    assert captured["limit"] == DDL_SCHEMA_FETCH_LIMIT == 1000


async def test_reconstruction_preserves_is_primary_key():
    cols = [
        {"name": "id", "data_type": "int", "is_primary_key": True},
        {"name": "name", "data_type": "text", "is_primary_key": False},
    ]
    mem = _mem([_ddl_doc("orders", cols)])
    out = await mem.get_table_schemas(None)
    assert len(out) == 1
    assert out[0].table_name == "orders"
    pk = {c.name: c.is_primary_key for c in out[0].columns}
    assert pk == {"id": True, "name": False}


async def test_truncation_warns_at_cap(caplog):
    docs = [
        _ddl_doc(f"t{i}", [{"name": "id", "data_type": "int"}])
        for i in range(DDL_SCHEMA_FETCH_LIMIT)
    ]
    mem = _mem(docs)
    with caplog.at_level(logging.WARNING):
        out = await mem.get_table_schemas(None)
    assert len(out) == DDL_SCHEMA_FETCH_LIMIT
    assert any("fetch cap" in r.getMessage() for r in caplog.records)


async def test_no_truncation_warn_below_cap(caplog):
    docs = [_ddl_doc(f"t{i}", [{"name": "id", "data_type": "int"}]) for i in range(3)]
    mem = _mem(docs)
    with caplog.at_level(logging.WARNING):
        await mem.get_table_schemas(None)
    assert not any("fetch cap" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# B2 — DDLMemory → TableDetails reconstruction (is_primary_key preserved)
# ---------------------------------------------------------------------------
def test_reconstruct_preserves_pk_and_fields():
    cols = [
        ColumnDetail(name="id", data_type="int", is_primary_key=True),
        ColumnDetail(name="cust", data_type="int", is_primary_key=False),
    ]
    mem = DDLMemory(
        memory_id="m1",
        ddl_statement="CREATE TABLE orders (...)",
        table_name="orders",
        table_description="orders table",
        columns=cols,
        relationships=["customers"],
    )
    out = reconstruct_table_details([mem])
    assert len(out) == 1
    td = out[0]
    assert td.table_name == "orders"
    assert td.ddl == "CREATE TABLE orders (...)"
    assert td.description == "orders table"
    assert td.related_tables == ["customers"]
    assert [(c.name, c.is_primary_key) for c in td.columns] == [
        ("id", True),
        ("cust", False),
    ]


def test_reconstruct_skips_blank_table_name():
    mem = DDLMemory(memory_id="m", ddl_statement="", table_name="")
    assert reconstruct_table_details([mem]) == []


# ---------------------------------------------------------------------------
# B3 — batch fresh merge
# ---------------------------------------------------------------------------
def _td(name, desc):
    return TableDetails(table_name=name, ddl="", description=desc, columns=[])


def test_merge_batch_wins_on_overlap():
    reloaded = [_td("orders", "stale"), _td("customers", "c")]
    batch = [_td("orders", "fresh")]
    out = {td.table_name: td.description for td in merge_batch_fresh(reloaded, batch)}
    assert out == {"orders": "fresh", "customers": "c"}


def test_merge_case_insensitive_union():
    reloaded = [_td("Orders", "stale")]
    batch = [_td("orders", "fresh"), _td("items", "i")]
    out = merge_batch_fresh(reloaded, batch)
    assert len(out) == 2  # Orders/orders collapse, items added
    descs = {td.description for td in out}
    assert "fresh" in descs and "i" in descs and "stale" not in descs


# ---------------------------------------------------------------------------
# C1 — normalize_relationships
# ---------------------------------------------------------------------------
def _constraint(source, target, pairs, cname):
    return {
        (source.lower(), cname): {
            "source": source,
            "target": target,
            "cname": cname,
            "pairs": list(pairs),
        }
    }


def test_normalize_single_verified():
    rows = normalize_relationships(
        _constraint("sales", "customers", [("customer_id", "id")], "fk1"), []
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["relationship_type"] == REL_VERIFIED_FK
    assert r["source_columns"] == ["customer_id"] and r["target_columns"] == ["id"]
    assert r["confidence"] == 1.0 and r["evidence"] == ["fk1"]


def test_normalize_composite_clean_one_row():
    rows = normalize_relationships(
        _constraint("s", "t", [("a", "x"), ("b", "y")], "fk_comp"), []
    )
    assert len(rows) == 1
    assert rows[0]["source_columns"] == ["a", "b"]
    assert rows[0]["target_columns"] == ["x", "y"]


def test_normalize_cartesian_split():
    # 2 src × 2 tgt = 4 pairs (N×N cartesian) → split into 4 single-col rows.
    pairs = [("a", "x"), ("a", "y"), ("b", "x"), ("b", "y")]
    rows = normalize_relationships(_constraint("s", "t", pairs, "fk_cart"), [])
    assert len(rows) == 4
    assert all(len(r["source_columns"]) == 1 for r in rows)


def test_normalize_inferred():
    j = InferredJoin(
        source_table="sales",
        target_table="matr",
        column_pairs=[("matr_code", "matr_code")],
        reason="same-name column 'matr_code'",
    )
    rows = normalize_relationships({}, [j])
    assert len(rows) == 1
    r = rows[0]
    assert r["relationship_type"] == REL_INFERRED_NAME
    assert r["confidence"] == 0.5
    assert r["evidence"] == ["same-name column 'matr_code'"]


# ---------------------------------------------------------------------------
# C1 — build_join_graph (compact, no cardinality, forward-compat)
# ---------------------------------------------------------------------------
def _vrow(s, scols, t, tcols):
    return {
        "source_table": s,
        "source_columns": scols,
        "target_table": t,
        "target_columns": tcols,
        "relationship_type": REL_VERIFIED_FK,
        "confidence": 1.0,
        "evidence": ["fk"],
    }


def _irow(s, scols, t, tcols):
    return {
        "source_table": s,
        "source_columns": scols,
        "target_table": t,
        "target_columns": tcols,
        "relationship_type": REL_INFERRED_NAME,
        "confidence": 0.5,
        "evidence": ["r"],
    }


def test_build_empty_returns_empty_string():
    assert build_join_graph([]) == ""


def test_build_verified_only():
    g = build_join_graph([_vrow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["ID"])])
    assert "## JOIN Graph" in g
    assert "### Verified (foreign keys)" in g
    assert "- SALES → CUSTOMERS  ON SALES.CUSTOMER_ID = CUSTOMERS.ID" in g
    assert "Inferred" not in g


def test_build_composite_on_and_join():
    g = build_join_graph([_vrow("S", ["a", "b"], "T", ["x", "y"])])
    assert "ON S.a = T.x AND S.b = T.y" in g


def test_build_inferred_candidate_label():
    g = build_join_graph([_irow("SALES", ["MATR_CODE"], "MATR", ["MATR_CODE"])])
    assert "### Inferred (structural candidates — not verified FK)" in g
    assert "- SALES → MATR (candidate)  ON SALES.MATR_CODE = MATR.MATR_CODE" in g


def test_build_inject_inferred_false_drops_inferred():
    rows = [_vrow("S", ["a"], "T", ["x"]), _irow("S", ["b"], "U", ["y"])]
    g = build_join_graph(rows, inject_inferred=False)
    assert "Verified" in g
    assert "Inferred" not in g and "(candidate)" not in g


def test_build_no_cardinality_token():
    rows = [_vrow("S", ["a"], "T", ["x"]), _irow("S", ["b"], "U", ["y"])]
    g = build_join_graph(rows)
    for token in ("M:1", "1:M", "many_to_one", "one_to_many", "cardinality"):
        assert token not in g


def test_build_inferred_only_when_no_verified():
    g = build_join_graph([_irow("S", ["a"], "T", ["x"])])
    assert "Verified" not in g
    assert "(candidate)" in g


def test_build_dedups_inferred_matching_verified():
    # An inferred candidate that merely restates a verified FK (same column
    # equalities) is redundant: the verified tier already asserts it, and echoing
    # it under "not verified FK" is self-contradictory + wastes always-inject
    # tokens. Drop the dup; keep genuine non-FK candidates.
    rows = [
        _vrow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["CUSTOMER_ID"]),
        _irow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["CUSTOMER_ID"]),  # dup of FK
        _irow("SALES", ["MATR_CODE"], "MATR", ["MATR_CODE"]),  # genuine non-FK
    ]
    g = build_join_graph(rows)
    assert "- SALES → CUSTOMERS  ON SALES.CUSTOMER_ID = CUSTOMERS.CUSTOMER_ID" in g
    assert "SALES → CUSTOMERS (candidate)" not in g  # dup suppressed
    assert "- SALES → MATR (candidate)  ON SALES.MATR_CODE = MATR.MATR_CODE" in g


def test_build_dedups_inferred_reverse_direction():
    # A→B FK and inferred B→A on the same columns describe the same join
    # (equality is symmetric) — dedup is direction-agnostic.
    rows = [
        _vrow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["CUSTOMER_ID"]),
        _irow("CUSTOMERS", ["CUSTOMER_ID"], "SALES", ["CUSTOMER_ID"]),
    ]
    g = build_join_graph(rows)
    assert "(candidate)" not in g


def test_build_dedup_drops_inferred_section_when_all_dup():
    # If every inferred row duplicates a verified FK, the Inferred section must
    # vanish entirely (no empty header).
    rows = [
        _vrow("S", ["a"], "T", ["x"]),
        _irow("S", ["a"], "T", ["x"]),
    ]
    g = build_join_graph(rows)
    assert "### Inferred" not in g
    assert "(candidate)" not in g


# ---------------------------------------------------------------------------
# C2/C3 — _recompute_join_graph orchestrator (full-S, no DOCUMENTATION save)
# ---------------------------------------------------------------------------
def _ddlmem(table, cols=None):
    return DDLMemory(
        memory_id=f"ds__{table}",
        ddl_statement=f"CREATE {table}",
        table_name=table,
        columns=list(cols or []),
    )


def _fkrow(src, src_col, tgt, tgt_col, cname):
    return {
        "SOURCE_TABLE": src,
        "SOURCE_COLUMN": src_col,
        "TARGET_TABLE": tgt,
        "TARGET_COLUMN": tgt_col,
        "CONSTRAINT_NAME": cname,
    }


class _FakeRunner:
    def __init__(self, fks=None):
        self._fks = fks or []

    async def get_foreign_key_relationships(self, table_name=None):
        if table_name is None:
            return list(self._fks)
        return [fk for fk in self._fks if fk.get("SOURCE_TABLE") == table_name]


class _FakeMemory:
    def __init__(self, dbsphere_id="ds-test", ddl=None):
        self.dbsphere_id = dbsphere_id
        self._ddl = list(ddl or [])
        self.saved_docs = []  # orchestrator must never save a DOCUMENTATION doc
        self.purged = False

    async def get_table_schemas(self, table_names=None):
        return list(self._ddl)

    async def save_documentation(self, **kw):
        self.saved_docs.append(kw)

    async def delete_relationship_graph_doc(self):
        self.purged = True
        return True


def _extractor(fks=None):
    return SchemaExtractor(sql_runner=_FakeRunner(fks=fks or []))


async def test_recompute_verified_edge_and_no_doc_save():
    ext = _extractor([_fkrow("T_ORDER", "CUST_ID", "T_CUST", "ID", "FK1")])
    mem = _FakeMemory(ddl=[_ddlmem("T_ORDER"), _ddlmem("T_CUST")])
    out = await ext._recompute_join_graph(mem, [])
    g = out["join_graph"]
    assert "### Verified (foreign keys)" in g
    assert "- T_ORDER → T_CUST  ON T_ORDER.CUST_ID = T_CUST.ID" in g
    assert mem.saved_docs == []  # Option C: relationship lives in data, not a doc
    assert out["truncated"] is False
    assert {td.table_name for td in out["full_table_details"]} == {"T_ORDER", "T_CUST"}


async def test_recompute_empty_when_no_relationship():
    ext = _extractor([])
    mem = _FakeMemory(ddl=[_ddlmem("T_X"), _ddlmem("T_Y")])
    out = await ext._recompute_join_graph(mem, [])
    assert out["join_graph"] == ""  # no FK + no PK signal → no inferred


async def test_recompute_composite_single_on():
    fks = [
        _fkrow("T_L", "PLANT", "T_H", "PLANT", "FKC"),
        _fkrow("T_L", "ORD_NO", "T_H", "ORD_NO", "FKC"),
    ]
    ext = _extractor(fks)
    mem = _FakeMemory(ddl=[_ddlmem("T_L"), _ddlmem("T_H")])
    g = (await ext._recompute_join_graph(mem, []))["join_graph"]
    assert "ON T_L.PLANT = T_H.PLANT AND T_L.ORD_NO = T_H.ORD_NO" in g


async def test_recompute_mysql_per_table_constraint_name_collision():
    # MySQL FK CONSTRAINT_NAME is unique per-table, so two unrelated source tables
    # can both own "fk_1". They must NOT merge into one corrupted edge (keying by
    # bare cname did exactly that; the full-S recompute fires it across the schema).
    fks = [
        _fkrow("ORDERS", "CUST_ID", "CUSTOMERS", "ID", "fk_1"),
        _fkrow("ITEMS", "CAT_ID", "CATEGORIES", "ID", "fk_1"),
    ]
    ext = _extractor(fks)
    mem = _FakeMemory(
        ddl=[
            _ddlmem("ORDERS"),
            _ddlmem("CUSTOMERS"),
            _ddlmem("ITEMS"),
            _ddlmem("CATEGORIES"),
        ]
    )
    g = (await ext._recompute_join_graph(mem, []))["join_graph"]
    assert "- ORDERS → CUSTOMERS  ON ORDERS.CUST_ID = CUSTOMERS.ID" in g
    assert "- ITEMS → CATEGORIES  ON ITEMS.CAT_ID = CATEGORIES.ID" in g


async def test_recompute_cartesian_fk_splits_to_per_pair():
    # postgres information_schema returns a composite FK as an N×N cartesian
    # (2 src × 2 tgt = 4 pairs); the invariant break must render per-pair single-
    # column edges, not one over-ANDed ON (migrated from the old doc test).
    fks = [
        _fkrow("T_L", "PLANT", "T_H", "PLANT", "FKC"),
        _fkrow("T_L", "PLANT", "T_H", "ORD", "FKC"),
        _fkrow("T_L", "ORD", "T_H", "PLANT", "FKC"),
        _fkrow("T_L", "ORD", "T_H", "ORD", "FKC"),
    ]
    ext = _extractor(fks)
    mem = _FakeMemory(ddl=[_ddlmem("T_L"), _ddlmem("T_H")])
    g = (await ext._recompute_join_graph(mem, []))["join_graph"]
    edges = [ln for ln in g.splitlines() if ln.startswith("- T_L → T_H")]
    assert len(edges) == 4
    assert all(" AND " not in ln for ln in edges)


async def test_recompute_drops_edge_to_non_extracted():
    ext = _extractor([_fkrow("T_ORDER", "CUST_ID", "T_GHOST", "ID", "FK1")])
    mem = _FakeMemory(ddl=[_ddlmem("T_ORDER")])  # T_GHOST not in S
    g = (await ext._recompute_join_graph(mem, []))["join_graph"]
    assert g == ""  # both-endpoints∈S fails → edge dropped


async def test_recompute_merges_batch_over_reload():
    # reload has T_A only; the batch contributes a fresh T_B → full S = {T_A, T_B}
    ext = _extractor([_fkrow("T_A", "B_ID", "T_B", "ID", "FK1")])
    mem = _FakeMemory(ddl=[_ddlmem("T_A")])
    batch = [TableDetails(table_name="T_B", ddl="", description="b", columns=[])]
    g = (await ext._recompute_join_graph(mem, batch))["join_graph"]
    assert "- T_A → T_B  ON T_A.B_ID = T_B.ID" in g


async def test_recompute_renders_inferred(monkeypatch):
    ext = _extractor([])
    mem = _FakeMemory(ddl=[_ddlmem("SALES"), _ddlmem("MATR")])

    async def fake_infer(self, details):
        return [
            InferredJoin(
                source_table="SALES",
                target_table="MATR",
                column_pairs=[("matr_code", "matr_code")],
                reason="same-name column 'matr_code'",
            )
        ]

    monkeypatch.setattr(SchemaExtractor, "_infer_column_semantics", fake_infer)
    g = (await ext._recompute_join_graph(mem, []))["join_graph"]
    assert "### Inferred (structural candidates — not verified FK)" in g
    assert "- SALES → MATR (candidate)  ON SALES.matr_code = MATR.matr_code" in g


# ---------------------------------------------------------------------------
# D1 — always-inject join_graph prompt slot + inject_inferred gate
# ---------------------------------------------------------------------------
_PG_VERIFIED = "## JOIN Graph\n\n### Verified (foreign keys)\n- A → B  ON A.x = B.y"
_PG_BOTH = (
    _PG_VERIFIED
    + "\n\n### Inferred (structural candidates — not verified FK)\n"
    + "- A → C (candidate)  ON A.z = C.z"
)
_PG_INFERRED_ONLY = (
    "## JOIN Graph\n\n### Inferred (structural candidates — not verified FK)\n"
    "- A → C (candidate)  ON A.z = C.z"
)


def test_prompt_injects_join_graph():
    p = get_dbsphere_system_prompt(
        dialect="PostgreSQL", schema_ddl="CREATE TABLE a();", join_graph=_PG_BOTH
    )
    assert "## JOIN Graph" in p
    assert "### Verified (foreign keys)" in p
    assert "- A → B  ON A.x = B.y" in p
    assert "### Inferred (structural candidates" in p
    assert "(candidate)" in p


def test_prompt_no_join_graph_section_when_empty():
    p = get_dbsphere_system_prompt(dialect="PostgreSQL", schema_ddl="x", join_graph="")
    assert "## JOIN Graph" not in p


def test_prompt_inject_inferred_off_strips_inferred():
    p = get_dbsphere_system_prompt(
        dialect="PostgreSQL", schema_ddl="x", join_graph=_PG_BOTH, inject_inferred=False
    )
    assert "### Verified (foreign keys)" in p
    assert "- A → B  ON A.x = B.y" in p
    assert "### Inferred" not in p
    assert "(candidate)" not in p


def test_prompt_inject_inferred_off_inferred_only_drops_graph():
    p = get_dbsphere_system_prompt(
        dialect="PostgreSQL",
        schema_ddl="x",
        join_graph=_PG_INFERRED_ONLY,
        inject_inferred=False,
    )
    assert "## JOIN Graph" not in p


def test_strip_helper_noop_without_inferred():
    assert _strip_inferred_from_join_graph(_PG_VERIFIED) == _PG_VERIFIED


# ---------------------------------------------------------------------------
# D2 — dbsphere_info (UnifiedAgent Stage-1) surfaces join_graph from data
# ---------------------------------------------------------------------------
def test_dbsphere_info_exposes_join_graph():
    content = _build_dbsphere_info_content(
        "PostgreSQL", {"table_overview": "- a: x", "join_graph": _PG_BOTH}
    )
    assert "## Available Tables" in content
    assert "## JOIN Graph" in content
    assert "### Verified (foreign keys)" in content
    assert "(candidate)" in content


def test_dbsphere_info_join_graph_inject_inferred_off():
    content = _build_dbsphere_info_content(
        "PostgreSQL", {"join_graph": _PG_BOTH, "inject_inferred": False}
    )
    assert "### Verified (foreign keys)" in content
    assert "### Inferred" not in content


def test_dbsphere_info_empty_data():
    content = _build_dbsphere_info_content("PostgreSQL", {})
    assert "No table information available." in content


def test_dbsphere_info_join_graph_only_counts_as_info():
    content = _build_dbsphere_info_content("PostgreSQL", {"join_graph": _PG_VERIFIED})
    assert "No table information available." not in content
    assert "## JOIN Graph" in content


# ---------------------------------------------------------------------------
# E1 — orchestrator purges the legacy fixed-id relationship doc
# ---------------------------------------------------------------------------
async def test_recompute_purges_legacy_doc():
    ext = _extractor([_fkrow("A", "x", "B", "y", "FK1")])
    mem = _FakeMemory(ddl=[_ddlmem("A"), _ddlmem("B")])
    await ext._recompute_join_graph(mem, [])
    assert mem.purged is True  # E1: legacy fixed-id doc purge attempted


# ---------------------------------------------------------------------------
# E2 — search_documentation excludes the legacy relationship doc (post-fetch)
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, result_id, score, content="", metadata=None):
        self.id = result_id
        self.score = score
        self.content = content
        self.metadata = metadata or {}


class _FakeDocEngine:
    def __init__(self, results):
        self._results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def index_exists(self):
        return True

    async def hybrid_search(self, text, vector, top_k, filter_expr):
        return self._results


async def test_search_documentation_excludes_legacy_by_id_suffix():
    mem = SearchEngineDbSphereMemory(app=None, dbsphere_id="ds1")
    rel = _FakeResult(
        "ds1__relationship_graph",
        0.9,
        content="rel graph",
        metadata={"title": "Database Table Relationships and JOIN Guide"},
    )
    biz = _FakeResult("doc-1", 0.9, content="biz", metadata={"doc_type": "rule"})
    mem._engine = _FakeDocEngine([rel, biz])
    out = await mem.search_documentation("q", question_vector=[0.0] * 8)
    ids = [r.memory.memory_id for r in out]
    assert "ds1__relationship_graph" not in ids
    assert "doc-1" in ids


async def test_search_documentation_excludes_random_id_orphan_by_title():
    mem = SearchEngineDbSphereMemory(app=None, dbsphere_id="ds1")
    orphan = _FakeResult(
        "uuid-random-123",
        0.9,
        content="rel graph",
        metadata={"title": "Database Table Relationships and JOIN Guide"},
    )
    mem._engine = _FakeDocEngine([orphan])
    out = await mem.search_documentation("q", question_vector=[0.0] * 8)
    assert out == []  # title match catches the PR#219-era random-id orphan
