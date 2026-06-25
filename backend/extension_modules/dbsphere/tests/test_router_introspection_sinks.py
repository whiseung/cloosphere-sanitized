"""Router-level introspection-injection hardening for the *direct-driver* paths.

``/tables`` and ``/test-connection`` have helpers that bypass the SQL runner
(``runner.__init__`` allow-lists ``schema_name``) and talk to pymysql / psycopg2 /
pymssql / snowflake-connector directly. Those previously interpolated
``schema_name``/``database`` into SQL via f-strings — an introspection-injection
sink. The fix:

* value positions (``WHERE TABLE_SCHEMA = ...``) → bound parameters, and
* identifier positions Snowflake requires in ``FROM {db}.INFORMATION_SCHEMA`` /
  ``SHOW ... IN SCHEMA {db}.{schema}`` (no bind channel) → ``validate_sql_identifier``.

These tests mock the DB driver's ``connect`` so the introspection code is reached
without a live database, then assert the cursor receives bound params (never the
raw value in the SQL text) and that malicious identifiers are rejected before any
SQL executes.
"""

from __future__ import annotations

from open_webui.routers.dbsphere import (
    ConnectionTestForm,
    _get_snowflake_tables,
    _test_mssql_connection,
    _test_mysql_connection,
    _test_postgresql_connection,
    _test_snowflake_connection,
)

_LEAK = "x'; DROP TABLE t;--"


class _FakeCursor:
    """Records every execute() call; returns a string for version queries and
    an int for count queries so the real handler code paths don't crash."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._last = ""

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._last = sql

    def fetchone(self):
        if "VERSION" in self._last.upper():
            return ("1.0-test",)
        return (0,)

    def fetchall(self):
        return []

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def _patch(monkeypatch, module_name: str) -> _FakeCursor:
    """Patch ``<module>.connect`` to hand back a fake connection/cursor."""
    import importlib

    mod = importlib.import_module(module_name)
    cur = _FakeCursor()
    monkeypatch.setattr(mod, "connect", lambda *a, **kw: _FakeConn(cur))
    return cur


# ---------------------------------------------------------------------------
# Value positions → bound parameters (mysql / mssql / postgresql)
# ---------------------------------------------------------------------------


async def test_pg_test_connection_binds_schema_name(monkeypatch):
    cur = _patch(monkeypatch, "psycopg2")
    form = ConnectionTestForm(db_type="postgresql", host="h", schema_name=_LEAK)
    await _test_postgresql_connection(form)

    introspection = [c for c in cur.calls if "table_schema" in c[0]]
    assert introspection, "introspection query not executed"
    sql, params = introspection[0]
    assert "%s" in sql
    assert _LEAK not in sql  # value is bound, not interpolated
    assert params == (_LEAK,)


async def test_mssql_test_connection_binds_schema_name(monkeypatch):
    cur = _patch(monkeypatch, "pymssql")
    form = ConnectionTestForm(db_type="mssql", host="h", schema_name=_LEAK)
    await _test_mssql_connection(form)

    introspection = [c for c in cur.calls if "TABLE_SCHEMA" in c[0]]
    assert introspection
    sql, params = introspection[0]
    assert "%s" in sql
    assert _LEAK not in sql
    assert params == (_LEAK,)


async def test_mysql_test_connection_binds_database(monkeypatch):
    cur = _patch(monkeypatch, "pymysql")
    form = ConnectionTestForm(db_type="mysql", host="h", database=_LEAK)
    await _test_mysql_connection(form)

    introspection = [c for c in cur.calls if "TABLE_SCHEMA" in c[0]]
    assert introspection
    sql, params = introspection[0]
    assert "%s" in sql
    assert _LEAK not in sql
    assert params == (_LEAK,)


# ---------------------------------------------------------------------------
# Identifier positions → validate_sql_identifier (snowflake)
# ---------------------------------------------------------------------------


async def test_snowflake_tables_rejects_malicious_database(monkeypatch):
    cur = _patch(monkeypatch, "snowflake.connector")
    form = ConnectionTestForm(
        db_type="snowflake", host="h", database=_LEAK, schema_name="PUBLIC"
    )
    resp = await _get_snowflake_tables(form)

    assert resp.success is False
    assert "Invalid SQL" in resp.message
    # validate fires before any SHOW reaches the cursor
    assert not any("SHOW" in c[0] for c in cur.calls)


async def test_snowflake_tables_rejects_malicious_schema(monkeypatch):
    cur = _patch(monkeypatch, "snowflake.connector")
    form = ConnectionTestForm(
        db_type="snowflake", host="h", database="mydb", schema_name="x' OR '1'='1"
    )
    resp = await _get_snowflake_tables(form)

    assert resp.success is False
    assert "Invalid SQL" in resp.message
    assert not any("SHOW" in c[0] for c in cur.calls)


async def test_snowflake_tables_allows_korean_identifiers(monkeypatch):
    cur = _patch(monkeypatch, "snowflake.connector")
    form = ConnectionTestForm(
        db_type="snowflake", host="h", database="생산", schema_name="공장"
    )
    resp = await _get_snowflake_tables(form)

    assert resp.success is True
    assert any("SHOW TABLES IN SCHEMA 생산.공장" in c[0] for c in cur.calls)


async def test_snowflake_test_connection_blocks_malicious_db_before_sql(monkeypatch):
    cur = _patch(monkeypatch, "snowflake.connector")
    form = ConnectionTestForm(
        db_type="snowflake", host="h", database=_LEAK, schema_name="PUBLIC"
    )
    resp = await _test_snowflake_connection(form)

    # Connection itself succeeds; the malicious db identifier is allow-listed so
    # the INFORMATION_SCHEMA introspection query never reaches the cursor.
    assert resp.success is True
    assert not any("INFORMATION_SCHEMA" in c[0] for c in cur.calls)


async def test_snowflake_test_connection_binds_schema_value(monkeypatch):
    cur = _patch(monkeypatch, "snowflake.connector")
    form = ConnectionTestForm(
        db_type="snowflake", host="h", database="mydb", schema_name="myschema"
    )
    await _test_snowflake_connection(form)

    introspection = [c for c in cur.calls if "INFORMATION_SCHEMA" in c[0]]
    assert introspection
    sql, params = introspection[0]
    assert "mydb.INFORMATION_SCHEMA" in sql  # db_name is a validated identifier
    assert "%s" in sql  # schema_name is a bound value
    assert params == ("myschema",)
