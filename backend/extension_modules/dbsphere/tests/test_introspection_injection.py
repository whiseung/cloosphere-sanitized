"""Unit tests for introspection SQL-injection hardening (P0 PR2 T2.1).

Schema/table names are SQL identifiers fed into introspection queries; they are
allow-listed (``validate_sql_identifier``) rather than parameterized — some flow
through ``run_sql`` which has no bind channel. The allow-list is Unicode-aware so
Korean/CJK identifiers (real in this product) pass, while injection metacharacters
are rejected. These tests cover the helper and runner-construction enforcement.
"""

from __future__ import annotations

import pytest
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.base import validate_sql_identifier
from extension_modules.dbsphere.sql_runners.oracle import OracleRunner
from extension_modules.dbsphere.sql_runners.postgres import PostgresRunner

VALID = [
    "public",
    "dbo",
    "MY_SCHEMA",
    "t$1",
    "a",
    "USER123",
    "schema_2",
    "공장코드",
    "테이블_1",
    "사용자",
]  # Unicode/Korean identifiers allowed

INVALID = [
    "x'; DROP TABLE users;--",
    "a b",  # whitespace
    "a;b",  # statement separator
    "a--b",  # comment
    "a.b",  # qualified names are composed in code, not passed whole
    "a'b",  # single quote (string-literal breakout)
    'a"b',  # double quote
    "a)b",  # paren
    "a\nb",  # embedded newline (fullmatch rejects)
    "",  # empty
]


@pytest.mark.parametrize("name", VALID)
def test_valid_identifiers_pass(name):
    assert validate_sql_identifier(name) == name


@pytest.mark.parametrize("name", INVALID)
def test_invalid_identifiers_rejected(name):
    with pytest.raises(ValueError):
        validate_sql_identifier(name, kind="schema")


def test_non_string_rejected():
    with pytest.raises(ValueError):
        validate_sql_identifier(None)  # type: ignore[arg-type]


def _cfg(**kw):
    base = dict(
        db_type="postgresql",
        host="h",
        port=5432,
        database="d",
        username="u",
        password="p",
    )
    base.update(kw)
    return DBConfig(**base)


def test_runner_rejects_malicious_schema_name_at_construction():
    # base.__init__ allow-lists config.schema_name before any DB connection.
    with pytest.raises(ValueError):
        PostgresRunner(_cfg(schema_name="x'; DROP TABLE t;--"))


def test_runner_accepts_clean_schema_name():
    runner = PostgresRunner(_cfg(schema_name="analytics"))
    assert runner.config.schema_name == "analytics"


def test_runner_accepts_korean_schema_name():
    runner = PostgresRunner(_cfg(schema_name="생산"))
    assert runner.config.schema_name == "생산"


def test_oracle_rejects_malicious_username_schema_fallback():
    # Oracle uses the username as the schema when schema_name is unset.
    with pytest.raises(ValueError):
        OracleRunner(_cfg(db_type="oracle", schema_name=None, username="u'; DROP--"))
