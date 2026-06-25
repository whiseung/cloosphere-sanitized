"""Unit tests for ``parse_join_graph`` — markdown → edge rows (round-trip parity).

The relationship panel (#4) renders the SAME edges the agent sees by parsing the
persisted ``join_graph`` markdown. ``parse_join_graph(build_join_graph(rows))``
must reproduce ``rows`` (modulo ``evidence``, which the rendered view drops, and
the render-time inferred-vs-verified dedup) — that parity is what guarantees
panel == agent without a second stored representation.
"""

from __future__ import annotations

from extension_modules.dbsphere.memory.schema_extractor import (
    REL_INFERRED_NAME,
    REL_VERIFIED_FK,
    build_join_graph,
    parse_join_graph,
)


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


def _key(row):
    """Projection of the fields the markdown preserves (evidence is not)."""
    return (
        row["source_table"],
        tuple(row["source_columns"]),
        row["target_table"],
        tuple(row["target_columns"]),
        row["relationship_type"],
        row["confidence"],
    )


def test_parse_empty():
    assert parse_join_graph("") == []
    assert parse_join_graph(None) == []


def test_parse_verified_single():
    md = build_join_graph([_vrow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["ID"])])
    out = parse_join_graph(md)
    assert len(out) == 1
    assert _key(out[0]) == (
        "SALES",
        ("CUSTOMER_ID",),
        "CUSTOMERS",
        ("ID",),
        REL_VERIFIED_FK,
        1.0,
    )
    assert out[0]["evidence"] == []


def test_parse_composite_on():
    md = build_join_graph([_vrow("S", ["a", "b"], "T", ["x", "y"])])
    out = parse_join_graph(md)
    assert _key(out[0]) == ("S", ("a", "b"), "T", ("x", "y"), REL_VERIFIED_FK, 1.0)


def test_parse_inferred_candidate_label_stripped():
    md = build_join_graph([_irow("SALES", ["MATR_CODE"], "MATR", ["MATR_CODE"])])
    out = parse_join_graph(md)
    assert len(out) == 1
    assert out[0]["relationship_type"] == REL_INFERRED_NAME
    assert out[0]["confidence"] == 0.5
    assert out[0]["target_table"] == "MATR"  # " (candidate)" stripped


def test_roundtrip_mixed_no_dup():
    rows = [
        _vrow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["CUSTOMER_ID"]),
        _vrow("ORDERS", ["CUST_ID", "REGION"], "CUSTOMERS", ["ID", "REGION"]),
        _irow("SALES", ["MATR_CODE"], "MATR_MASTER", ["MATR_CODE"]),
    ]
    out = parse_join_graph(build_join_graph(rows))
    assert {_key(r) for r in out} == {_key(r) for r in rows}


def test_roundtrip_respects_render_dedup():
    # build_join_graph drops an inferred candidate that restates a verified FK;
    # the parser sees only what was rendered (parity with the agent's view).
    rows = [
        _vrow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["CUSTOMER_ID"]),
        _irow("SALES", ["CUSTOMER_ID"], "CUSTOMERS", ["CUSTOMER_ID"]),  # dropped
    ]
    out = parse_join_graph(build_join_graph(rows))
    assert len(out) == 1
    assert out[0]["relationship_type"] == REL_VERIFIED_FK


def test_parse_ignores_roles_section():
    # Forward-compat with follow-up B: a "### Roles" section must not be parsed
    # as edges (its "- Fact: X" lines are not relationship rows).
    md = build_join_graph([_vrow("S", ["a"], "T", ["x"])])
    md += "\n\n### Roles (inferred, structural)\n- Fact: S\n- Dimension: T"
    out = parse_join_graph(md)
    assert len(out) == 1
    assert _key(out[0]) == ("S", ("a",), "T", ("x",), REL_VERIFIED_FK, 1.0)
