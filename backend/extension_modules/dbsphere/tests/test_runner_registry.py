"""Unit tests for the unified SQL runner + dialect registry (P0 PR1).

Guards the single-source-of-truth invariant: every DBType maps to the correct
runner class AND to a dialect_name that resolves to its *own* dialect-specific
prompt block (not the generic fallback, and not a different dialect's block).

BigQuery is the regression case — it was missing from the DBSphereAgent /
DashboardBuilder / dialect_map copies before unification, so it silently fell
back to a generic "SQL" dialect with no BigQuery rules.

These tests are pure (no DB / network) — they assert the registry data and the
prompt linkage only.
"""

from __future__ import annotations

import pytest
from extension_modules.dbsphere.dbsphere_state import DBType
from extension_modules.dbsphere.prompts import _build_dialect_rules
from extension_modules.dbsphere.sql_runners import (
    RUNNER_REGISTRY,
    create_sql_runner,
    get_dialect_name,
)
from extension_modules.dbsphere.sql_runners.bigquery import BigQueryRunner
from extension_modules.dbsphere.sql_runners.databricks import DatabricksRunner
from extension_modules.dbsphere.sql_runners.fabric import FabricRunner
from extension_modules.dbsphere.sql_runners.mssql import MSSQLRunner
from extension_modules.dbsphere.sql_runners.mysql import MySQLRunner
from extension_modules.dbsphere.sql_runners.oracle import OracleRunner
from extension_modules.dbsphere.sql_runners.postgres import PostgresRunner
from extension_modules.dbsphere.sql_runners.snowflake import SnowflakeRunner
from extension_modules.dbsphere.sql_runners.synapse import SynapseRunner

# Expected runner class per DBType. None = in the enum but no runner (sqlite).
EXPECTED_RUNNER = {
    DBType.POSTGRES: PostgresRunner,
    DBType.MYSQL: MySQLRunner,
    DBType.MSSQL: MSSQLRunner,
    DBType.ORACLE: OracleRunner,
    DBType.SNOWFLAKE: SnowflakeRunner,
    DBType.DATABRICKS: DatabricksRunner,
    DBType.SYNAPSE: SynapseRunner,
    DBType.FABRIC: FabricRunner,
    DBType.BIGQUERY: BigQueryRunner,
    DBType.SQLITE: None,
}

# A header marker unique to each dialect's block in prompts._build_dialect_rules.
# Asserting the *correct* block (not merely a non-generic one) catches a
# dialect_name that accidentally substring-matches the wrong block.
EXPECTED_DIALECT_MARKER = {
    DBType.POSTGRES: "PostgreSQL-Specific",
    DBType.MYSQL: "MySQL / MariaDB-Specific",
    DBType.MSSQL: "SQL Server / Synapse / Fabric-Specific",
    DBType.ORACLE: "Oracle-Specific",
    DBType.SNOWFLAKE: "Snowflake-Specific",
    DBType.DATABRICKS: "Databricks SQL-Specific",
    DBType.SYNAPSE: "SQL Server / Synapse / Fabric-Specific",
    DBType.FABRIC: "SQL Server / Synapse / Fabric-Specific",
    DBType.BIGQUERY: "BigQuery-Specific",
    DBType.SQLITE: "SQLite-Specific",
}

_GENERIC_MARKER = "General SQL Rules"


def test_registry_covers_every_dbtype():
    """RUNNER_REGISTRY must hold an entry for every DBType — no drift."""
    assert set(RUNNER_REGISTRY) == set(DBType)


def test_registry_runner_classes_match():
    for db_type, expected in EXPECTED_RUNNER.items():
        assert RUNNER_REGISTRY[db_type].runner_cls is expected, db_type


def test_dialect_name_resolves_to_correct_block():
    """Every DBType's dialect_name routes to its own dialect-specific block."""
    for db_type, marker in EXPECTED_DIALECT_MARKER.items():
        dialect = get_dialect_name(db_type)
        rules = _build_dialect_rules(dialect)
        assert marker in rules, f"{db_type} -> {dialect!r} missed block {marker!r}"
        assert _GENERIC_MARKER not in rules, f"{db_type} -> generic fallback"


def test_bigquery_regression():
    """BigQuery: missing before unification — now resolves to BigQuery rules."""
    assert RUNNER_REGISTRY[DBType.BIGQUERY].runner_cls is BigQueryRunner
    rules = _build_dialect_rules(get_dialect_name(DBType.BIGQUERY))
    # BigQuery-specific content must reach the prompt (was generic "SQL" before).
    assert "SAFE_CAST" in rules


def test_sqlite_asymmetry():
    """SQLITE is in the enum + has a dialect block, but has no runner."""
    assert RUNNER_REGISTRY[DBType.SQLITE].runner_cls is None
    assert "SQLite-Specific" in _build_dialect_rules(get_dialect_name(DBType.SQLITE))


def test_create_sql_runner_returns_none_for_runnerless_type():
    class _Cfg:
        def get_db_type_enum(self):
            return DBType.SQLITE

    assert create_sql_runner(_Cfg()) is None


def test_get_dialect_name_unknown_falls_back():
    class _NotADbType:
        pass

    assert get_dialect_name(_NotADbType()) == "SQL"


def test_registry_is_read_only():
    """RUNNER_REGISTRY는 MappingProxyType로 봉인 — single source of truth가
    런타임에 변조(전역 오염)되지 않음을 가드한다."""
    with pytest.raises(TypeError):
        RUNNER_REGISTRY[DBType.POSTGRES] = None  # type: ignore[index]
    with pytest.raises(AttributeError):
        RUNNER_REGISTRY.pop(DBType.POSTGRES)  # type: ignore[attr-defined]
