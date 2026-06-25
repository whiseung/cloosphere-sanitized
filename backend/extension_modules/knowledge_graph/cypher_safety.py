"""KG `kg_cypher` 도구의 read-only Cypher 안전 검증/리라이팅 유틸.

LLM 이 자유롭게 짠 Cypher 문자열을 AGE 에 그대로 보내면 (a) 쓰기 절로 그래프
손상, (b) AGE 의 부분 openCypher 지원으로 인한 cryptic syntax error, (c) 무한
루프성 트래버설로 DoS 가 발생할 수 있다. 이 모듈은 그 입력을 `safe_execute_cypher`
호출 전에 파이프로 흘려 안전한 형태로 만든다.

순수 함수만 모음 — DB / 파일 I/O 없음. 따라서 단위 테스트가 결정론적.
"""

from __future__ import annotations

import re
from typing import Iterable

# ── Public exceptions ──────────────────────────────────────────────────────


class CypherSafetyError(ValueError):
    """LLM 이 보낸 Cypher 가 안전 정책에 위반될 때 raise.

    메시지는 그대로 LLM 에 retry context 로 전달되므로 어떤 규칙을 어떻게 고치면
    되는지 명시적으로 적는다.
    """


# ── 정책 상수 ──────────────────────────────────────────────────────────────

# 허용 키워드 (대소문자 무시). 이 외 top-level 키워드는 reject.
ALLOWED_KEYWORDS: frozenset[str] = frozenset(
    {
        "MATCH",
        "OPTIONAL",  # OPTIONAL MATCH
        "WITH",
        "RETURN",
        "UNWIND",
        "WHERE",
        "ORDER",  # ORDER BY
        "BY",
        "LIMIT",
        "SKIP",
        "DISTINCT",
        "AS",
        "AND",
        "OR",
        "NOT",
        "IN",
        "IS",
        "NULL",
        "TRUE",
        "FALSE",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "ASC",
        "DESC",
        "EXISTS",
        "STARTS",  # STARTS WITH
        "ENDS",  # ENDS WITH
        "CONTAINS",
        "XOR",
        "ALL",
        "ANY",
        "NONE",
        "SINGLE",
        "TYPE",  # type(r)
    }
)

# 명시적으로 거부되는 키워드 (쓰기/Side-effect 동반).
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        "CREATE",
        "MERGE",
        "DELETE",
        "DETACH",
        "SET",
        "REMOVE",
        "DROP",
        "CALL",
        "USE",
        "LOAD",
        "FOREACH",
        "START",  # 구버전 Cypher
        "COMMIT",
        "ROLLBACK",
    }
)

# Cypher 식별자 (라벨/property key) 정규식. ASCII 영숫자 + 언더스코어.
# AGE 는 한글 라벨도 받을 수 있지만 LLM 이 quoting 을 자주 틀려서 ASCII 만 허용.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Edge alternation 패턴. AGE 미지원 — 친절한 hint 함께 reject.
_EDGE_ALTERNATION_RE = re.compile(
    r"\[\s*[A-Za-z_]?\s*:\s*[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\s*\|\s*:?\s*[A-Za-z_][A-Za-z0-9_]*)+",
)

# 마지막 RETURN 절 추출 (순수 aggregate 판별용).
# 문자열 리터럴 제거 후 적용해야 'RETURN' 단어 오탐을 막음.
_RETURN_TAIL_RE = re.compile(
    r"(?<![A-Za-z_])RETURN\s+(.+?)$",
    re.I | re.S,
)

# Aggregate 함수 이름 (이것만으로 RETURN 이 채워지면 LIMIT 부착 안 함).
_AGGREGATE_FUNCS: frozenset[str] = frozenset(
    {"count", "sum", "avg", "min", "max", "collect", "stdev", "percentilecont"}
)
_AGGREGATE_HEAD_RE = re.compile(
    r"^\s*(?:DISTINCT\s+)?(\w+)\s*\(",
    re.I,
)

# 결과 길이 / 쿼리 길이 cap.
MAX_CYPHER_LENGTH = 4000

# ── Helpers ────────────────────────────────────────────────────────────────


def tokenize_strip_strings(cypher: str) -> str:
    """문자열 리터럴, 라인 주석, 블록 주석을 빈/공백으로 치환한다.

    이후 keyword 검사가 문자열 안의 'CREATE' 같은 우연한 단어에 오탐하지 않도록
    하기 위함. 위치/길이는 보존해서 에러 메시지에 영향 없도록.
    """
    # 작은따옴표 문자열
    s = re.sub(r"'(?:[^'\\]|\\.)*'", lambda m: " " * len(m.group(0)), cypher)
    # 큰따옴표 문자열 (Cypher 표준은 single quote 지만 AGE 가 받기도 함)
    s = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: " " * len(m.group(0)), s)
    # 블록 주석 /* ... */
    s = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), s, flags=re.S)
    # 라인 주석 // ...
    s = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), s)
    return s


def _top_level_words(stripped: str) -> Iterable[str]:
    """문자열/주석이 제거된 Cypher 에서 단어 토큰만 yield (대문자화 후)."""
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped):
        yield tok.upper()


# ── Main API ──────────────────────────────────────────────────────────────


def validate_cypher(cypher: str) -> None:
    """안전 정책 위반 시 CypherSafetyError raise. 합격이면 None.

    검사 순서가 중요: 길이 → 다중 statement → forbidden 키워드 → alternation →
    식별자 → 미지원 절. 친절한 메시지를 위해 첫 발견 시점에 즉시 raise.
    """
    if not cypher or not cypher.strip():
        raise CypherSafetyError("Empty Cypher query.")

    if len(cypher) > MAX_CYPHER_LENGTH:
        raise CypherSafetyError(
            f"Cypher length {len(cypher)} exceeds limit {MAX_CYPHER_LENGTH}. "
            f"Tighten the query or split it."
        )

    stripped = tokenize_strip_strings(cypher)

    # 다중 statement 차단 (literal 안의 ';' 은 strip 단계에서 제거됨)
    if ";" in stripped:
        raise CypherSafetyError(
            "Multiple statements are not allowed. Submit one Cypher per call."
        )

    # Forbidden keywords (쓰기 절)
    for word in _top_level_words(stripped):
        if word in FORBIDDEN_KEYWORDS:
            raise CypherSafetyError(
                f"Write/side-effect clause `{word}` is not allowed. "
                f"kg_cypher is read-only — use only "
                f"MATCH/OPTIONAL MATCH/WITH/RETURN/UNWIND/WHERE/ORDER BY/LIMIT/SKIP."
            )

    # Edge alternation
    if _EDGE_ALTERNATION_RE.search(stripped):
        raise CypherSafetyError(
            "AGE does not support edge type alternation `[:A|B]`. "
            "Rewrite as `[r]` followed by `WHERE type(r) IN ['A','B']`."
        )

    # 호출 같은 패턴 (CALL 은 위에서 forbidden 으로 잡지만 procedure invoke 형태도)
    if re.search(r"\bCALL\b\s*\(", stripped, re.I):
        raise CypherSafetyError(
            "Procedure calls are not supported on AGE. Use vanilla Cypher patterns."
        )


def inject_limit(cypher: str, default_limit: int = 100) -> str:
    """마지막 RETURN 절에 LIMIT 가 없고 순수 aggregate 가 아니면 LIMIT N 부착.

    - `RETURN count(*)` 같은 단일-aggregate 는 LIMIT 무의미 → 그대로 둠
    - `RETURN n LIMIT 5` 처럼 이미 LIMIT 있으면 그대로
    - `RETURN n` → `RETURN n LIMIT N` 으로 변환
    - `RETURN n ORDER BY ...` → `RETURN n ORDER BY ... LIMIT N`

    문자열 리터럴 안의 RETURN/LIMIT 키워드는 strip 후 검사.
    """
    if default_limit <= 0:
        raise ValueError("default_limit must be positive")

    stripped = tokenize_strip_strings(cypher)

    # 이미 LIMIT 가 있으면 그대로 (여러 LIMIT 가능 — `WITH ... LIMIT 5 RETURN ...` 등)
    # 마지막 RETURN 이후의 LIMIT 만 본다.
    return_match = _RETURN_TAIL_RE.search(stripped)
    if not return_match:
        # RETURN 자체가 없는 쿼리 (UNWIND ... 만 있는 경우 등) — 그대로 통과
        return cypher

    return_tail = return_match.group(1)
    if re.search(r"(?<![A-Za-z_])LIMIT\s+\d+", return_tail, re.I):
        return cypher

    # RETURN 직후 첫 expression 이 aggregate 함수 호출인지 검사
    if _is_pure_aggregate_return(return_tail):
        return cypher

    # LIMIT 부착. 원본 cypher 에 직접 부착해야 string literal 보존.
    return cypher.rstrip().rstrip(";") + f" LIMIT {default_limit}"


def _is_pure_aggregate_return(return_tail: str) -> bool:
    """RETURN 절이 aggregate 함수 호출만으로 이루어지는지 판정.

    다음과 같이 단순 휴리스틱: top-level 콤마로 split → 각 항목이 (DISTINCT)
    `func(...)` 형태이고 func 가 aggregate 집합에 속하면 True.
    """
    # ORDER BY / LIMIT / SKIP 뒤는 잘라냄
    head_match = re.split(
        r"(?<![A-Za-z_])(?:ORDER\s+BY|LIMIT|SKIP)\b",
        return_tail,
        maxsplit=1,
        flags=re.I,
    )
    head = head_match[0]

    # top-level comma split
    items: list[str] = []
    depth = 0
    cur = []
    for ch in head:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        items.append("".join(cur))

    if not items:
        return False

    for item in items:
        m = _AGGREGATE_HEAD_RE.match(item)
        if not m or m.group(1).lower() not in _AGGREGATE_FUNCS:
            return False
    return True


def friendly_error(error_msg: str) -> str:
    """AGE / psycopg2 에러 메시지를 LLM 이 fix 하기 쉬운 hint 로 매핑.

    원본 에러를 그대로 두고 끝에 `Hint:` 를 append. 매칭 실패 시 원본 그대로.
    """
    msg = error_msg or ""
    lower = msg.lower()

    hints: list[str] = []

    if "syntax error" in lower and "|" in msg:
        hints.append(
            "Edge alternation `[:A|B]` is not supported by AGE. "
            "Rewrite using `[r]` + `WHERE type(r) IN ['A','B']`."
        )
    if "function" in lower and "does not exist" in lower:
        hints.append(
            "AGE supports only a subset of Cypher functions; "
            "`apoc.*` and many built-ins are unavailable. Try a vanilla equivalent."
        )
    if "agtype" in lower and ("parse" in lower or "cannot" in lower):
        hints.append(
            "Complex RETURN expressions can produce unparseable agtype. "
            "Project explicit fields with aliases (e.g. `RETURN n.label AS label`)."
        )
    if "relation" in lower and "does not exist" in lower:
        hints.append(
            "The AGE graph for this KG may not exist yet. "
            "Confirm `kg_id` is valid and the graph has been created."
        )
    # `RETURN ... AS x ORDER BY x` 패턴은 AGE 가 alias 를 ORDER BY 에서 인식 못 해
    # PostgreSQL UndefinedColumn (`could not find rte for x`) 으로 떨어진다.
    # 관찰 결과 매 cypher 호출의 ~37% 가 이 함정에 첫 시도 실패하므로 LLM 에
    # 명확한 fix 패턴을 제공한다.
    if "could not find rte" in lower or (
        "undefinedcolumn" in lower and "order by" in lower
    ):
        hints.append(
            "AGE does not recognize RETURN aliases inside ORDER BY. "
            "Use the underlying expression instead of the alias "
            "(`ORDER BY n.label` not `ORDER BY medication`), "
            "or rebind first with `WITH n.label AS x ... RETURN x ORDER BY x`."
        )
    if "syntax error" in lower and not hints:
        hints.append(
            "Syntax error from AGE. Note: AGE supports only a subset of openCypher "
            "(no edge alternation, no CALL, no apoc functions)."
        )

    if not hints:
        return msg
    return f"{msg}\n\nHint: {' '.join(hints)}"


def extract_referenced_types(cypher: str) -> tuple[set[str], set[str]]:
    """Cypher 가 참조하는 (node_labels, edge_types) 집합을 추출.

    드리프트 처리용 — 메모리 row 의 metadata 에 저장해서 KG sync 시 사라진
    label/edge_type 을 참조하는 entry 를 stale 마킹할 수 있게 한다.

    완전한 파싱이 아니라 휴리스틱 정규식: `(:Label)` `[:EDGE]` 패턴만 잡는다.
    LLM 이 라벨 없이 변수만 쓰는 case 는 추출 결과에 포함되지 않음 (보수적 OK).
    """
    stripped = tokenize_strip_strings(cypher)

    node_labels: set[str] = set()
    for m in re.finditer(
        r"\(\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", stripped
    ):
        node_labels.add(m.group(1))
    # 변수 없이 (:Label)
    for m in re.finditer(r"\(\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", stripped):
        node_labels.add(m.group(1))

    edge_types: set[str] = set()
    for m in re.finditer(r"\[\s*[A-Za-z_]?\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", stripped):
        edge_types.add(m.group(1))

    return node_labels, edge_types


def validate_identifier(identifier: str, kind: str = "identifier") -> None:
    """LLM 입력 라벨/property 키 검증. ASCII 영숫자 + underscore 만.

    cypher 내부에 직접 인용되는 식별자에는 quote 가 안 붙으므로 injection 방지를
    위해 호출자가 별도로 검증해야 함. 위반 시 CypherSafetyError raise.
    """
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.match(identifier):
        raise CypherSafetyError(
            f"Invalid {kind} `{identifier}`. Must match `[A-Za-z_][A-Za-z0-9_]*`."
        )
