"""Unit tests for ``_infer_table_roles`` + ``build_join_graph_struct`` (#5).

Roles are a SOFT structural hint derived from join directionality (an edge
``source → target`` has ``target`` = referenced PK = dimension side). They are
never authoritative; the matrix below pins the conservative classification
(default ``unclassified``) and the verified/inferred confidence tier.
"""

from __future__ import annotations

from extension_modules.dbsphere.memory.models import ColumnDetail, TableDetails
from extension_modules.dbsphere.memory.schema_extractor import (
    REL_INFERRED_NAME,
    REL_VERIFIED_FK,
    _infer_table_roles,
    build_join_graph_struct,
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


def _td(name, cols):
    return TableDetails(table_name=name, ddl="", description="", columns=cols)


def _e(s, scols, t, tcols, rel=REL_VERIFIED_FK):
    return {
        "source_table": s,
        "source_columns": scols,
        "target_table": t,
        "target_columns": tcols,
        "relationship_type": rel,
        "confidence": 1.0 if rel == REL_VERIFIED_FK else 0.5,
        "evidence": [],
    }


def test_star_fact_and_dims():
    tds = [
        _td(
            "SALES",
            [
                _col("SALE_ID", pk=True),
                _col("CUST_ID", fk=True),
                _col("REGION_ID", fk=True),
                _col("PROD_ID", fk=True),
            ],
        ),
        _td("CUSTOMERS", [_col("CUST_ID", pk=True)]),
        _td("REGIONS", [_col("REGION_ID", pk=True)]),
        _td("PRODUCTS", [_col("PROD_ID", pk=True)]),
    ]
    edges = [
        _e("SALES", ["CUST_ID"], "CUSTOMERS", ["CUST_ID"]),
        _e("SALES", ["REGION_ID"], "REGIONS", ["REGION_ID"]),
        _e("SALES", ["PROD_ID"], "PRODUCTS", ["PROD_ID"]),
    ]
    roles = _infer_table_roles(edges, tds)
    assert roles["sales"]["role"] == "fact"
    assert roles["sales"]["role_confidence"] == "high"
    assert roles["customers"]["role"] == "dimension"
    assert roles["regions"]["role"] == "dimension"
    assert roles["sales"]["as_source"] == 3
    assert roles["customers"]["as_target"] == 1


def test_bridge_junction():
    tds = [
        _td(
            "ORDER_ITEMS",
            [
                _col("ORDER_ID", pk=True, fk=True),
                _col("PRODUCT_ID", pk=True, fk=True),
                _col("QTY"),
            ],
        ),
        _td("ORDERS", [_col("ORDER_ID", pk=True)]),
        _td("PRODUCTS", [_col("PRODUCT_ID", pk=True)]),
    ]
    edges = [
        _e("ORDER_ITEMS", ["ORDER_ID"], "ORDERS", ["ORDER_ID"]),
        _e("ORDER_ITEMS", ["PRODUCT_ID"], "PRODUCTS", ["PRODUCT_ID"]),
    ]
    roles = _infer_table_roles(edges, tds)
    assert roles["order_items"]["role"] == "bridge"
    assert roles["orders"]["role"] == "dimension"


def test_surrogate_pk_is_fact_not_bridge():
    # Two outgoing FKs but a single surrogate PK (not the FK cols) → fact.
    tds = [
        _td(
            "EVENTS",
            [
                _col("EVENT_ID", pk=True),
                _col("USER_ID", fk=True),
                _col("APP_ID", fk=True),
            ],
        ),
        _td("USERS", [_col("USER_ID", pk=True)]),
        _td("APPS", [_col("APP_ID", pk=True)]),
    ]
    edges = [
        _e("EVENTS", ["USER_ID"], "USERS", ["USER_ID"]),
        _e("EVENTS", ["APP_ID"], "APPS", ["APP_ID"]),
    ]
    roles = _infer_table_roles(edges, tds)
    assert roles["events"]["role"] == "fact"


def test_isolated_unclassified():
    tds = [_td("LOGS", [_col("ID", pk=True), _col("MSG")])]
    roles = _infer_table_roles([], tds)
    assert roles["logs"]["role"] == "unclassified"
    assert roles["logs"]["role_confidence"] is None


def test_dimension_tolerates_one_audit_fk():
    tds = [
        _td("SALES", [_col("ID", pk=True), _col("CUST_ID", fk=True)]),
        _td("CUSTOMERS", [_col("CUST_ID", pk=True), _col("CREATED_BY", fk=True)]),
        _td("USERS", [_col("USER_ID", pk=True)]),
    ]
    edges = [
        _e("SALES", ["CUST_ID"], "CUSTOMERS", ["CUST_ID"]),
        _e("CUSTOMERS", ["CREATED_BY"], "USERS", ["USER_ID"]),
    ]
    roles = _infer_table_roles(edges, tds)
    assert roles["customers"]["role"] == "dimension"  # as_target=1, as_source=1


def test_hub_high_in_and_out_unclassified():
    tds = [
        _td("T", [_col("ID", pk=True), _col("A_ID", fk=True), _col("B_ID", fk=True)]),
        _td("A", [_col("A_ID", pk=True)]),
        _td("B", [_col("B_ID", pk=True)]),
        _td("X", [_col("ID", pk=True), _col("T_ID", fk=True)]),
        _td("Y", [_col("ID", pk=True), _col("T_ID", fk=True)]),
    ]
    edges = [
        _e("T", ["A_ID"], "A", ["A_ID"]),
        _e("T", ["B_ID"], "B", ["B_ID"]),
        _e("X", ["T_ID"], "T", ["ID"]),
        _e("Y", ["T_ID"], "T", ["ID"]),
    ]
    roles = _infer_table_roles(edges, tds)
    assert roles["t"]["role"] == "unclassified"
    assert roles["t"]["as_target"] == 2
    assert roles["t"]["as_source"] == 2


def test_self_ref_excluded_from_degree():
    tds = [_td("EMPLOYEE", [_col("ID", pk=True), _col("MANAGER_ID", fk=True)])]
    edges = [_e("EMPLOYEE", ["MANAGER_ID"], "EMPLOYEE", ["ID"])]
    roles = _infer_table_roles(edges, tds)
    assert roles["employee"]["self_ref"] is True
    assert roles["employee"]["as_target"] == 0
    assert roles["employee"]["as_source"] == 0
    assert roles["employee"]["role"] == "unclassified"


def test_warehouse_inferred_only_likely_tier():
    # No verified FK (databricks/bigquery style) — inferred edges still classify,
    # but at the 'likely' confidence tier (H1 deliberate: inferred is the only signal).
    tds = [
        _td("SALES", [_col("SALE_ID", pk=True), _col("CUST_CODE"), _col("PROD_CODE")]),
        _td("CUST_DIM", [_col("CUST_CODE", pk=True)]),
        _td("PROD_DIM", [_col("PROD_CODE", pk=True)]),
    ]
    edges = [
        _e("SALES", ["CUST_CODE"], "CUST_DIM", ["CUST_CODE"], rel=REL_INFERRED_NAME),
        _e("SALES", ["PROD_CODE"], "PROD_DIM", ["PROD_CODE"], rel=REL_INFERRED_NAME),
    ]
    roles = _infer_table_roles(edges, tds)
    assert roles["sales"]["role"] == "fact"
    assert roles["sales"]["role_confidence"] == "likely"
    assert roles["cust_dim"]["role"] == "dimension"
    assert roles["cust_dim"]["role_confidence"] == "likely"


def test_truncated_forces_all_unclassified():
    tds = [
        _td("SALES", [_col("ID", pk=True), _col("CUST_ID", fk=True)]),
        _td("CUSTOMERS", [_col("CUST_ID", pk=True)]),
    ]
    edges = [_e("SALES", ["CUST_ID"], "CUSTOMERS", ["CUST_ID"])]
    roles = _infer_table_roles(edges, tds, truncated=True)
    assert all(r["role"] == "unclassified" for r in roles.values())


def test_build_struct_nodes_columns_edges():
    tds = [
        _td(
            "SALES",
            [
                _col("ID", pk=True),
                _col("CUST_ID", fk=True, ftable="CUSTOMERS", fcol="CUST_ID"),
            ],
        ),
        _td("CUSTOMERS", [_col("CUST_ID", pk=True)]),
    ]
    edges = [_e("SALES", ["CUST_ID"], "CUSTOMERS", ["CUST_ID"])]
    roles = _infer_table_roles(edges, tds)
    struct = build_join_graph_struct(
        edges, tds, roles, schema_map={"sales": "public", "customers": "public"}
    )
    assert {n["table"] for n in struct["nodes"]} == {"SALES", "CUSTOMERS"}
    sales = next(n for n in struct["nodes"] if n["table"] == "SALES")
    assert sales["column_count"] == 2
    assert sales["schema_name"] == "public"
    # struct builder propagates the computed role verbatim (single FK → not a fact)
    assert sales["role"] == roles["sales"]["role"]
    assert sales["as_source"] == 1
    fk_cols = [c for c in sales["columns"] if c["is_foreign_key"]]
    assert fk_cols and fk_cols[0]["foreign_table"] == "CUSTOMERS"
    assert len(struct["edges"]) == 1
    assert struct["edges"][0]["relationship_type"] == REL_VERIFIED_FK
