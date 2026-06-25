"""kg_cypher 안전 검증/리라이팅 회귀 fixture.

`cypher_safety` 모듈의 모든 정책을 케이스로 굳힘. 새 정책 추가 시 fixture 도
함께 늘려서 regression coverage 유지.
"""

from __future__ import annotations

import pytest
from extension_modules.knowledge_graph.cypher_safety import (
    CypherSafetyError,
    extract_referenced_types,
    friendly_error,
    inject_limit,
    validate_cypher,
    validate_identifier,
)

# ── 1. 허용되어야 하는 read-only 쿼리 ────────────────────────────────────────


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) RETURN n LIMIT 10",
        "MATCH (n:term) RETURN n.label",
        "MATCH (n:term)-[r:synonym_of]->(m) RETURN n, r, m",
        "OPTIONAL MATCH (n:term {label: 'Aspirin'}) RETURN n",
        "MATCH (n) WITH n WHERE n.label IS NOT NULL RETURN count(n)",
        "UNWIND [1,2,3] AS x RETURN x",
        "MATCH (n) RETURN n ORDER BY n.label DESC",
        "MATCH (n) WHERE n.label STARTS WITH '아' RETURN n",
        "MATCH (n)-[r]-(m) WHERE type(r) IN ['has_active_ingredient', 'mentions'] RETURN n, m",
    ],
)
def test_validate_allows_read_only(cypher):
    validate_cypher(cypher)  # raise 안 하면 통과


# ── 2. 거부되어야 하는 write/side-effect 쿼리 ───────────────────────────────


@pytest.mark.parametrize(
    "cypher,expected_substring",
    [
        ("CREATE (n:Foo) RETURN n", "CREATE"),
        ("MATCH (n) DELETE n", "DELETE"),
        ("MATCH (n) DETACH DELETE n", "DETACH"),
        ("MERGE (n:Foo {x: 1}) RETURN n", "MERGE"),
        ("MATCH (n) SET n.label = 'x' RETURN n", "SET"),
        ("MATCH (n) REMOVE n.x RETURN n", "REMOVE"),
        ("DROP TABLE foo", "DROP"),
        ("CALL db.labels()", "CALL"),
        ("USE mygraph MATCH (n) RETURN n", "USE"),
        ("LOAD CSV FROM 'x' AS row RETURN row", "LOAD"),
        ("MATCH (n) FOREACH (x IN [1,2] | SET n.y = x) RETURN n", "FOREACH"),
    ],
)
def test_validate_rejects_writes(cypher, expected_substring):
    with pytest.raises(CypherSafetyError) as exc:
        validate_cypher(cypher)
    assert expected_substring in str(exc.value)


# ── 3. AGE edge alternation 거부 ───────────────────────────────────────────


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n)-[:A|B]->(m) RETURN n, m",
        "MATCH (n)-[:has_active_ingredient|mentions]->(m) RETURN n, m",
        "MATCH (n)-[r:A|B|C]->(m) RETURN n, r, m",
        "MATCH (n)-[:A | B]->(m) RETURN n, m",  # 공백 포함
    ],
)
def test_validate_rejects_alternation(cypher):
    with pytest.raises(CypherSafetyError) as exc:
        validate_cypher(cypher)
    assert "alternation" in str(exc.value).lower()


# ── 4. 다중 statement 거부 ─────────────────────────────────────────────────


def test_validate_rejects_multiple_statements():
    with pytest.raises(CypherSafetyError) as exc:
        validate_cypher("MATCH (n) RETURN n; MATCH (m) RETURN m")
    assert "multiple statements" in str(exc.value).lower()


# ── 5. 길이 제한 ──────────────────────────────────────────────────────────


def test_validate_rejects_oversized():
    huge = "MATCH (n) WHERE n.label = '" + "x" * 5000 + "' RETURN n"
    with pytest.raises(CypherSafetyError) as exc:
        validate_cypher(huge)
    assert "length" in str(exc.value).lower()


def test_validate_rejects_empty():
    with pytest.raises(CypherSafetyError):
        validate_cypher("")
    with pytest.raises(CypherSafetyError):
        validate_cypher("   \n  ")


# ── 6. 문자열 리터럴 안의 키워드는 오탐하지 않아야 함 ───────────────────────


def test_validate_does_not_falseflag_keywords_in_strings():
    # CREATE 가 문자열 안에 있을 뿐
    validate_cypher("MATCH (n) WHERE n.note = 'CREATE flag' RETURN n")
    validate_cypher('MATCH (n) WHERE n.note = "this DELETE that" RETURN n')


def test_validate_does_not_falseflag_keywords_in_comments():
    validate_cypher(
        """MATCH (n)
        // CREATE this is just a comment
        RETURN n"""
    )
    validate_cypher("MATCH (n) /* CREATE in block comment */ RETURN n")


# ── 7. LIMIT 자동 주입 ─────────────────────────────────────────────────────


def test_inject_limit_appends_when_missing():
    out = inject_limit("MATCH (n) RETURN n", default_limit=50)
    assert out.endswith("LIMIT 50")


def test_inject_limit_keeps_existing_limit():
    cypher = "MATCH (n) RETURN n LIMIT 5"
    assert inject_limit(cypher) == cypher


def test_inject_limit_with_order_by():
    out = inject_limit("MATCH (n) RETURN n ORDER BY n.label", default_limit=50)
    assert out.endswith("LIMIT 50")
    assert "ORDER BY" in out


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) RETURN count(n)",
        "MATCH (n) RETURN count(*)",
        "MATCH (n) RETURN sum(n.x), avg(n.y)",
        "MATCH (n) RETURN DISTINCT count(n)",
    ],
)
def test_inject_limit_skips_pure_aggregate(cypher):
    assert inject_limit(cypher) == cypher  # 변경 없음


def test_inject_limit_applies_to_mixed_aggregate_and_field():
    # count() 와 일반 필드가 섞이면 aggregate-only 가 아니므로 LIMIT 부착
    cypher = "MATCH (n) RETURN n.label, count(n)"
    out = inject_limit(cypher, default_limit=10)
    assert out.endswith("LIMIT 10")


def test_inject_limit_handles_trailing_semicolon_strip():
    # 다중 statement 는 validate 에서 reject 되지만, inject_limit 은 최후 보호로
    # 끝 세미콜론을 제거하고 LIMIT 부착.
    out = inject_limit("MATCH (n) RETURN n;", default_limit=50)
    assert "RETURN n LIMIT 50" in out


# ── 8. friendly_error 매핑 ────────────────────────────────────────────────


def test_friendly_error_alternation_hint():
    raw = 'syntax error at or near "|"'
    out = friendly_error(raw)
    assert "alternation" in out.lower()
    assert "type(r) IN" in out


def test_friendly_error_function_not_exist_hint():
    raw = "function apoc.foo() does not exist"
    out = friendly_error(raw)
    assert "subset" in out.lower() or "apoc" in out.lower()


def test_friendly_error_passthrough_when_unknown():
    raw = "some random error"
    assert friendly_error(raw) == raw


def test_friendly_error_order_by_alias_hint():
    # AGE 가 RETURN alias 를 ORDER BY 에서 인식 못 할 때의 PostgreSQL 에러
    raw = "could not find rte for medication\nLINE 6: ORDER BY medication ..."
    out = friendly_error(raw)
    assert "ORDER BY" in out
    assert "alias" in out.lower()
    assert "n.label" in out or "WITH" in out


def test_friendly_error_undefined_column_with_order_by():
    raw = "psycopg2.errors.UndefinedColumn: column 'drug_name' ... ORDER BY drug_name"
    out = friendly_error(raw)
    assert "ORDER BY" in out
    assert "alias" in out.lower()


# ── 9. Identifier validation ──────────────────────────────────────────────


def test_validate_identifier_accepts_ascii():
    validate_identifier("term")
    validate_identifier("has_active_ingredient")
    validate_identifier("_private")


@pytest.mark.parametrize(
    "bad",
    [
        "1starts_with_digit",
        "has-hyphen",
        "has space",
        "한글라벨",
        "x;DROP",
        "",
    ],
)
def test_validate_identifier_rejects_bad(bad):
    with pytest.raises(CypherSafetyError):
        validate_identifier(bad)


# ── 10. extract_referenced_types ──────────────────────────────────────────


def test_extract_referenced_types_simple():
    nodes, edges = extract_referenced_types(
        "MATCH (n:term)-[r:has_active_ingredient]->(m:term) RETURN n, m"
    )
    assert nodes == {"term"}
    assert edges == {"has_active_ingredient"}


def test_extract_referenced_types_anonymous_node():
    nodes, edges = extract_referenced_types(
        "MATCH (:term)-[:mentions]->(:document) RETURN 1"
    )
    assert nodes == {"term", "document"}
    assert edges == {"mentions"}


def test_extract_referenced_types_no_labels():
    # 변수만 쓰고 라벨 없는 경우 — 보수적으로 빈 set
    nodes, edges = extract_referenced_types("MATCH (n)-[r]-(m) RETURN n, m")
    assert nodes == set()
    assert edges == set()
