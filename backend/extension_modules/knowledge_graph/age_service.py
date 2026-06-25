"""Apache AGE 그래프 서비스.

PostgreSQL AGE 확장을 통해 Cypher 쿼리를 실행하는 서비스 레이어.
psycopg2로 직접 AGE SQL을 실행하며, SQLAlchemy와 별도로 동작한다.

사용법:
    svc = AGEService(kg_id="my-kg-id")
    await svc.ensure_graph()
    await svc.create_node("Product", {"label": "갤럭시S26"})
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
from open_webui.env import DATABASE_SCHEMA, DATABASE_URL, SRC_LOG_LEVELS

_AGE_POOL_MIN = int(os.environ.get("AGE_POOL_MIN", "2"))
_AGE_POOL_MAX = int(os.environ.get("AGE_POOL_MAX", "32"))

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

# AGE agtype 결과를 파싱하기 위한 정규식
_AGTYPE_VERTEX_RE = re.compile(r"(\{.*\})::vertex")
_AGTYPE_EDGE_RE = re.compile(r"(\{.*\})::edge")
_AGTYPE_PATH_RE = re.compile(r"\[.*\]::path")


def _to_cypher_props(d: dict) -> str:
    """Python dict를 AGE Cypher 프로퍼티 맵 문자열로 변환.

    AGE Cypher는 JSON과 달리 키를 따옴표 없이 사용한다:
        {name: "갤럭시", price: 100, active: true, nested: {key: "v"}}

    중첩 dict 도 재귀적으로 지원 (UNWIND 배치에서 사용).
    """
    parts = []
    for k, v in d.items():
        if isinstance(v, bool):
            parts.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k}: {v}")
        elif v is None:
            parts.append(f"{k}: null")
        elif isinstance(v, dict):
            parts.append(f"{k}: {_to_cypher_props(v)}")
        elif isinstance(v, (list, tuple)):
            inner = []
            for item in v:
                if isinstance(item, bool):
                    inner.append(str(item).lower())
                elif isinstance(item, (int, float)):
                    inner.append(str(item))
                elif item is None:
                    inner.append("null")
                elif isinstance(item, dict):
                    inner.append(_to_cypher_props(item))
                else:
                    esc = str(item).replace("\\", "\\\\").replace("'", "\\'")
                    inner.append(f"'{esc}'")
            parts.append(f"{k}: [{', '.join(inner)}]")
        else:
            # 문자열: 이스케이프 처리
            escaped = str(v).replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{k}: '{escaped}'")
    return "{" + ", ".join(parts) + "}"


def _parse_connection_string(url: str) -> str:
    """SQLAlchemy DATABASE_URL을 psycopg2 connection string으로 변환.

    postgresql://user:pass@host:port/db → host=host port=port dbname=db user=user password=pass
    postgresql+psycopg2://... 도 처리.
    """
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")
    return url


# ── Connection pool ─────────────────────────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def _get_pool(dsn: str) -> psycopg2.pool.ThreadedConnectionPool:
    """모듈 수준 커넥션 풀을 반환 (lazy init, double-checked locking)."""
    global _pool
    if _pool is None or _pool.closed:
        with _pool_lock:
            if _pool is None or _pool.closed:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    _AGE_POOL_MIN, _AGE_POOL_MAX, dsn=dsn
                )
                log.info(
                    f"[age_service] pool initialized (min={_AGE_POOL_MIN}, max={_AGE_POOL_MAX})"
                )
    return _pool


def _init_age_connection(conn) -> None:
    """커넥션 풀에서 꺼낸 연결에 AGE 확장을 초기화."""
    conn.autocommit = False
    app_schema = DATABASE_SCHEMA or "public"
    with conn.cursor() as cur:
        try:
            cur.execute("LOAD 'age';")
        except Exception:
            # Azure PG에서는 LOAD 불필요할 수 있음
            conn.rollback()
        cur.execute(f'SET search_path = ag_catalog, "{app_schema}"')
    conn.commit()


def _parse_agtype(raw: Any) -> Any:
    """AGE agtype 결과를 Python dict/list로 파싱.

    AGE는 결과를 agtype 문자열로 반환한다:
    - vertex: {"id": 123, "label": "Product", "properties": {...}}::vertex
    - edge: {"id": 456, ...}::edge
    - scalar: 직접 값
    """
    if raw is None:
        return None
    s = str(raw)
    # vertex
    m = _AGTYPE_VERTEX_RE.search(s)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return s
    # edge
    m = _AGTYPE_EDGE_RE.search(s)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return s
    # JSON 직접 파싱 시도
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


class AGEService:
    """KG 인스턴스 단위 AGE 그래프 서비스."""

    def __init__(self, kg_id: str):
        self.kg_id = kg_id
        # 그래프 이름: 영숫자+언더스코어만 (AGE 제약)
        safe_id = re.sub(r"[^a-zA-Z0-9]", "_", kg_id)
        self.graph_name = f"kg_{safe_id}"
        self._dsn = _parse_connection_string(DATABASE_URL)

    def _get_conn(self):
        """풀에서 커넥션을 가져와 AGE 초기화 후 반환.

        풀 고갈 시 지수 백오프로 짧게 재시도 (fan-out race 완화).
        idle/failover 로 server-side 종료된 죽은 커넥션은 폐기 후 재획득해
        "consuming input failed: SSL error: unexpected eof while reading" 를 예방한다.
        (psycopg2 풀은 psycopg3 의 check 콜백이 없어 _init 의 SQL 실행이 사실상
        probe 역할을 하므로, 그 시점의 OperationalError 를 잡아 폐기·재시도한다.)
        """
        import time

        pool = _get_pool(self._dsn)
        last_err: Optional[Exception] = None
        for attempt in range(5):
            conn = None
            try:
                conn = pool.getconn()
                _init_age_connection(conn)  # SQL 실행 → 죽은 커넥션이면 여기서 raise
                return conn
            except psycopg2.pool.PoolError as e:
                last_err = e
                time.sleep(0.1 * (2**attempt))
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                # stale connection: 풀에서 폐기(close=True)하고 새 커넥션으로 재시도
                last_err = e
                if conn is not None:
                    try:
                        pool.putconn(conn, close=True)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                log.warning(
                    "[age_service] discarding dead pooled connection (attempt %d): %s",
                    attempt,
                    e,
                )
                time.sleep(0.05 * (2**attempt))
        raise last_err  # type: ignore[misc]

    def _put_conn(self, conn) -> None:
        """커넥션을 풀에 반환."""
        try:
            pool = _get_pool(self._dsn)
            pool.putconn(conn)
        except Exception:
            # 풀 반환 실패 시 연결 직접 닫기
            try:
                conn.close()
            except Exception:
                pass

    def ensure_graph(self) -> None:
        """그래프가 없으면 생성."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # 그래프 존재 여부 확인
                cur.execute(
                    "SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s",
                    (self.graph_name,),
                )
                exists = cur.fetchone()[0] > 0
                if not exists:
                    cur.execute(f"SELECT create_graph('{self.graph_name}');")
                    log.info(f"[AGE] Created graph: {self.graph_name}")
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.exception(f"[AGE] ensure_graph failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    def execute_cypher(
        self,
        cypher: str,
        *,
        statement_timeout_ms: Optional[int] = None,
    ) -> list[list[Any]]:
        """Cypher 쿼리 실행.

        AGE Cypher는 SQL wrapper로 실행된다:
        SELECT * FROM cypher('graph', $$ CYPHER $$) AS (col1 agtype, ...);

        단순화: 결과 컬럼을 result agtype 하나로 받는다.
        복수 RETURN 컬럼이 필요하면 호출자가 직접 SQL을 구성.

        Args:
            cypher: Cypher 쿼리 (write 절은 호출자 책임으로 검증)
            statement_timeout_ms: PostgreSQL `SET LOCAL statement_timeout`. None
                이면 미적용. kg_cypher 도구가 LLM 입력을 실행할 때 DoS 방어용.
        """
        # RETURN 절의 컬럼 수 추정 (쉼표 기반)
        # 먼저 작은따옴표 문자열 리터럴을 제거하여 RETURN 키워드 오탐 방지
        # (예: label: 'FACT_RETURN' 의 RETURN이 Cypher RETURN으로 오인되는 문제)
        stripped = re.sub(r"'(?:[^'\\]|\\.)*'", "''", cypher)
        return_match = re.search(
            r"(?<![A-Za-z_])RETURN\s+(.+?)(?:\s+LIMIT|\s+ORDER|\s*$)",
            stripped,
            re.I | re.S,
        )
        if return_match:
            return_clause = return_match.group(1)
            # 괄호 안의 쉼표는 무시하고 top-level 쉼표만 카운트
            depth = 0
            col_count = 1
            for ch in return_clause:
                if ch in ("(", "[", "{"):
                    depth += 1
                elif ch in (")", "]", "}"):
                    depth -= 1
                elif ch == "," and depth == 0:
                    col_count += 1
        else:
            col_count = 1

        col_defs = ", ".join(f"c{i} agtype" for i in range(col_count))
        sql = f"SELECT * FROM cypher('{self.graph_name}', $$ {cypher} $$) AS ({col_defs});"

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if statement_timeout_ms is not None and statement_timeout_ms > 0:
                    # 동일 transaction 내에서만 적용. 다음 commit/rollback 시 자동 해제.
                    cur.execute(
                        f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}"
                    )
                cur.execute(sql)
                rows = cur.fetchall()
            conn.commit()
            # agtype 파싱
            parsed = []
            for row in rows:
                parsed.append([_parse_agtype(cell) for cell in row])
            return parsed
        except Exception as e:
            conn.rollback()
            log.exception(f"[AGE] Cypher failed: {e}\nQuery: {cypher}")
            raise
        finally:
            self._put_conn(conn)

    def safe_execute_cypher(
        self,
        cypher: str,
        *,
        max_rows: int = 100,
        timeout_ms: int = 5000,
    ) -> dict:
        """LLM 이 짠 read-only Cypher 를 검증·리라이팅 후 실행.

        kg_cypher 도구가 사용하는 진입점. `cypher_safety` 모듈이 정책 위반 시
        `CypherSafetyError` 를 raise 하므로 호출자가 retry 컨텍스트에 그 메시지를
        그대로 LLM 에 넘기면 된다.

        Args:
            cypher: LLM 이 생성한 Cypher 문자열
            max_rows: 결과 행 cap (기본 100, 호출자가 ≤500 까지 override 가능)
            timeout_ms: PostgreSQL statement_timeout (기본 5000)

        Returns:
            {
                "rows": list[list[Any]],     # 파싱된 agtype 결과
                "row_count": int,             # 잘리기 전 원본 행 수
                "truncated": bool,            # row 또는 byte cap 적중 여부
                "executed_cypher": str,       # 실제 실행된 (LIMIT 자동 주입된) Cypher
                "referenced_node_types": list[str],
                "referenced_edge_types": list[str],
            }

        Raises:
            CypherSafetyError: 안전 정책 위반
            Exception: AGE 실행 에러 (호출자가 friendly_error 로 후처리 권장)
        """
        # 패키지 __init__ 의 import 사슬과 충돌 방지를 위해 lazy import.
        from extension_modules.knowledge_graph import cypher_safety

        # 1. 검증
        cypher_safety.validate_cypher(cypher)

        # 2. LIMIT 자동 주입 (max_rows 상한선)
        effective_limit = min(max(max_rows, 1), 500)
        rewritten = cypher_safety.inject_limit(cypher, default_limit=effective_limit)

        # 3. 참조 타입 추출 (드리프트 처리 metadata 용)
        node_labels, edge_types = cypher_safety.extract_referenced_types(rewritten)

        # 4. 실행 + timeout
        rows = self.execute_cypher(rewritten, statement_timeout_ms=timeout_ms)

        # 5. row / byte cap
        row_count = len(rows)
        truncated = row_count > effective_limit
        if truncated:
            rows = rows[:effective_limit]

        # byte cap (직렬화 길이 64KB) — agtype 폭주 방어
        BYTE_CAP = 64 * 1024
        try:
            serialized_len = sum(
                len(json.dumps(r, ensure_ascii=False, default=str)) for r in rows
            )
        except (TypeError, ValueError):
            serialized_len = 0
        if serialized_len > BYTE_CAP:
            # 단순 잘라내기 — 절반씩 줄이며 cap 안에 들어올 때까지
            while rows and serialized_len > BYTE_CAP:
                rows = rows[: max(1, len(rows) // 2)]
                try:
                    serialized_len = sum(
                        len(json.dumps(r, ensure_ascii=False, default=str))
                        for r in rows
                    )
                except (TypeError, ValueError):
                    break
            truncated = True

        return {
            "rows": rows,
            "row_count": row_count,
            "truncated": truncated,
            "executed_cypher": rewritten,
            "referenced_node_types": sorted(node_labels),
            "referenced_edge_types": sorted(edge_types),
        }

    def create_node(self, label: str, properties: dict) -> Optional[dict]:
        """노드 생성."""
        props_str = _to_cypher_props(properties)
        cypher = f"CREATE (n:{label} {props_str}) RETURN n"
        rows = self.execute_cypher(cypher)
        return rows[0][0] if rows else None

    def upsert_node(
        self, label: str, match_key: str, match_value: Any, properties: dict
    ) -> Optional[dict]:
        """MERGE로 노드 upsert — match_key로 매칭, properties로 갱신."""
        match_props = _to_cypher_props({match_key: match_value})
        set_props = _to_cypher_props(properties)
        cypher = f"MERGE (n:{label} {match_props}) SET n += {set_props} RETURN n"
        rows = self.execute_cypher(cypher)
        return rows[0][0] if rows else None

    def create_edge(
        self,
        src_label: str,
        src_match: dict,
        dst_label: str,
        dst_match: dict,
        edge_label: str,
        properties: dict = None,
    ) -> Optional[dict]:
        """두 노드 사이에 엣지 생성.

        src_match/dst_match: {key: value} 매칭 조건.
        """
        src_props = _to_cypher_props(src_match)
        dst_props = _to_cypher_props(dst_match)
        edge_props = _to_cypher_props(properties or {})
        cypher = (
            f"MATCH (a:{src_label} {src_props}), (b:{dst_label} {dst_props}) "
            f"CREATE (a)-[r:{edge_label} {edge_props}]->(b) "
            f"RETURN r"
        )
        rows = self.execute_cypher(cypher)
        return rows[0][0] if rows else None

    def bulk_upsert_nodes(
        self,
        label: str,
        match_key: str,
        items: list[dict],
        chunk_size: int = 500,
    ) -> int:
        """UNWIND 기반 노드 배치 upsert.

        items: 각 항목은 match_key 와 추가 프로퍼티를 포함한 dict.
               예: ``[{"node_id": "a", "label": "A", "source_kind": "kb"}, ...]``
        chunk_size: Cypher 문자열 길이 폭주를 막기 위한 단위.

        같은 match_key 값이 여러 번 오면 나중 SET 이 승리 (MERGE semantics).
        반환: 처리된 총 item 수 (실패 chunk 는 제외).
        """
        if not items:
            return 0
        processed = 0
        for offset in range(0, len(items), chunk_size):
            chunk = items[offset : offset + chunk_size]
            # 각 item 을 Cypher map literal 로 변환
            map_literals = [_to_cypher_props(it) for it in chunk]
            list_literal = "[" + ", ".join(map_literals) + "]"
            # UNWIND + MERGE: match_key 값만으로 매칭, 나머지는 SET 으로 덮어씀
            cypher = (
                f"UNWIND {list_literal} AS it "
                f"MERGE (n:{label} {{{match_key}: it.{match_key}}}) "
                f"SET n += it "
                f"RETURN count(n)"
            )
            try:
                self.execute_cypher(cypher)
                processed += len(chunk)
            except Exception as e:
                log.warning(
                    f"[AGE] bulk_upsert_nodes chunk failed "
                    f"(label={label}, {len(chunk)} items): {e}"
                )
        return processed

    def bulk_upsert_edges(
        self,
        src_label: str,
        dst_label: str,
        edge_label: str,
        items: list[dict],
        src_key: str = "node_id",
        dst_key: str = "node_id",
        chunk_size: int = 500,
    ) -> int:
        """UNWIND 기반 엣지 배치 upsert.

        items: 각 항목은 ``{src_<src_key>: ..., dst_<dst_key>: ..., props: {...}}``.
            ``props`` 는 scalar 값만 허용. (이유: Apache AGE 는 ``SET r += it.props``
            에서 UNWIND 변수 경유 map 참조를 버전에 따라 "SET clause expects a map"
            으로 거부한다. 이 구현은 같은 `props` key-set 을 가진 item 들을
            sub-group 으로 묶은 뒤 ``SET r.k1 = it.k1, r.k2 = it.k2`` 처럼 key-level
            로 전개해 Cypher 변수 참조를 회피한다.)
        chunk_size: Cypher 문자열 길이 폭주 방지 상한.

        반환: 실제 Cypher 실행이 성공한 chunk 의 item 합계.
        """
        if not items:
            return 0
        src_field = f"src_{src_key}"
        dst_field = f"dst_{dst_key}"

        # props key-set 기준으로 items 를 sub-group 화. 같은 key-set 은 동일
        # SET clause Cypher 로 처리 가능.
        from collections import defaultdict

        groups: dict[tuple, list[dict]] = defaultdict(list)
        for it in items:
            if src_field not in it or dst_field not in it:
                continue
            props = it.get("props") or {}
            # None 값 key 는 스킵 — AGE 의 SET r.k = null 은 속성 삭제로 해석돼서
            # idempotent 가 아님.
            key_sig = tuple(sorted(k for k, v in props.items() if v is not None))
            groups[key_sig].append(it)

        processed = 0
        for key_sig, group_items in groups.items():
            for offset in range(0, len(group_items), chunk_size):
                chunk = group_items[offset : offset + chunk_size]
                map_literals = []
                for it in chunk:
                    props = it.get("props") or {}
                    entry = {
                        src_field: it[src_field],
                        dst_field: it[dst_field],
                    }
                    for k in key_sig:
                        entry[k] = props.get(k)
                    map_literals.append(_to_cypher_props(entry))

                if not map_literals:
                    continue

                list_literal = "[" + ", ".join(map_literals) + "]"
                set_clause = ""
                if key_sig:
                    set_clause = "SET " + ", ".join(f"r.{k} = it.{k}" for k in key_sig)
                cypher = (
                    f"UNWIND {list_literal} AS it "
                    f"MATCH (a:{src_label} {{{src_key}: it.{src_field}}}), "
                    f"(b:{dst_label} {{{dst_key}: it.{dst_field}}}) "
                    f"MERGE (a)-[r:{edge_label}]->(b) "
                    f"{set_clause} "
                    f"RETURN count(r)"
                )
                try:
                    self.execute_cypher(cypher)
                    processed += len(chunk)
                except Exception as e:
                    log.warning(
                        f"[AGE] bulk_upsert_edges chunk failed "
                        f"(edge={edge_label}, keys={list(key_sig)}, "
                        f"{len(chunk)} items): {e}"
                    )
        return processed

    def upsert_edge(
        self,
        src_label: str,
        src_match: dict,
        dst_label: str,
        dst_match: dict,
        edge_label: str,
        properties: dict = None,
    ) -> Optional[dict]:
        """MERGE로 엣지 upsert — 동일 src/dst/type이면 properties만 갱신.

        AGE의 MERGE는 엣지에 대해 제한적이므로,
        존재 여부 확인 후 CREATE 또는 SET으로 처리한다.
        """
        src_props = _to_cypher_props(src_match)
        dst_props = _to_cypher_props(dst_match)
        set_props = _to_cypher_props(properties or {})
        # MATCH로 기존 엣지 확인 후 없으면 CREATE
        cypher = (
            f"MATCH (a:{src_label} {src_props}), (b:{dst_label} {dst_props}) "
            f"MERGE (a)-[r:{edge_label}]->(b) "
            f"SET r += {set_props} "
            f"RETURN r"
        )
        rows = self.execute_cypher(cypher)
        return rows[0][0] if rows else None

    def delete_nodes_by_property(
        self,
        label: Optional[str],
        prop_key: str,
        prop_value: Any,
    ) -> int:
        """특정 속성 값을 가진 노드 전체 삭제 (DETACH DELETE).

        예) source_kind = "glossary" AND source_id = "glos-123" 인 노드 모두 삭제.
        """
        label_str = f":{label}" if label else ""
        # AGE Cypher에서 문자열 값은 작은따옴표 사용
        if isinstance(prop_value, str):
            escaped = prop_value.replace("\\", "\\\\").replace("'", "\\'")
            val_literal = f"'{escaped}'"
        elif isinstance(prop_value, bool):
            val_literal = str(prop_value).lower()
        elif prop_value is None:
            val_literal = "null"
        else:
            val_literal = str(prop_value)
        cypher = (
            f"MATCH (n{label_str}) "
            f"WHERE n.{prop_key} = {val_literal} "
            f"DETACH DELETE n "
            f"RETURN count(n)"
        )
        rows = self.execute_cypher(cypher)
        return int(rows[0][0]) if rows else 0

    def get_neighbors(
        self,
        label: str,
        match: dict,
        hops: int = 1,
        edge_labels: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[dict]:
        """N-hop 이웃 탐색.

        AGE 는 edge alternation `[:A|B]` 를 지원하지 않으므로 분기:
        - edge_labels 0 또는 1 개: 표준 Cypher edge label 표기
        - edge_labels 2+개 + hops=1: ``WHERE type(r) IN [...]`` 으로 필터
        - edge_labels 2+개 + hops>=2: alternation 회피 — 모든 엣지로 traverse
          한 뒤 over-fetch 분량을 제한 (LIMIT). 정확한 hop-단위 필터는 응용
          레벨 post-filter 가 필요할 수 있음.
        """
        match_props = _to_cypher_props(match)
        labels = list(edge_labels or [])

        if not labels:
            edge_part = f"*1..{hops}"
            cypher = (
                f"MATCH (start:{label} {match_props})-[{edge_part}]-(neighbor) "
                f"RETURN DISTINCT neighbor LIMIT {limit}"
            )
        elif len(labels) == 1:
            edge_part = f":{labels[0]}*1..{hops}"
            cypher = (
                f"MATCH (start:{label} {match_props})-[{edge_part}]-(neighbor) "
                f"RETURN DISTINCT neighbor LIMIT {limit}"
            )
        elif hops == 1:
            label_list = ", ".join(f"'{lbl}'" for lbl in labels)
            cypher = (
                f"MATCH (start:{label} {match_props})-[r]-(neighbor) "
                f"WHERE type(r) IN [{label_list}] "
                f"RETURN DISTINCT neighbor LIMIT {limit}"
            )
        else:
            # AGE 미지원 조합 — alternation 없이 traverse, 결과 다소 over-fetch
            # 됨. LIMIT 으로 폭주 방지. (호출자가 필요하면 후처리.)
            edge_part = f"*1..{hops}"
            cypher = (
                f"MATCH (start:{label} {match_props})-[{edge_part}]-(neighbor) "
                f"RETURN DISTINCT neighbor LIMIT {limit}"
            )

        rows = self.execute_cypher(cypher)
        return [row[0] for row in rows if row[0]]

    def delete_all_nodes(self, label: Optional[str] = None) -> int:
        """노드 전체 삭제 (특정 라벨 또는 전체)."""
        if label:
            cypher = f"MATCH (n:{label}) DETACH DELETE n RETURN count(n)"
        else:
            cypher = "MATCH (n) DETACH DELETE n RETURN count(n)"
        rows = self.execute_cypher(cypher)
        return int(rows[0][0]) if rows else 0

    def drop_graph(self) -> None:
        """그래프 삭제."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT drop_graph('{self.graph_name}', true);")
            conn.commit()
            log.info(f"[AGE] Dropped graph: {self.graph_name}")
        except Exception as e:
            conn.rollback()
            log.exception(f"[AGE] drop_graph failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    def graph_exists(self) -> bool:
        """그래프 존재 여부 확인."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s",
                    (self.graph_name,),
                )
                return cur.fetchone()[0] > 0
        finally:
            self._put_conn(conn)

    def count_nodes(self, label: Optional[str] = None) -> int:
        """노드 수 카운트."""
        if label:
            cypher = f"MATCH (n:{label}) RETURN count(n)"
        else:
            cypher = "MATCH (n) RETURN count(n)"
        rows = self.execute_cypher(cypher)
        return int(rows[0][0]) if rows else 0

    def count_edges(self, label: Optional[str] = None) -> int:
        """엣지 수 카운트."""
        if label:
            cypher = f"MATCH ()-[r:{label}]->() RETURN count(r)"
        else:
            cypher = "MATCH ()-[r]->() RETURN count(r)"
        rows = self.execute_cypher(cypher)
        return int(rows[0][0]) if rows else 0
