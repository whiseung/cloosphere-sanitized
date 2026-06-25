"""DB overview tool for DBSphere - Stage 1 of 3-stage tool design."""

import logging
from typing import Any, Dict, Optional

from extension_modules.dbsphere.dbsphere_state import DBSphereAgentState
from extension_modules.dbsphere.prompts import _strip_inferred_from_join_graph
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

logger = logging.getLogger(__name__)


def _build_dbsphere_info_content(dialect: str, data: Dict[str, Any]) -> str:
    """Render the Stage-1 DB overview from dbsphere.data (pure, testable).

    Surfaces available tables + DB overview + the always-recomputed JOIN graph
    (Option C). The join_graph lets the 3-stage UnifiedAgent see verified-FK +
    inferred relationships up front; ``inject_inferred=False`` strips the inferred
    tier (same gate as the always-inject prompt path).
    """
    parts = [f"Database: {dialect}"]
    has_info = False

    table_overview = data.get("table_overview", "")
    if table_overview:
        parts.append(f"\n## Available Tables\n{table_overview}")
        has_info = True

    schema_summary = data.get("schema_summary", "")
    if schema_summary:
        parts.append(f"\n## Database Overview\n{schema_summary}")
        has_info = True

    join_graph = data.get("join_graph") or ""
    if join_graph and not data.get("inject_inferred", True):
        join_graph = _strip_inferred_from_join_graph(join_graph)
    if join_graph.strip():
        parts.append(f"\n{join_graph}")
        has_info = True

    if not has_info:
        parts.append("\nNo table information available.")

    return "\n".join(parts)


def create_dbsphere_info_tool(
    dialect: str = "SQL",
    dbsphere_data: Optional[Dict[str, Any]] = None,
    *,
    registry: Optional[Dict[str, Any]] = None,
) -> StructuredTool:
    """
    Create a tool that returns DB overview information.

    Args:
        dialect: Database dialect name (e.g., "PostgreSQL") — single-DB mode.
        dbsphere_data: The dbsphere.data dict (single-DB mode).
        registry: per-DB registry (multi-DB mode) — returns a catalog of ALL
            connected DBs so the LLM can pick a dbsphere_id for the stage-2/3 tools.

    Returns:
        StructuredTool for DB overview
    """
    if registry is not None:
        return _create_dbsphere_info_catalog_tool(registry)

    data = dbsphere_data or {}

    async def dbsphere_info(
        runtime: ToolRuntime[None, DBSphereAgentState],
    ) -> Command:
        """Return database overview including available tables."""
        content = _build_dbsphere_info_content(dialect, data)

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return StructuredTool.from_function(
        coroutine=dbsphere_info,
        name="dbsphere_info",
        description=(
            f"Get an overview of the {dialect} database including "
            "available tables and their descriptions. "
            "Call this first to understand what tables are available "
            "before querying for details."
        ),
    )


def _create_dbsphere_info_catalog_tool(registry: Dict[str, Any]) -> StructuredTool:
    """Multi-DB stage-1 tool: a catalog of every connected database.

    Renders one section per DB (id | name (dialect) + table_overview/schema_summary)
    so the LLM learns which dbsphere_id holds the relevant tables before calling
    get_table_details / run_sql with that id.
    """

    async def dbsphere_info(
        runtime: ToolRuntime[None, DBSphereAgentState],
    ) -> Command:
        """Return an overview catalog of all connected databases."""
        blocks = []
        for dbsphere_id, entry in registry.items():
            info = entry.get("info")
            name = getattr(info, "name", "") or dbsphere_id
            dialect = entry.get("dialect", "SQL")
            data = entry.get("data") or {}
            header = f"# DB id: {dbsphere_id} | {name} ({dialect})"
            body = _build_dbsphere_info_content(dialect, data)
            blocks.append(f"{header}\n{body}")
        content = (
            "연결된 데이터베이스 목록입니다. 질문과 관련된 DB의 id 를 골라 "
            "get_table_details / run_sql_read / run_sql_write 의 dbsphere_id "
            "파라미터로 전달하세요.\n\n" + "\n\n---\n\n".join(blocks)
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    db_list = ", ".join(
        f"{dbsphere_id}({getattr(entry.get('info'), 'name', '') or dbsphere_id})"
        for dbsphere_id, entry in registry.items()
    )
    return StructuredTool.from_function(
        coroutine=dbsphere_info,
        name="dbsphere_info",
        description=(
            "Get an overview catalog of ALL connected databases (tables + "
            "descriptions per DB). Call this FIRST to learn which database holds "
            "the data you need, then pass that DB's id as dbsphere_id to "
            f"get_table_details and run_sql. Connected: {db_list}."
        ),
    )
