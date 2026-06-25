"""PR3 — concurrency + dbsphere backend (P0 stabilization).

Covers four stabilization fixes; all use fakes/mocks so no live DB driver
(oracledb/pymssql/databricks-sql) is required:

- T3.1 thread-safety: parallel schema extraction must give each table-task its
  OWN sql runner (own DBAPI connection). Raw-connection runners share a single
  ``self._connection`` that is unsafe across the run_in_executor threads spawned
  under ``Semaphore(5)``. The shared runner must NOT be used for per-table
  extraction, and each per-task runner must be closed.
- T3.2 Fabric guard: FabricRunner must fail fast with a clear, unsupported-
  connector error instead of inheriting Synapse's pymssql SQL-auth path.
- T3.3 Synapse PK: Synapse DDL/column extraction must surface PRIMARY KEY.
- T3.4 Databricks verified FK: get_foreign_key_relationships must read declared
  Unity Catalog information_schema FKs (no inference) and degrade to [] on error.
"""

from __future__ import annotations

import pandas as pd
import pytest
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.memory.schema_extractor import SchemaExtractor


def _cfg(db_type: str = "databricks", **kw) -> DBConfig:
    base = dict(
        db_type=db_type,
        host="h",
        port=443,
        database="db",
        username="u",
        password="p",
    )
    base.update(kw)
    return DBConfig(**base)


# ===========================================================================
# T3.1 — per-task runner connection isolation during parallel extraction
# ===========================================================================
class _SpyTaskRunner:
    """A per-task runner returned by the patched factory. Records the table it
    extracted and whether it was closed, so the test can prove isolation."""

    def __init__(self, config):
        self.config = config
        self.ddl_tables: list[str] = []
        self.closed = False

    async def get_table_ddl(self, table_name):
        self.ddl_tables.append(table_name)
        return f"CREATE TABLE {table_name} (id INT);"

    async def get_table_columns(self, table_name):
        return []

    async def get_random_samples(self, table_name, limit=5):
        return pd.DataFrame()

    async def close(self):
        self.closed = True


class _SharedRunner:
    """The shared runner held by the extractor. If extraction is correctly
    isolated, its get_table_ddl is NEVER called (only the relationship pass
    touches get_foreign_key_relationships)."""

    def __init__(self, config):
        self.config = config
        self.ddl_calls: list[str] = []
        self.fk_calls: list[str] = []

    async def get_table_ddl(self, table_name):
        self.ddl_calls.append(table_name)
        return f"CREATE TABLE {table_name} (id INT);"

    async def get_table_columns(self, table_name):
        return []

    async def get_random_samples(self, table_name, limit=5):
        return pd.DataFrame()

    async def get_foreign_key_relationships(self, table_name=None):
        self.fk_calls.append(table_name)
        return []

    async def close(self):  # pragma: no cover - shared runner not closed by us
        raise AssertionError("shared runner must not be closed by extraction")


class _PoolSharedRunner(_SharedRunner):
    """A pool-based shared runner (Postgres/MySQL). pool.acquire() hands each
    query its own connection, so it is concurrency-safe and the parallel
    extraction should reuse it directly instead of building a per-table runner."""

    is_pool_based = True


class _FakeMemory:
    """Minimal SearchEngineDbSphereMemory stand-in for extract_and_save."""

    def __init__(self, dbsphere_id="ds-pr3"):
        self.dbsphere_id = dbsphere_id
        self.ddl_saved: list[str] = []

    def session(self):
        memory = self

        class _Ctx:
            async def __aenter__(self):
                return memory

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    async def save_ddl_memory(self, *, ddl_statement, table_name, columns, **kw):
        self.ddl_saved.append(table_name)
        return True

    async def save_documentation(self, **kw):  # pragma: no cover - no FK here
        return object()


async def test_parallel_extraction_uses_isolated_runner_per_table(monkeypatch):
    """Each table-task builds its own runner (own connection) and closes it;
    the shared runner is never used for per-table DDL extraction."""
    created: list[_SpyTaskRunner] = []

    def _fake_factory(config):
        r = _SpyTaskRunner(config)
        created.append(r)
        return r

    # process_table imports create_sql_runner lazily from this package module.
    monkeypatch.setattr(
        "extension_modules.dbsphere.sql_runners.create_sql_runner",
        _fake_factory,
    )

    shared = _SharedRunner(_cfg(db_type="oracle"))
    ext = SchemaExtractor(sql_runner=shared)  # no LLM → basic extraction
    mem = _FakeMemory()

    tables = ["T_A", "T_B", "T_C"]
    result = await ext.extract_and_save_to_memory(
        memory=mem,
        table_names=tables,
        generate_sample_qa=False,
    )

    # One dedicated runner per table, each closed (connection released).
    assert len(created) == len(tables)
    assert all(r.closed for r in created)
    # Every table was extracted via a per-task runner, not the shared one.
    extracted = sorted(t for r in created for t in r.ddl_tables)
    assert extracted == sorted(tables)
    assert shared.ddl_calls == [], "shared runner used for extraction (race risk)"
    assert result["ddl_saved"] == len(tables)


async def test_extraction_falls_back_to_shared_runner_if_factory_fails(monkeypatch):
    """If the factory can't build a per-task runner, extraction degrades to the
    shared runner rather than crashing the whole batch."""

    def _broken_factory(config):
        raise RuntimeError("no driver")

    monkeypatch.setattr(
        "extension_modules.dbsphere.sql_runners.create_sql_runner",
        _broken_factory,
    )

    shared = _SharedRunner(_cfg(db_type="oracle"))
    ext = SchemaExtractor(sql_runner=shared)
    mem = _FakeMemory()

    result = await ext.extract_and_save_to_memory(
        memory=mem,
        table_names=["T_X"],
        generate_sample_qa=False,
    )

    # Fallback path: shared runner did the extraction.
    assert shared.ddl_calls == ["T_X"]
    assert result["ddl_saved"] == 1


async def test_pool_based_runner_reuses_shared_no_per_table_runner(monkeypatch):
    """Pool-based runners (Postgres/MySQL) are already concurrency-safe, so the
    parallel extraction reuses the shared runner instead of spawning one per
    table — avoiding the per-table connection-pool amplification regression."""
    created: list[_SpyTaskRunner] = []

    def _fake_factory(config):
        r = _SpyTaskRunner(config)
        created.append(r)
        return r

    monkeypatch.setattr(
        "extension_modules.dbsphere.sql_runners.create_sql_runner",
        _fake_factory,
    )

    shared = _PoolSharedRunner(_cfg(db_type="postgresql"))
    ext = SchemaExtractor(sql_runner=shared)
    mem = _FakeMemory()

    tables = ["T_A", "T_B", "T_C"]
    result = await ext.extract_and_save_to_memory(
        memory=mem,
        table_names=tables,
        generate_sample_qa=False,
    )

    # No per-task runner built — the factory must never be called for a
    # pool-based shared runner (else each table opens its own pool).
    assert created == [], "pool-based runner must not spawn per-table runners"
    # The shared pool runner handled every table's extraction directly.
    assert sorted(shared.ddl_calls) == sorted(tables)
    assert result["ddl_saved"] == len(tables)


# ===========================================================================
# T3.2 — Fabric fail-fast guard
# ===========================================================================
def test_fabric_get_connection_raises_clear_unsupported_error():
    from extension_modules.dbsphere.sql_runners.fabric import FabricRunner

    runner = FabricRunner(_cfg(db_type="fabric"))
    with pytest.raises(NotImplementedError) as exc:
        runner._get_connection_sync()

    msg = str(exc.value)
    assert "Fabric" in msg
    assert "not supported" in msg.lower()
    # Mentions the real cause so operators aren't sent chasing credentials.
    assert "Azure AD" in msg or "Entra" in msg


async def test_fabric_test_connection_propagates_guard():
    """test_connection must surface the guard, not silently return a result."""
    from extension_modules.dbsphere.sql_runners.fabric import FabricRunner

    runner = FabricRunner(_cfg(db_type="fabric"))
    with pytest.raises(NotImplementedError):
        await runner.test_connection()


# ===========================================================================
# T3.3 — Synapse PRIMARY KEY surfaced in extraction
# ===========================================================================
async def test_synapse_ddl_includes_primary_key(monkeypatch):
    from extension_modules.dbsphere.sql_runners.synapse import SynapseRunner

    runner = SynapseRunner(_cfg(db_type="synapse", schema_name="dbo"))

    cols = pd.DataFrame(
        [
            {
                "COLUMN_NAME": "ID",
                "DATA_TYPE": "int",
                "CHARACTER_MAXIMUM_LENGTH": None,
                "NUMERIC_PRECISION": None,
                "NUMERIC_SCALE": None,
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
            },
            {
                "COLUMN_NAME": "NAME",
                "DATA_TYPE": "varchar",
                "CHARACTER_MAXIMUM_LENGTH": 50,
                "NUMERIC_PRECISION": None,
                "NUMERIC_SCALE": None,
                "IS_NULLABLE": "YES",
                "COLUMN_DEFAULT": None,
            },
        ]
    )

    async def _fake_run_sql(sql):
        return cols

    async def _fake_pks(schema_name, table_name):
        return {"ID"}

    monkeypatch.setattr(runner, "run_sql", _fake_run_sql)
    monkeypatch.setattr(runner, "_get_primary_keys", _fake_pks)

    ddl = await runner.get_table_ddl("T_ORDER")
    pk_line = next(ln for ln in ddl.splitlines() if "[ID]" in ln)
    assert "PRIMARY KEY" in pk_line
    # Non-PK column must not be marked PK.
    name_line = next(ln for ln in ddl.splitlines() if "[NAME]" in ln)
    assert "PRIMARY KEY" not in name_line


async def test_synapse_columns_flag_primary_key(monkeypatch):
    from extension_modules.dbsphere.sql_runners.synapse import SynapseRunner

    runner = SynapseRunner(_cfg(db_type="synapse", schema_name="dbo"))
    cols = pd.DataFrame(
        [
            {
                "COLUMN_NAME": "ID",
                "DATA_TYPE": "int",
                "CHARACTER_MAXIMUM_LENGTH": None,
                "IS_NULLABLE": "NO",
                "COLUMN_DEFAULT": None,
            }
        ]
    )

    async def _fake_run_sql(sql):
        return cols

    async def _fake_pks(schema_name, table_name):
        return {"ID"}

    async def _fake_fks(schema_name, table_name):
        return {}

    monkeypatch.setattr(runner, "run_sql", _fake_run_sql)
    monkeypatch.setattr(runner, "_get_primary_keys", _fake_pks)
    monkeypatch.setattr(runner, "_get_foreign_keys_for_table", _fake_fks)

    columns = await runner.get_table_columns("T_ORDER")
    assert len(columns) == 1
    assert columns[0].is_primary_key is True


# ===========================================================================
# T3.4 — Databricks declared (verified) FK extraction
# ===========================================================================
async def test_databricks_fk_reads_information_schema(monkeypatch):
    from extension_modules.dbsphere.sql_runners.databricks import DatabricksRunner

    runner = DatabricksRunner(
        _cfg(db_type="databricks", catalog="main", schema_name="sales")
    )

    captured = {}

    async def _fake_run_sql(sql):
        captured["sql"] = sql
        return pd.DataFrame(
            [
                {
                    "constraint_name": "fk_order_cust",
                    "source_table": "orders",
                    "source_column": "cust_id",
                    "target_table": "customers",
                    "target_column": "id",
                }
            ]
        )

    monkeypatch.setattr(runner, "run_sql", _fake_run_sql)

    fks = await runner.get_foreign_key_relationships()
    assert len(fks) == 1
    assert fks[0]["source_table"] == "orders"
    assert fks[0]["target_column"] == "id"
    assert fks[0]["constraint_name"] == "fk_order_cust"

    # Declared-FK only: reads ANSI information_schema, never infers from names.
    sql = captured["sql"]
    assert "information_schema.referential_constraints" in sql
    assert "key_column_usage" in sql
    # Catalog-qualified for Unity Catalog.
    assert "main.information_schema" in sql
    # Scoped to the configured schema.
    assert "'sales'" in sql


async def test_databricks_fk_degrades_to_empty_on_error(monkeypatch):
    from extension_modules.dbsphere.sql_runners.databricks import DatabricksRunner

    runner = DatabricksRunner(_cfg(db_type="databricks", schema_name="sales"))

    async def _raise(sql):
        raise RuntimeError("information_schema not available on this metastore")

    monkeypatch.setattr(runner, "run_sql", _raise)

    fks = await runner.get_foreign_key_relationships()
    assert fks == []


async def test_databricks_fk_filters_by_table(monkeypatch):
    from extension_modules.dbsphere.sql_runners.databricks import DatabricksRunner

    runner = DatabricksRunner(_cfg(db_type="databricks", schema_name="sales"))
    captured = {}

    async def _fake_run_sql(sql):
        captured["sql"] = sql
        return pd.DataFrame(
            columns=[
                "constraint_name",
                "source_table",
                "source_column",
                "target_table",
                "target_column",
            ]
        )

    monkeypatch.setattr(runner, "run_sql", _fake_run_sql)

    await runner.get_foreign_key_relationships(table_name="orders")
    assert "kcu_fk.table_name = 'orders'" in captured["sql"]
