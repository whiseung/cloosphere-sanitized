"""
Search Engine - OData → SQL 안전 변환기

OData 필터 문자열을 파라미터 바인딩된 안전한 SQL WHERE 절로 변환합니다.
SQL 인젝션을 방지하기 위해 모든 값은 $N 파라미터로 바인딩됩니다.

지원하는 OData 패턴:
- eq (문자열, 정수, 날짜): field eq 'value', field eq 123
- ge/le (날짜/정수 범위): field ge value and field le value
- and/or 결합: A and B, (A or B)
- 괄호 그룹: (collection eq 'a' or collection eq 'b')

필드 매핑 규칙:
- 'collection' → collection 컬럼 (직접 매칭)
- column_info에 정의된 필드 → metadata->>'{field}' (JSONB 추출)
- 정수 비교 시 → (metadata->>'{field}')::int
- 날짜 비교 시 → (metadata->>'{field}')::timestamptz
"""

import logging
import re
from typing import Any, List, Optional, Tuple

from .models import ColumnInfo

log = logging.getLogger(__name__)

# 직접 컬럼 매핑되는 필드 (JSONB metadata에서 추출하지 않음)
DIRECT_COLUMNS = {"collection"}

# 허용 연산자
ODATA_TO_SQL_OP = {
    "eq": "=",
    "ge": ">=",
    "le": "<=",
}

# OData 토큰 정규식
_TOKEN_RE = re.compile(
    r"""
    \(                         |  # 여는 괄호
    \)                         |  # 닫는 괄호
    '(?:[^']|'')*'             |  # 작은따옴표 문자열 (이스케이프된 '' 포함)
    \b(?:and|or|eq|ge|le)\b    |  # 키워드
    [A-Za-z_]\w*               |  # 식별자 (필드명)
    -?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z  |  # ISO 날짜
    -?\d+                      |  # 정수
    \S+                           # 기타 (에러 감지용)
    """,
    re.VERBOSE,
)


def translate_odata_to_sql(
    filter_expr: Optional[str],
    column_info: Optional[List[ColumnInfo]] = None,
) -> Tuple[str, List[Any]]:
    """
    OData 필터 표현식을 안전한 파라미터 바인딩 SQL WHERE 절로 변환.

    Args:
        filter_expr: OData 필터 문자열 (None 또는 빈 문자열이면 빈 결과 반환)
        column_info: 허용된 필드 정의 리스트 (None이면 collection만 허용)

    Returns:
        Tuple[str, List[Any]]: (SQL WHERE 절, 파라미터 리스트)

    Raises:
        ValueError: 허용되지 않은 필드명 또는 잘못된 구문

    Examples:
        >>> translate_odata_to_sql("collection eq 'x'", [])
        ("collection = $1", ['x'])

        >>> cols = [ColumnInfo(name="entity_type", type="string")]
        >>> translate_odata_to_sql("collection eq 'x' and entity_type eq 'y'", cols)
        ("collection = $1 AND metadata->>'entity_type' = $2", ['x', 'y'])

        >>> cols = [ColumnInfo(name="f_int_1", type="int32")]
        >>> translate_odata_to_sql("f_int_1 eq 2024", cols)
        ("(metadata->>'f_int_1')::int = $1", [2024])
    """
    if not filter_expr or not filter_expr.strip():
        return "", []

    # 허용 필드 목록 구성
    allowed_fields = set(DIRECT_COLUMNS)
    field_types = {}
    if column_info:
        for col in column_info:
            allowed_fields.add(col.name)
            field_types[col.name] = col.type

    # 토큰화
    tokens = _tokenize(filter_expr)
    if not tokens:
        return "", []

    # 파서 상태
    ctx = _ParseContext(tokens, allowed_fields, field_types)
    sql = _parse_or_expr(ctx)

    if ctx.pos < len(ctx.tokens):
        raise ValueError(
            f"Unexpected token at position {ctx.pos}: '{ctx.tokens[ctx.pos]}'"
        )

    return sql, ctx.params


def _tokenize(expr: str) -> List[str]:
    """OData 필터 문자열을 토큰 리스트로 분리"""
    return _TOKEN_RE.findall(expr)


class _ParseContext:
    """파서 상태"""

    def __init__(
        self,
        tokens: List[str],
        allowed_fields: set,
        field_types: dict,
    ):
        self.tokens = tokens
        self.pos = 0
        self.params: List[Any] = []
        self.allowed_fields = allowed_fields
        self.field_types = field_types

    def peek(self) -> Optional[str]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, expected: str) -> str:
        token = self.peek()
        if token != expected:
            raise ValueError(f"Expected '{expected}', got '{token}' at pos {self.pos}")
        return self.advance()

    def add_param(self, value: Any) -> str:
        """파라미터를 추가하고 $N 자리표시자를 반환"""
        self.params.append(value)
        return f"${len(self.params)}"


def _parse_or_expr(ctx: _ParseContext) -> str:
    """OR 결합 파싱: expr (or expr)*"""
    left = _parse_and_expr(ctx)

    while ctx.peek() == "or":
        ctx.advance()
        right = _parse_and_expr(ctx)
        left = f"{left} OR {right}"

    return left


def _parse_and_expr(ctx: _ParseContext) -> str:
    """AND 결합 파싱: expr (and expr)*"""
    left = _parse_primary(ctx)

    while ctx.peek() == "and":
        ctx.advance()
        right = _parse_primary(ctx)
        left = f"{left} AND {right}"

    return left


def _parse_primary(ctx: _ParseContext) -> str:
    """괄호 그룹 또는 비교 연산 파싱"""
    token = ctx.peek()

    if token == "(":
        ctx.advance()
        expr = _parse_or_expr(ctx)
        ctx.expect(")")
        return f"({expr})"

    return _parse_comparison(ctx)


def _parse_comparison(ctx: _ParseContext) -> str:
    """비교 연산 파싱: field op value"""
    # 필드명
    field = ctx.advance()

    if field not in ctx.allowed_fields:
        raise ValueError(
            f"Field '{field}' not allowed. Allowed fields: {ctx.allowed_fields}"
        )

    # 연산자
    op_token = ctx.advance()
    if op_token not in ODATA_TO_SQL_OP:
        raise ValueError(
            f"Unsupported operator '{op_token}'. Supported: {list(ODATA_TO_SQL_OP.keys())}"
        )
    sql_op = ODATA_TO_SQL_OP[op_token]

    # 값
    raw_value = ctx.advance()
    value = _parse_value(raw_value)

    # SQL 필드 참조 생성
    field_type = ctx.field_types.get(field, "string")
    sql_field = _build_sql_field(field, field_type, value)

    # 파라미터 바인딩
    placeholder = ctx.add_param(value)

    return f"{sql_field} {sql_op} {placeholder}"


def _parse_value(raw: str) -> Any:
    """토큰 값을 Python 타입으로 변환"""
    # 문자열 리터럴
    if raw.startswith("'") and raw.endswith("'"):
        # OData 이스케이프 해제: '' → '
        return raw[1:-1].replace("''", "'")

    # ISO 날짜
    if re.match(r"^-?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", raw):
        return raw

    # 정수
    try:
        return int(raw)
    except ValueError:
        pass

    raise ValueError(f"Cannot parse value: '{raw}'")


def _build_sql_field(field: str, field_type: str, value: Any) -> str:
    """필드명 + 타입에 따라 SQL 필드 참조 생성"""
    # 직접 컬럼 (collection 등)
    if field in DIRECT_COLUMNS:
        return field

    # JSONB 메타데이터 추출 + 타입 캐스팅
    base = f"metadata->>'{field}'"

    if field_type in ("int32", "int64") or isinstance(value, int):
        return f"({base})::int"

    if field_type == "double":
        return f"({base})::float"

    if field_type == "datetimeoffset" or (
        isinstance(value, str)
        and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", value)
    ):
        return f"({base})::timestamptz"

    # 기본: 문자열
    return base


# ---------------------------------------------------------------------------
# OData → Elasticsearch Query DSL
#
# translate_odata_to_sql 과 동일한 문법/허용필드/값 파서를 공유하되, SQL 대신
# Elasticsearch bool query(dict) 를 방출한다. 값은 dict 의 값으로 들어가므로
# (문자열 연결이 없으므로) 인젝션 위험이 없다. 복합 and/or/괄호 필터를 정확히
# 변환해, ES 어댑터가 복합 필터를 match_all 로 떨어뜨려 발생하던 cross-collection
# 누출을 막는다.
# ---------------------------------------------------------------------------


def translate_odata_to_es(
    filter_expr: Optional[str],
    column_info: Optional[List[ColumnInfo]] = None,
) -> Optional[dict]:
    """OData 필터 표현식을 Elasticsearch query dict 로 변환.

    Args:
        filter_expr: OData 필터 문자열 (None/빈 문자열이면 None 반환)
        column_info: 허용 필드 정의 (None 이면 collection 만 허용)

    Returns:
        Elasticsearch query dict, 또는 빈 필터면 None.

    Raises:
        ValueError: 허용되지 않은 필드명/연산자 또는 잘못된 구문.
    """
    if not filter_expr or not filter_expr.strip():
        return None

    allowed_fields = set(DIRECT_COLUMNS)
    field_types = {}
    if column_info:
        for col in column_info:
            allowed_fields.add(col.name)
            field_types[col.name] = col.type

    tokens = _tokenize(filter_expr)
    if not tokens:
        return None

    ctx = _ParseContext(tokens, allowed_fields, field_types)
    es_query = _parse_or_expr_es(ctx)

    if ctx.pos < len(ctx.tokens):
        raise ValueError(
            f"Unexpected token at position {ctx.pos}: '{ctx.tokens[ctx.pos]}'"
        )

    return es_query


def _parse_or_expr_es(ctx: _ParseContext) -> dict:
    """OR 결합: at least one (should, minimum_should_match=1)."""
    clauses = [_parse_and_expr_es(ctx)]
    while ctx.peek() == "or":
        ctx.advance()
        clauses.append(_parse_and_expr_es(ctx))
    if len(clauses) == 1:
        return clauses[0]
    return {"bool": {"should": clauses, "minimum_should_match": 1}}


def _parse_and_expr_es(ctx: _ParseContext) -> dict:
    """AND 결합: all must match (filter context, 무점수)."""
    clauses = [_parse_primary_es(ctx)]
    while ctx.peek() == "and":
        ctx.advance()
        clauses.append(_parse_primary_es(ctx))
    if len(clauses) == 1:
        return clauses[0]
    return {"bool": {"filter": clauses}}


def _parse_primary_es(ctx: _ParseContext) -> dict:
    """괄호 그룹 또는 비교 연산."""
    if ctx.peek() == "(":
        ctx.advance()
        expr = _parse_or_expr_es(ctx)
        ctx.expect(")")
        return expr
    return _parse_comparison_es(ctx)


def _parse_comparison_es(ctx: _ParseContext) -> dict:
    """비교 연산: field op value → term / range."""
    field = ctx.advance()
    if field not in ctx.allowed_fields:
        raise ValueError(
            f"Field '{field}' not allowed. Allowed fields: {ctx.allowed_fields}"
        )

    op_token = ctx.advance()
    if op_token not in ODATA_TO_SQL_OP:
        raise ValueError(
            f"Unsupported operator '{op_token}'. Supported: {list(ODATA_TO_SQL_OP.keys())}"
        )

    raw_value = ctx.advance()
    value = _parse_value(raw_value)

    if op_token == "eq":
        return {"term": {field: value}}
    # ge / le → range
    range_key = "gte" if op_token == "ge" else "lte"
    return {"range": {field: {range_key: value}}}
