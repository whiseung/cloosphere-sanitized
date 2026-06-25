"""SQL execution tool for DBSphere V2.

read/write 분리:
    - run_sql_read  — SELECT (read-only). HITL 자동승인 대상.
    - run_sql_write — INSERT/UPDATE/DELETE/MERGE/CREATE/ALTER/DROP/TRUNCATE/REPLACE.
      HITL 승인 게이트로 가로채진다 (정책: hitl_policy.py).

LLM 은 의도 (조회 vs 변경) 에 따라 적절한 도구를 선택한다. 도구를 둘로 쪼갠
이유는 LangChain HumanInTheLoopMiddleware 의 정책이 도구 이름 단위라서 — SQL
인자 분석 없이 표준 그대로 read 자동 / write 승인 정책을 적용할 수 있기 위함.
"""

import logging
import os
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from extension_modules.dbsphere.dbsphere_state import DBSphereAgentState
from extension_modules.dbsphere.sql_classifier import StmtClass, classify_statement
from extension_modules.dbsphere.tools.schemas import RunSqlInput
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

if TYPE_CHECKING:
    from extension_modules.dbsphere.sql_runners.base import SqlRunnerBase

logger = logging.getLogger(__name__)


def _error_remediation_hint(error_text: str) -> str:
    """알려진 DB 에러에 대해 LLM 이 다음 시도에서 자가수정할 수 있는 교정 힌트를 반환.

    raw 에러만 돌려주면 LLM 이 원인을 못 짚고 같은 SQL 을 반복하는 경우가 있어,
    구체적 재작성 방법을 덧붙인다. 매칭 없으면 빈 문자열.
    """
    e = (error_text or "").lower()
    # PostgreSQL `json`(≠ jsonb) 타입은 equality 연산자가 없어 DISTINCT / GROUP BY /
    # UNION / ORDER BY 에 그 컬럼이 끼면 실패한다.
    if "equality operator for type json" in e or ("operator" in e and "type json" in e):
        return (
            "\n\nHINT: A PostgreSQL `json` column has no equality operator, so it "
            "cannot appear in DISTINCT, GROUP BY, UNION (use UNION ALL instead), or "
            "ORDER BY. Rewrite by (a) NOT selecting the raw json column in such "
            "queries, (b) casting it with `col::text` or `col::jsonb`, or "
            "(c) extracting scalar fields via `col->>'key'` and aggregating those. "
            "If you used `SELECT DISTINCT *` or `UNION`, list only the scalar columns "
            "you actually need and avoid the json column."
        )
    return ""


def _oracle_hint(dialect: str) -> str:
    if "oracle" not in (dialect or "").lower():
        return ""
    # Oracle treats '' as NULL — comparison with '' is UNKNOWN, filters out every row.
    return (
        " ORACLE RULES (MUST FOLLOW): Oracle treats empty string '' as NULL, "
        "so any comparison with '' is UNKNOWN (never TRUE) and will exclude all rows. "
        "NEVER write `col <> ''`, `col = ''`, `TRIM(col) <> ''`, `NVL(col, '') <> ''`, "
        "or `TRIM(NVL(col, '')) <> ''`. "
        "To filter non-empty values use `col IS NOT NULL` (or `TRIM(col) IS NOT NULL`). "
        "If a similar-query example or memory shows the bad pattern, IGNORE it and rewrite with IS NOT NULL."
    )


# SQL strategy guidance — relocated from the system prompt into the tool
# description so it travels with run_sql (W2: tool-specific guidance lives on the tool).
_SQL_STRATEGY = (
    " SQL STRATEGY: Always write a SINGLE comprehensive query using WHERE, "
    "GROUP BY, CASE WHEN, or UNION ALL to cover all conditions. Do NOT run "
    "separate queries for each condition (e.g., one per date) — a single query "
    "produces one result set, which is required for combined charts."
)
_SQL_STRATEGY_WRITE_PTR = (
    " Follow the same single-comprehensive-query strategy described for run_sql_read."
)


async def _execute_and_format(
    sql: str,
    sql_runner: "SqlRunnerBase",
    working_directory: str,
    runtime: ToolRuntime,
    *,
    is_write: bool,
    dbsphere_id: Optional[str] = None,
) -> Command:
    """공통 실행 로직 — read/write 둘 다 사용. write 의 경우 빈 DataFrame 가
    "0 rows affected" 같은 의미로 자연스럽게 표시된다.

    dbsphere_id 가 주어지면(멀티 DB 라우팅) state 에 last_sql_dbsphere_id 를 기록해
    Q-SQL 메모리 저장이 올바른 DB 로 라우팅되게 한다."""

    def _with_db(update: dict) -> dict:
        if dbsphere_id:
            update["last_sql_dbsphere_id"] = dbsphere_id
        return update

    try:
        logger.info(
            "Executing %s SQL: %s%s",
            "write" if is_write else "read",
            sql[:100],
            "..." if len(sql) > 100 else "",
        )
        df = await sql_runner.run_sql(sql)

        if df.empty:
            if is_write:
                # DML 의 빈 결과 — RETURNING 절 없으면 정상. affected rows 정보가
                # sql_runner 에 없으므로 LLM 에 명시적 메시지로 전달.
                result_message = (
                    "Statement executed successfully. "
                    "(Driver did not return affected row count; "
                    "verify with a follow-up SELECT if needed.)"
                )
            else:
                result_message = "Query executed successfully. No rows returned."
            return Command(
                update=_with_db(
                    {
                        "messages": [
                            ToolMessage(
                                content=result_message,
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                        "executed_sql": sql,
                        "query_result_file": "",
                        "query_history": [sql],
                    }
                )
            )

        # 결과 있는 경우 (read 또는 write 의 RETURNING 절)
        file_id = str(uuid.uuid4())[:8]
        filename = f"query_results_{file_id}.csv"
        filepath = os.path.join(working_directory, filename)
        csv_content = df.to_csv(index=False)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(csv_content)

        row_count = len(df)
        col_count = len(df.columns)
        columns = df.columns.tolist()
        preview = csv_content
        if len(preview) > 1500:
            preview = preview[:1500] + "\n...(truncated)"

        result_message = f"""Query executed successfully.

**Results:** {row_count} rows, {col_count} columns
**Columns:** {", ".join(columns)}
**Output file:** {filename}

**Preview:**
{preview}
"""
        logger.info("Query returned %d rows, saved to %s", row_count, filename)
        return Command(
            update=_with_db(
                {
                    "messages": [
                        ToolMessage(
                            content=result_message,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                    "executed_sql": sql,
                    "query_result_file": filename,
                    "query_history": [sql],
                }
            )
        )

    except Exception as e:
        error_message = f"Error executing SQL query: {str(e)}"
        error_message += _error_remediation_hint(str(e))
        logger.error("Error executing SQL query: %s", str(e), exc_info=True)
        return Command(
            update=_with_db(
                {
                    "messages": [
                        ToolMessage(
                            content=error_message,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                    "executed_sql": sql,
                }
            )
        )


def _build_run_sql_description(registry: Dict[str, Any], *, is_write: bool) -> str:
    """Build a multi-DB run_sql description (dialect-aware, dbsphere_id-routed)."""
    dialects = sorted({(e.get("dialect") or "SQL") for e in registry.values() if e})
    dialect_str = dialects[0] if len(dialects) == 1 else "selected"
    any_oracle = any(
        "oracle" in ((e.get("dialect") or "").lower()) for e in registry.values() if e
    )
    oracle = _oracle_hint("oracle") if any_oracle else ""
    if is_write:
        body = (
            f"Execute a data-modifying SQL statement against the {dialect_str} "
            "database (INSERT, UPDATE, DELETE, MERGE, CREATE, ALTER, DROP, "
            "TRUNCATE, GRANT, REVOKE, COMMENT). Pass dbsphere_id to choose which "
            "connected database to target. REQUIRES USER APPROVAL — every call is "
            "intercepted by the HITL gate. Use only when the user clearly asked to "
            "modify data or schema. Always preview with a SELECT via run_sql_read first."
        )
    else:
        body = (
            f"Execute a read-only SQL query against the {dialect_str} database "
            "(SELECT, WITH ... SELECT, SHOW, DESCRIBE, EXPLAIN). Pass dbsphere_id to "
            "choose which connected database to query (see dbsphere_info for the "
            "list). Returns query results and saves them to a CSV file. Use "
            "get_table_details first to understand schemas before writing SQL. For "
            "data modification (INSERT/UPDATE/DELETE/CREATE/ALTER/DROP), use "
            "run_sql_write — that path requires user approval."
        )
    strategy = _SQL_STRATEGY_WRITE_PTR if is_write else _SQL_STRATEGY
    return f"{body}{strategy}{oracle}"


def _create_run_sql_tool_multi(
    *,
    registry: Dict[str, Any],
    dbsphere_ids: List[str],
    working_directory: str,
    is_write: bool,
) -> StructuredTool:
    """Multi-DB run_sql tool: fixed name, dbsphere_id selector, registry routing."""
    from extension_modules.dbsphere.tools._routing import (
        invalid_db_message,
        make_dbsphere_id_field,
        resolve_entry,
    )
    from pydantic import create_model

    name = "run_sql_write" if is_write else "run_sql_read"
    InputModel = create_model(
        "RunSqlWriteInput" if is_write else "RunSqlReadInput",
        __base__=RunSqlInput,
        dbsphere_id=make_dbsphere_id_field(dbsphere_ids),
    )

    async def run_sql_multi(
        sql: str,
        runtime: ToolRuntime[None, DBSphereAgentState],
        dbsphere_id: Optional[str] = None,
    ) -> Command:
        resolved_id, entry = resolve_entry(dbsphere_id, registry, dbsphere_ids)
        if not entry or not entry.get("runner"):
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=invalid_db_message(dbsphere_id, dbsphere_ids),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )
        cls = classify_statement(sql)
        if not is_write and cls != StmtClass.READ:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "run_sql_read only executes read-only SQL "
                                "(SELECT, WITH ... SELECT, SHOW, DESCRIBE, EXPLAIN). "
                                "For INSERT/UPDATE/DELETE/DDL — including CTE-wrapped "
                                "DML (`WITH ... DELETE`), `SELECT ... INTO`, or "
                                "multi-statement SQL — use run_sql_write, which "
                                "requires user approval."
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )
        if is_write and cls not in (StmtClass.WRITE, StmtClass.UNKNOWN):
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "run_sql_write only executes data-modifying or "
                                "ambiguous SQL. For a plain read-only SELECT, use "
                                "run_sql_read."
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )
        return await _execute_and_format(
            sql,
            entry["runner"],
            working_directory,
            runtime,
            is_write=is_write,
            dbsphere_id=resolved_id,
        )

    return StructuredTool.from_function(
        coroutine=run_sql_multi,
        name=name,
        description=_build_run_sql_description(registry, is_write=is_write),
        args_schema=InputModel,
    )


def create_run_sql_read_tool(
    sql_runner: "Optional[SqlRunnerBase]" = None,
    working_directory: str = "data/cache/dbsphere_v2",
    dialect: str = "SQL",
    *,
    registry: Optional[Dict[str, Any]] = None,
    dbsphere_ids: Optional[List[str]] = None,
) -> StructuredTool:
    """SELECT-only SQL 실행 도구.

    HITL 정책에서 자동승인 대상 (사용자 결재 없이 즉시 실행).
    registry 가 주어지면 멀티 DB 모드 — dbsphere_id 파라미터로 대상 DB 선택.
    """
    os.makedirs(working_directory, exist_ok=True)

    if registry is not None:
        return _create_run_sql_tool_multi(
            registry=registry,
            dbsphere_ids=dbsphere_ids or list(registry.keys()),
            working_directory=working_directory,
            is_write=False,
        )

    async def run_sql_read(
        sql: str,
        runtime: ToolRuntime[None, DBSphereAgentState],
    ) -> Command:
        # 컨텐츠 기반 분류 — first-keyword 가드는 `WITH cte AS (...) DELETE` 같은
        # CTE-wrapped DML / SELECT...INTO / multi-statement 를 READ 로 오인해 HITL 을
        # 우회시켰다. classify_statement 로 READ 만 자동 실행하고 나머지는 거부.
        if classify_statement(sql) != StmtClass.READ:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "run_sql_read only executes read-only SQL "
                                "(SELECT, WITH ... SELECT, SHOW, DESCRIBE, EXPLAIN). "
                                "This statement was classified as data-modifying or "
                                "ambiguous. For INSERT/UPDATE/DELETE/DDL — including "
                                "CTE-wrapped DML (`WITH ... DELETE`), `SELECT ... INTO`, "
                                "or multi-statement SQL — use run_sql_write, which "
                                "requires user approval."
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )
        return await _execute_and_format(
            sql, sql_runner, working_directory, runtime, is_write=False
        )

    return StructuredTool.from_function(
        coroutine=run_sql_read,
        name="run_sql_read",
        description=(
            f"Execute a read-only SQL query against the {dialect} database "
            "(SELECT, WITH ... SELECT, SHOW, DESCRIBE, EXPLAIN). "
            "Returns query results and saves them to a CSV file. "
            "Use this tool whenever you need to fetch or inspect data. "
            "Use get_table_details first to understand schemas before writing SQL. "
            "For data modification (INSERT/UPDATE/DELETE/CREATE/ALTER/DROP), "
            "use run_sql_write — that path requires user approval."
            f"{_SQL_STRATEGY}{_oracle_hint(dialect)}"
        ),
        args_schema=RunSqlInput,
    )


def create_run_sql_write_tool(
    sql_runner: "Optional[SqlRunnerBase]" = None,
    working_directory: str = "data/cache/dbsphere_v2",
    dialect: str = "SQL",
    *,
    registry: Optional[Dict[str, Any]] = None,
    dbsphere_ids: Optional[List[str]] = None,
) -> StructuredTool:
    """INSERT/UPDATE/DELETE/DDL SQL 실행 도구.

    HITL 정책에서 승인 게이트 대상 — 호출 직전 사용자 결재 필요.
    실제 실행은 사용자가 Approve 한 후에만 일어난다.
    registry 가 주어지면 멀티 DB 모드 — dbsphere_id 파라미터로 대상 DB 선택.
    """
    os.makedirs(working_directory, exist_ok=True)

    if registry is not None:
        return _create_run_sql_tool_multi(
            registry=registry,
            dbsphere_ids=dbsphere_ids or list(registry.keys()),
            working_directory=working_directory,
            is_write=True,
        )

    async def run_sql_write(
        sql: str,
        runtime: ToolRuntime[None, DBSphereAgentState],
    ) -> Command:
        # READ 가 아닌 모든 분류(WRITE + UNKNOWN: multi-statement·미인식 키워드)를
        # 허용해 HITL 게이트를 태운다 — default-deny(UNKNOWN=WRITE). 순수 SELECT 만 거부.
        if classify_statement(sql) not in (StmtClass.WRITE, StmtClass.UNKNOWN):
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "run_sql_write only executes data-modifying or ambiguous "
                                "SQL (INSERT/UPDATE/DELETE/MERGE/CREATE/ALTER/DROP/TRUNCATE, "
                                "CTE-wrapped DML, stored procedures, multi-statement). "
                                "For a plain read-only SELECT, use run_sql_read."
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )
        return await _execute_and_format(
            sql, sql_runner, working_directory, runtime, is_write=True
        )

    return StructuredTool.from_function(
        coroutine=run_sql_write,
        name="run_sql_write",
        description=(
            f"Execute a data-modifying SQL statement against the {dialect} database "
            "(INSERT, UPDATE, DELETE, MERGE, CREATE, ALTER, DROP, TRUNCATE, "
            "GRANT, REVOKE, COMMENT). "
            "REQUIRES USER APPROVAL — every call is intercepted by the HITL gate "
            "and the user must explicitly approve before execution. "
            "Use this only when the user has clearly asked to modify data or schema. "
            "Always preview the change first with a SELECT via run_sql_read so the "
            "user can see what rows are affected. "
            "Wrap multi-row destructive changes in a transaction when the dialect supports it."
            f"{_SQL_STRATEGY_WRITE_PTR}{_oracle_hint(dialect)}"
        ),
        args_schema=RunSqlInput,
    )


# ---------------------------------------------------------------------------
# Backward-compat alias — 기존 import 경로 (extension_modules.../run_sql.create_run_sql_tool)
# 를 쓰는 코드가 있을 경우를 위해 read 도구로 매핑. 신규 코드는 read/write 를 명시적으로.
# ---------------------------------------------------------------------------
def create_run_sql_tool(
    sql_runner: "SqlRunnerBase",
    working_directory: str = "data/cache/dbsphere_v2",
    dialect: str = "SQL",
) -> StructuredTool:
    return create_run_sql_read_tool(sql_runner, working_directory, dialect)
