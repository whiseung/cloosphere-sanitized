"""SQL statement classifier — READ vs WRITE.

DbSphere SQL Editor 의 `Allow data modifications` 토글 게이트에 쓰이는 분류기.
사용자가 직접 입력한 SQL을 실행하기 전에 READ / WRITE / UNKNOWN / INVALID 로
분류한다.

기존 `extension_modules/dbsphere/tools/run_sql.py::_first_keyword` 는 agent 흐름
에서 LLM 이 tool 이름을 골라 호출하는 구조라 컨텐츠 기반 가드가 필요 없었지만,
직접 실행 경로 (`POST /api/v1/dbsphere/{id}/sql/execute`) 는 컨텐츠 기반 분류
필수.

설계 결정:
- sqlglot / sqlparse 같은 풀 파서는 50MB+ 의존성, 1차 도입 비용 큼.
- 첫 키워드 + deny-list regex 조합으로 99% 의 WRITE 케이스를 잡는다.
- 잡지 못하는 케이스 (예: 동적 SQL, 저장 프로시저 내부 변경) 는 connection-
  level 권한 (read-only DB user) 으로 막는 것이 정석. 분류기는 defense-in-depth.

분류 결과:
- READ : 안전한 조회. 즉시 실행.
- WRITE : DML/DDL/저장프로시저. allow_data_modifications=True + 사용자 승인 필요.
- UNKNOWN : 분류 불가. allow_data_modifications=True 일 때 WRITE 취급 (보수적).
            False 일 때는 라우터가 차단.
- INVALID : 빈 입력 / 다중 statement. 라우터가 400.
"""

import re
from enum import Enum


class StmtClass(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


_READ_KEYWORDS = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}

# WRITE 키워드 — DML + DDL + DCL + 저장 프로시저 호출.
# `CALL` / `EXEC` / `EXECUTE` / `DO` 도 포함 (저장 프로시저 / 익명 코드 블록은
# 내부에서 무엇이든 할 수 있음 — 보수적으로 WRITE).
_WRITE_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "REPLACE",
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "COMMENT",
    "CALL",
    "EXEC",
    "EXECUTE",
    "DO",
}

# Deny-list — 첫 키워드는 READ 로 보이지만 실제로는 DML 을 실행하는 패턴.
# 이 패턴이 매치되면 분류 결과를 WRITE 로 강제한다.
_DENY_WRITE_PATTERNS = [
    # PostgreSQL: `EXPLAIN ANALYZE <DML>` 가 실제로 DML 을 실행한다 (`SELECT` 는 안전).
    # 옵션 형태도 커버: `EXPLAIN (ANALYZE, VERBOSE) <DML>`
    re.compile(
        r"^\s*EXPLAIN\s+"
        r"(?:\([^)]*\bANALYZE\b[^)]*\)|ANALYZE\b)"
        r"\s+(INSERT|UPDATE|DELETE|MERGE|REPLACE|CREATE|ALTER|DROP|TRUNCATE)\b",
        re.IGNORECASE,
    ),
    # PostgreSQL: CTE 내부 DML — `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x`
    # `WITH ... AS (INSERT|UPDATE|DELETE|MERGE` 패턴.
    re.compile(
        r"^\s*WITH\b[^;]*?\bAS\s*\(\s*(INSERT|UPDATE|DELETE|MERGE)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # CTE-then-DML — `WITH cte AS (SELECT ...) DELETE FROM t ...`. 위 AS(...) 패턴은
    # CTE *내부* DML 만 잡고, DML 이 CTE 정의 뒤의 main statement 인 경우를 놓친다.
    # WITH 로 시작하는 문에 DML signature 가 나타나면 보수적으로 WRITE.
    re.compile(
        r"^\s*WITH\b[\s\S]*?\b"
        r"(DELETE\s+FROM|INSERT\s+INTO|MERGE\s+INTO|UPDATE\s+[^\s;]+\s+SET)\b",
        re.IGNORECASE,
    ),
    # `SELECT ... INTO <newtable> FROM ...` — SQL Server/PostgreSQL 테이블 생성(write).
    # 대상 식별자는 따옴표("a b")·대괄호([a b])·#temp·@var·schema.qual 형태가 가능하므로
    # 이름 토큰을 FROM 앵커에서 분리한다(ident 시작 문자만 고정, 이후는 FROM 까지 lazy).
    re.compile(
        r"^\s*SELECT\b[\s\S]*?\bINTO\s+(?:[\"\[#@]|\w)[\s\S]*?\bFROM\b",
        re.IGNORECASE,
    ),
    # `SELECT ... INTO OUTFILE|DUMPFILE` — MySQL 파일 쓰기(write).
    re.compile(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", re.IGNORECASE),
]


def _strip_comments(sql: str) -> str:
    """라인 / 블록 코멘트 제거. 키워드 탐지 신뢰성 확보."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _first_keyword(sql: str) -> str:
    stripped = _strip_comments(sql).strip()
    parts = stripped.upper().split(maxsplit=1)
    return parts[0] if parts else ""


def _is_multi_statement(sql: str) -> bool:
    """단순 휴리스틱: 코멘트 제거 후 세미콜론으로 split 했을 때 의미 있는
    chunk 가 2개 이상이면 multi-statement. 문자열 리터럴 안 세미콜론은 일반적
    SQL 에서 드물지만 100% 정확하진 않다. 1차는 보수적으로 reject."""
    stripped = _strip_comments(sql).strip()
    # PG `DO $$ ... $$` 등 dollar-quoted body 안 세미콜론은 별개. 단 첫 키워드가
    # DO 면 이미 WRITE 로 분류되어 multi-statement 검사 도달 전에 종료.
    chunks = [c.strip() for c in stripped.split(";") if c.strip()]
    return len(chunks) > 1


def classify_statement(sql: str) -> StmtClass:
    """단일 SQL statement 를 분류.

    Multi-statement (`;` 로 구분된 2개 이상) 는 1차 미지원 — INVALID 가 아닌
    UNKNOWN 으로 반환해서 라우터가 명시적인 에러 메시지로 답할 수 있게 한다.

    빈/공백 / 코멘트만 있는 입력은 INVALID.
    """
    if not sql or not sql.strip():
        return StmtClass.INVALID

    stripped = _strip_comments(sql).strip()
    if not stripped:
        return StmtClass.INVALID

    # 1) 명시적 deny-list 가 먼저 — `EXPLAIN ANALYZE DELETE` 같이 READ-looking WRITE.
    for pat in _DENY_WRITE_PATTERNS:
        if pat.search(stripped):
            return StmtClass.WRITE

    # 2) 첫 키워드 룩업.
    first = _first_keyword(stripped)

    # 3) DO 블록은 dollar-quoted body 내부에 세미콜론이 허용됨 — multi-statement
    #    검사를 우회하고 즉시 WRITE 로 분류 (저장 프로시저와 동격).
    if first == "DO":
        return StmtClass.WRITE

    # 4) Multi-statement reject — DO 가 아닌 SQL 에 한해서 단순 ; split 휴리스틱.
    if _is_multi_statement(sql):
        return StmtClass.UNKNOWN

    if first in _WRITE_KEYWORDS:
        return StmtClass.WRITE
    if first in _READ_KEYWORDS:
        return StmtClass.READ
    return StmtClass.UNKNOWN
