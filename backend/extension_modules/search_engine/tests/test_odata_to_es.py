"""Unit tests for OData → Elasticsearch query translation (P0 PR2 T2.2).

The ES adapter previously parsed only a single ``field eq value`` and silently
dropped every compound filter to ``match_all`` — a cross-collection leak, since
DbSphere memory always filters by ``collection eq <dbsphere_id> and entity_type
eq <type>``. ``translate_odata_to_es`` parses the full OData grammar (and/or/
parens, eq/ge/le) into a precise bool query so isolation filters are enforced.
"""

from __future__ import annotations

import pytest
from extension_modules.search_engine.filter_translator import translate_odata_to_es
from extension_modules.search_engine.models import ColumnInfo

COLS = [
    ColumnInfo(name="entity_type", type="string"),
    ColumnInfo(name="page_num", type="int32"),
]


def test_single_collection_eq_preserved():
    # The one case the old parser handled must keep working.
    assert translate_odata_to_es("collection eq 'abc'") == {
        "term": {"collection": "abc"}
    }


def test_compound_and_enforces_isolation():
    q = translate_odata_to_es(
        "collection eq 'db1' and entity_type eq 'sql_memory'", COLS
    )
    assert q == {
        "bool": {
            "filter": [
                {"term": {"collection": "db1"}},
                {"term": {"entity_type": "sql_memory"}},
            ]
        }
    }


def test_or_grouping():
    q = translate_odata_to_es("collection eq 'a' or collection eq 'b'")
    assert q == {
        "bool": {
            "should": [
                {"term": {"collection": "a"}},
                {"term": {"collection": "b"}},
            ],
            "minimum_should_match": 1,
        }
    }


def test_parenthesised_or_inside_and():
    q = translate_odata_to_es(
        "entity_type eq 'x' and (collection eq 'a' or collection eq 'b')", COLS
    )
    assert q == {
        "bool": {
            "filter": [
                {"term": {"entity_type": "x"}},
                {
                    "bool": {
                        "should": [
                            {"term": {"collection": "a"}},
                            {"term": {"collection": "b"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            ]
        }
    }


def test_range_ge_le():
    assert translate_odata_to_es("page_num ge 5", COLS) == {
        "range": {"page_num": {"gte": 5}}
    }
    assert translate_odata_to_es("page_num le 9", COLS) == {
        "range": {"page_num": {"lte": 9}}
    }


def test_compound_never_falls_back_to_match_all():
    # Regression guard for the leak: a compound filter must yield a precise
    # query, never match_all.
    q = translate_odata_to_es("collection eq 'db1' and entity_type eq 't'", COLS)
    assert "match_all" not in str(q)


def test_empty_returns_none():
    assert translate_odata_to_es("") is None
    assert translate_odata_to_es(None) is None
    assert translate_odata_to_es("   ") is None


def test_disallowed_field_raises():
    with pytest.raises(ValueError):
        translate_odata_to_es("secret eq 'x'")


def test_unparseable_raises():
    # Boolean/null literals (self-improving-memory's filters) are not yet
    # supported — they must raise (caller fails safe), not silently pass.
    with pytest.raises(ValueError):
        translate_odata_to_es(
            "is_shared eq true", [ColumnInfo(name="is_shared", type="string")]
        )


# ---------------------------------------------------------------------------
# Cross-collection leak via unescaped OData values (search_memory._odata_quote)
# ---------------------------------------------------------------------------

from extension_modules.dbsphere.memory.search_memory import _odata_quote  # noqa: E402

COLS_TABLE = [
    ColumnInfo(name="entity_type", type="string"),
    ColumnInfo(name="table_name", type="string"),
]

# A paren-balanced table_name that, unescaped, breaks out of the collection
# isolation filter with a top-level OR onto another DbSphere's collection.
_LEAK_PAYLOAD = "x') or collection eq 'victim_db' and (table_name eq 'y"


def _ddl_filter(dbsphere_id: str, names, *, escape: bool) -> str:
    """Reproduce search_memory's table-scoped DDL filter construction."""
    quote = _odata_quote if escape else (lambda v: v)
    conds = " or ".join(f"table_name eq '{quote(n)}'" for n in names)
    return (
        f"collection eq '{dbsphere_id}' and entity_type eq 'ddl_schema' and ({conds})"
    )


def _collection_terms(node) -> list:
    """Every ``collection`` term-value anywhere in the ES query tree."""
    out: list = []
    if isinstance(node, dict):
        if "term" in node and "collection" in node["term"]:
            out.append(node["term"]["collection"])
        for v in node.values():
            out.extend(_collection_terms(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_collection_terms(v))
    return out


def test_unescaped_table_name_leaks_foreign_collection():
    # Documents the attack: without escaping, the payload injects a foreign
    # collection branch — the cross-collection leak the fix closes.
    q = translate_odata_to_es(
        _ddl_filter("mydb", [_LEAK_PAYLOAD], escape=False), COLS_TABLE
    )
    assert "victim_db" in _collection_terms(q)


def test_odata_quote_blocks_cross_collection_leak():
    # The fix: _odata_quote doubles quotes so the payload is parsed as a single
    # literal table_name value — collection stays locked to the caller's id.
    q = translate_odata_to_es(
        _ddl_filter("mydb", [_LEAK_PAYLOAD], escape=True), COLS_TABLE
    )
    assert _collection_terms(q) == ["mydb"]
    assert _LEAK_PAYLOAD in str(q)
