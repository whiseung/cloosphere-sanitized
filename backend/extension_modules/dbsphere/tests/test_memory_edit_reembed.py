"""Unit tests for DbSphere DDL memory edit re-embedding (ddl_schema only).

Covers:
- `render_ddl_memory` extraction — byte-identical to the legacy inline builder
  (save_ddl_memory L689-716), incl. a description-less column AND relationships
  (content uses ", "/"Related tables:" while embedding uses " "/"Related:").
- `update_memory` ddl_schema branch: re-embed on description/column edits,
  field-level column merge that preserves FE-dropped structural fields
  (foreign_column / is_nullable / default_value), `_safe_json` guards against
  relationships_json=None, and embed-attempted fail-closed scoped to ddl only.

Tooling: an INPUT-SENSITIVE fake embedder (constant embedders make "vector
changed" asserts vacuous) with a call counter + captured-text list.

Run (from repo root — conftest uses root-relative alembic paths):
`uv run pytest backend/extension_modules/dbsphere/tests/test_memory_edit_reembed.py`
"""

import contextlib
import json
import logging

from extension_modules.dbsphere.memory.models import ColumnDetail, MemoryType
from extension_modules.dbsphere.memory.search_memory import (
    SearchEngineDbSphereMemory,
    _safe_json,
    merge_columns_by_name,
    render_ddl_memory,
)
from extension_modules.search_engine import DocumentItem

# Full-fidelity columns as save_ddl_memory persists them (all ColumnDetail
# fields). `note` has no description (exercises the bare-name embedding branch);
# customer_id/qty carry the structural fields the FE edit payload drops.
_FULL_COLUMNS = [
    ColumnDetail(
        name="id",
        data_type="INT",
        description="primary id",
        is_primary_key=True,
        is_nullable=False,
    ),
    ColumnDetail(
        name="customer_id",
        data_type="INT",
        description="fk customer",
        is_foreign_key=True,
        foreign_table="customer",
        foreign_column="id",
        is_nullable=False,
    ),
    ColumnDetail(
        name="qty",
        data_type="INT",
        description="quantity",
        is_nullable=False,
        default_value="0",
    ),
    ColumnDetail(name="note", data_type="TEXT"),  # description-less
]


# --- fake engine + input-sensitive embedder ----------------------------------
class _FakeEngine:
    def __init__(self):
        self.store = {}
        self.embed_calls = 0
        self.captured = []
        self.update_calls = 0
        self.insert_calls = 0

    async def index_exists(self):
        return True

    async def get(self, ids):
        return [self.store[i] for i in ids if i in self.store]

    async def update(self, docs):
        for d in docs:
            self.store[d.id] = d
        self.update_calls += 1
        return len(docs)

    async def insert(self, docs):
        for d in docs:
            self.store[d.id] = d
        self.insert_calls += 1
        return len(docs)

    async def filter_by_metadata(self, filter_expr=None, limit=None):
        docs = [
            d
            for d in self.store.values()
            if (d.metadata or {}).get("entity_type") == MemoryType.DDL_SCHEMA.value
        ]
        return docs[:limit] if limit else docs


def _make_memory(engine, *, user_id="userB"):
    mem = SearchEngineDbSphereMemory(app=None, dbsphere_id="db1", user_id=user_id)
    mem._get_engine = lambda: engine

    @contextlib.asynccontextmanager
    async def _ctx(_e):
        yield engine

    mem._engine_ctx = _ctx

    async def _ensure(_e):
        return True

    mem._ensure_index_exists = _ensure

    async def _embed(text):
        # Content-sensitive: different text -> different vector (len guards the
        # rare ord-sum collision). Captures the exact embedded string.
        engine.embed_calls += 1
        engine.captured.append(text)
        return [float(sum(map(ord, text))), float(len(text)), 0.3]

    mem._create_embedding = _embed
    return mem


async def _seed_ddl(mem, *, relationships=("customer",), table_description="old desc"):
    return await mem.save_ddl_memory(
        ddl_statement="CREATE TABLE orders (id INT)",
        table_name="orders",
        columns=list(_FULL_COLUMNS),
        schema_name="public",
        table_description=table_description,
        relationships=list(relationships) if relationships else None,
    )


def _fe_columns(new_descriptions=None):
    """Mirror src/.../MemoryEditModal.svelte editColumns.map (L94-101): only
    name/data_type/description/is_primary_key/is_foreign_key/(foreign_table).
    foreign_column / is_nullable / default_value are DROPPED — the whole point
    of the merge.
    """
    new_descriptions = new_descriptions or {}
    out = []
    for c in _FULL_COLUMNS:
        d = {
            "name": c.name,
            "data_type": c.data_type,
            "description": new_descriptions.get(c.name, c.description or ""),
            "is_primary_key": c.is_primary_key,
            "is_foreign_key": c.is_foreign_key,
        }
        if c.foreign_table:
            d["foreign_table"] = c.foreign_table
        out.append(d)
    return out


def _seed_doc(
    eng,
    *,
    mid="docX",
    content="old content",
    vector=(1.0, 2.0, 3.0),
    entity="documentation",
    extra=None,
):
    md = {"entity_type": entity}
    if extra:
        md.update(extra)
    eng.store[mid] = DocumentItem(
        id=mid,
        content=content,
        vector=list(vector) if vector is not None else None,
        collection="db1",
        metadata=md,
    )
    return mid


# --- render_ddl_memory (pure) ------------------------------------------------
class TestRenderDdlMemory:
    def test_byte_identical_with_relationships_and_descless_column(self):
        cols = [
            ColumnDetail(name="id", data_type="INT", description="primary id"),
            ColumnDetail(name="note", data_type="TEXT"),  # no description
        ]
        content, embedding = render_ddl_memory(
            "orders", "Order records", cols, ["customer", "product"]
        )
        assert content == (
            "Table: orders\n"
            "Description: Order records\n"
            "Columns: id: primary id\n"
            "Related tables: customer, product"
        )
        assert embedding == (
            "orders\nOrder records\nid: primary id\nnote\nRelated: customer product"
        )

    def test_accepts_dicts_same_as_columndetail(self):
        cols_obj = [ColumnDetail(name="id", data_type="INT", description="d")]
        cols_dict = [{"name": "id", "data_type": "INT", "description": "d"}]
        assert render_ddl_memory("t", "td", cols_obj, ["r"]) == render_ddl_memory(
            "t", "td", cols_dict, ["r"]
        )

    def test_minimal_no_desc_no_cols_no_rels(self):
        content, embedding = render_ddl_memory("t", None, [], None)
        assert content == "Table: t"
        assert embedding == "t"


# --- _safe_json (pure) -------------------------------------------------------
class TestSafeJson:
    def test_none_returns_none(self):
        assert _safe_json(None) is None

    def test_malformed_returns_none(self):
        assert _safe_json("{not valid") is None

    def test_valid_json_parsed(self):
        assert _safe_json('[{"name": "a"}]') == [{"name": "a"}]

    def test_already_parsed_passthrough(self):
        v = [{"name": "a"}]
        assert _safe_json(v) is v


# --- merge_columns_by_name (pure) --------------------------------------------
class TestMergeColumns:
    def test_preserves_stored_structural_fields(self):
        stored = [
            {
                "name": "cust",
                "data_type": "INT",
                "description": "d",
                "is_primary_key": False,
                "is_foreign_key": True,
                "foreign_table": "customer",
                "foreign_column": "id",
                "is_nullable": False,
                "default_value": "0",
            }
        ]
        incoming = [  # FE-shaped: no foreign_column / is_nullable / default_value
            {
                "name": "cust",
                "data_type": "INT",
                "description": "EDITED",
                "is_primary_key": False,
                "is_foreign_key": True,
                "foreign_table": "customer",
            }
        ]
        merged = {c["name"]: c for c in merge_columns_by_name(stored, incoming)}
        assert merged["cust"]["description"] == "EDITED"  # edit applied
        assert merged["cust"]["foreign_column"] == "id"  # preserved
        assert merged["cust"]["is_nullable"] is False  # preserved
        assert merged["cust"]["default_value"] == "0"  # preserved

    def test_empty_incoming_keeps_stored(self):
        stored = [{"name": "id", "data_type": "INT", "foreign_column": "x"}]
        assert merge_columns_by_name(stored, []) == stored  # wipe prevention

    def test_appends_new_incoming_column(self):
        stored = [{"name": "a", "data_type": "INT"}]
        incoming = [
            {"name": "a", "data_type": "INT", "description": "d"},
            {"name": "b", "data_type": "TEXT", "description": "new"},
        ]
        merged = merge_columns_by_name(stored, incoming)
        assert [c["name"] for c in merged] == ["a", "b"]


# --- update_memory: ddl_schema branch ----------------------------------------
class TestUpdateMemoryDdlReembed:
    async def test_table_description_edit_reembeds(self):  # (1)
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem)
        vec_before = list(eng.store[ddl.memory_id].vector)
        eng.embed_calls = 0
        eng.captured = []

        ok = await mem.update_memory(
            ddl.memory_id,
            content=None,
            metadata_updates={
                "table_description": "BRAND NEW description",
                "column_info_json": json.dumps(_fe_columns()),
            },
        )

        assert ok is True
        assert eng.embed_calls == 1
        assert "BRAND NEW description" in eng.captured[-1]
        after = eng.store[ddl.memory_id]
        assert after.vector != vec_before
        assert "BRAND NEW description" in after.content
        assert after.metadata["table_description"] == "BRAND NEW description"

    async def test_column_description_edit_in_embedding(self):  # (2)
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem)
        eng.embed_calls = 0
        eng.captured = []

        ok = await mem.update_memory(
            ddl.memory_id,
            content=None,
            metadata_updates={
                "table_description": "old desc",
                "column_info_json": json.dumps(
                    _fe_columns(new_descriptions={"qty": "ORDERED QUANTITY"})
                ),
            },
        )

        assert ok is True
        assert "qty: ORDERED QUANTITY" in eng.captured[-1]

    async def test_embedding_failure_is_fail_closed(self):  # (3)
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem)
        before = eng.store[ddl.memory_id]
        snap = (before.content, list(before.vector), dict(before.metadata))
        updates_before = eng.update_calls

        async def _none_embed(text):
            eng.embed_calls += 1
            return None

        mem._create_embedding = _none_embed

        ok = await mem.update_memory(
            ddl.memory_id,
            content=None,
            metadata_updates={
                "table_description": "should not persist",
                "column_info_json": json.dumps(_fe_columns()),
            },
        )

        assert ok is False
        after = eng.store[ddl.memory_id]
        assert (after.content, after.vector, after.metadata) == snap  # untouched
        assert eng.update_calls == updates_before  # no partial write

    async def test_edit_relationshipless_ddl_succeeds(self):  # (4) C1 guard
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem, relationships=None)
        assert eng.store[ddl.memory_id].metadata["relationships_json"] is None
        eng.embed_calls = 0

        ok = await mem.update_memory(
            ddl.memory_id,
            content=None,
            metadata_updates={
                "table_description": "edited",
                "column_info_json": json.dumps(_fe_columns()),
            },
        )

        assert ok is True  # no json.loads(None) crash
        assert eng.embed_calls == 1

    async def test_edit_preserves_structural_fields_for_join_graph(self):  # (5) C2
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem)

        ok = await mem.update_memory(
            ddl.memory_id,
            content=None,
            metadata_updates={
                "table_description": "new",
                "column_info_json": json.dumps(_fe_columns()),  # FE drops 3 fields
            },
        )

        assert ok is True
        schemas = await mem.get_table_schemas(["orders"])
        assert len(schemas) == 1
        cols = {c.name: c for c in schemas[0].columns}
        assert cols["customer_id"].foreign_column == "id"  # preserved
        assert cols["customer_id"].is_nullable is False  # preserved
        assert cols["qty"].default_value == "0"  # preserved

    async def test_edit_preserves_immutable_metadata(self):  # (6)
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem)

        await mem.update_memory(
            ddl.memory_id,
            content=None,
            metadata_updates={
                "table_description": "new",
                "column_info_json": json.dumps(_fe_columns()),
            },
        )

        md = eng.store[ddl.memory_id].metadata
        assert md["schema_name"] == "public"
        assert md["ddl_statement"] == "CREATE TABLE orders (id INT)"
        assert md["relationships_json"] == json.dumps(["customer"])

    async def test_reembed_emits_confirmation_log(self, caplog):  # observability
        eng = _FakeEngine()
        mem = _make_memory(eng)
        ddl = await _seed_ddl(mem)
        with caplog.at_level(
            logging.INFO, logger="extension_modules.dbsphere.memory.search_memory"
        ):
            await mem.update_memory(
                ddl.memory_id,
                content=None,
                metadata_updates={
                    "table_description": "logged desc",
                    "column_info_json": json.dumps(_fe_columns()),
                },
            )
        recs = [
            r.getMessage() for r in caplog.records if "re-embedded" in r.getMessage()
        ]
        assert recs, "expected a 'DDL re-embedded' info log"
        assert "logged desc" in recs[-1]  # text= shows the edited description


# --- update_memory: non-ddl unchanged (fail-closed scoped to ddl) ------------
class TestUpdateMemoryNonDdl:
    async def test_documentation_content_edit_reembeds(self):  # (7)
        eng = _FakeEngine()
        mem = _make_memory(eng)
        mid = _seed_doc(eng)
        eng.embed_calls = 0
        eng.captured = []

        ok = await mem.update_memory(mid, content="new content", metadata_updates=None)

        assert ok is True
        assert eng.embed_calls == 1
        assert eng.store[mid].content == "new content"
        assert eng.store[mid].vector is not None

    async def test_non_ddl_embedding_failure_not_fail_closed(self):  # (7b) scope lock
        eng = _FakeEngine()
        mem = _make_memory(eng)
        mid = _seed_doc(eng)

        async def _none_embed(text):
            eng.embed_calls += 1
            return None

        mem._create_embedding = _none_embed

        ok = await mem.update_memory(mid, content="changed", metadata_updates=None)

        # fail-closed is ddl-scoped: non-ddl path keeps its legacy behavior
        # (stores even a None vector) — out of scope to change here.
        assert ok is True
        assert eng.store[mid].vector is None

    async def test_legacy_none_vector_metadata_only_edit_succeeds(self):  # (8) H2
        eng = _FakeEngine()
        mem = _make_memory(eng)
        mid = _seed_doc(eng, vector=None, extra={"title": "old"})
        eng.embed_calls = 0

        ok = await mem.update_memory(
            mid, content=None, metadata_updates={"title": "new"}
        )

        assert ok is True
        assert eng.embed_calls == 0  # no embedding attempted
        assert eng.store[mid].metadata["title"] == "new"
        assert eng.store[mid].vector is None
