"""Endpoint tests for ``GET /{id}/join-graph`` (relationship panel #4/#5).

Direct-call tests with mocked ``DbSpheres`` + memory (no live DB/engine). Cover
the permission matrix, response shape, truncated/extracted flags, and the
side-effect-free invariant — the GET must never call ``_recompute_join_graph`` /
``delete_relationship_graph_doc`` (router integration via FastAPI harness is the
separate backlog item #6).
"""

from __future__ import annotations

import types

import pytest
from extension_modules.dbsphere.memory.models import ColumnDetail, DDLMemory
from fastapi import HTTPException
from open_webui.routers import dbsphere as dbsphere_router

_JG = (
    "## JOIN Graph\n\n"
    "### Verified (foreign keys)\n"
    "- SALES → CUSTOMERS  ON SALES.CUST_ID = CUSTOMERS.CUST_ID"
)


def _col(name, pk=False, fk=False, ftable=None, fcol=None):
    return ColumnDetail(
        name=name,
        data_type="int",
        is_primary_key=pk,
        is_foreign_key=fk,
        foreign_table=ftable,
        foreign_column=fcol,
    )


def _ddl(table, columns, schema="public"):
    return DDLMemory(
        memory_id=f"ds__ddl__{table}",
        ddl_statement=f"CREATE TABLE {table} (...)",
        table_name=table,
        schema_name=schema,
        columns=columns,
    )


_TWO_TABLES = [
    _ddl(
        "SALES",
        [
            _col("ID", pk=True),
            _col("CUST_ID", fk=True, ftable="CUSTOMERS", fcol="CUST_ID"),
        ],
    ),
    _ddl("CUSTOMERS", [_col("CUST_ID", pk=True)]),
]


class _FakeMemory:
    """Records construction + would-be side-effects; returns canned DDL."""

    last = None

    def __init__(self, app=None, dbsphere_id=None, user_id=None, tables=None):
        self._tables = _TWO_TABLES if tables is None else tables
        self.deleted = False
        _FakeMemory.last = self

    async def get_table_schemas(self, *a, **k):
        return self._tables

    async def delete_relationship_graph_doc(self):  # must never be called by GET
        self.deleted = True


def _empty_memory_cls():
    class _Empty(_FakeMemory):
        def __init__(self, *a, **k):
            super().__init__(*a, tables=[], **k)

    return _Empty


def _dbsphere(user_id="owner", access_control=None, data=None):
    return types.SimpleNamespace(
        id="ds1",
        user_id=user_id,
        access_control=access_control,
        data={"join_graph": _JG} if data is None else data,
    )


def _patch(monkeypatch, dbsphere_obj, memory_cls=_FakeMemory):
    monkeypatch.setattr(
        dbsphere_router.DbSpheres,
        "get_dbsphere_by_id",
        lambda id: dbsphere_obj,
        raising=True,
    )
    monkeypatch.setattr(
        "extension_modules.dbsphere.memory.SearchEngineDbSphereMemory",
        memory_cls,
        raising=False,
    )


def _req():
    return types.SimpleNamespace(app=None)


def _user(uid, role="user"):
    return types.SimpleNamespace(id=uid, role=role)


async def test_owner_gets_graph_with_roles(monkeypatch):
    _patch(monkeypatch, _dbsphere(user_id="owner"))
    resp = await dbsphere_router.get_join_graph(_req(), "ds1", _user("owner"))
    assert resp.success is True
    assert resp.extracted is True
    assert {n.table for n in resp.nodes} == {"SALES", "CUSTOMERS"}
    assert len(resp.edges) == 1
    assert resp.edges[0].relationship_type == "verified_fk"
    customers = next(n for n in resp.nodes if n.table == "CUSTOMERS")
    assert customers.role == "dimension"  # referenced by SALES, references none
    assert customers.schema_name == "public"


async def test_admin_bypasses_ownership(monkeypatch):
    _patch(monkeypatch, _dbsphere(user_id="someone_else", access_control={}))
    resp = await dbsphere_router.get_join_graph(
        _req(), "ds1", _user("admin1", role="admin")
    )
    assert resp.success is True and resp.extracted is True


async def test_other_user_without_access_denied(monkeypatch):
    _patch(monkeypatch, _dbsphere(user_id="owner", access_control={}))  # private
    with pytest.raises(HTTPException) as ei:
        await dbsphere_router.get_join_graph(_req(), "ds1", _user("intruder"))
    assert ei.value.status_code == 401


async def test_access_control_read_grant(monkeypatch):
    ac = {"read": {"group_ids": [], "user_ids": ["guest"], "org_unit_ids": []}}
    _patch(monkeypatch, _dbsphere(user_id="owner", access_control=ac))
    resp = await dbsphere_router.get_join_graph(_req(), "ds1", _user("guest"))
    assert resp.success is True and resp.extracted is True


async def test_missing_dbsphere_404(monkeypatch):
    _patch(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await dbsphere_router.get_join_graph(_req(), "nope", _user("owner"))
    assert ei.value.status_code == 404


async def test_never_extracted_returns_empty_not_error(monkeypatch):
    _patch(
        monkeypatch, _dbsphere(user_id="owner", data={}), memory_cls=_empty_memory_cls()
    )
    resp = await dbsphere_router.get_join_graph(_req(), "ds1", _user("owner"))
    assert resp.success is True
    assert resp.extracted is False
    assert resp.nodes == [] and resp.edges == []


async def test_extracted_but_no_relationships(monkeypatch):
    # DDL present but join_graph empty → extracted=True, no edges, roles unclassified.
    _patch(monkeypatch, _dbsphere(user_id="owner", data={"join_graph": ""}))
    resp = await dbsphere_router.get_join_graph(_req(), "ds1", _user("owner"))
    assert resp.success is True and resp.extracted is True
    assert resp.edges == []
    assert all(n.role == "unclassified" for n in resp.nodes)


async def test_side_effect_free(monkeypatch):
    _patch(monkeypatch, _dbsphere(user_id="owner"))
    await dbsphere_router.get_join_graph(_req(), "ds1", _user("owner"))
    assert _FakeMemory.last is not None
    assert _FakeMemory.last.deleted is False  # GET never purges/recomputes


async def test_truncated_flag_and_role_suppression(monkeypatch):
    monkeypatch.setattr(
        "extension_modules.dbsphere.memory.search_memory.DDL_SCHEMA_FETCH_LIMIT",
        2,
        raising=True,
    )
    _patch(monkeypatch, _dbsphere(user_id="owner"))  # returns exactly 2 tables
    resp = await dbsphere_router.get_join_graph(_req(), "ds1", _user("owner"))
    assert resp.truncated is True
    assert all(n.role == "unclassified" for n in resp.nodes)
