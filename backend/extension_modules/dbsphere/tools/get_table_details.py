"""Table details tool for DBSphere - Stage 2 of 3-stage tool design."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from extension_modules.dbsphere.dbsphere_state import DBSphereAgentState
from extension_modules.dbsphere.memory.models import MemoryType
from extension_modules.dbsphere.tools.schemas import GetTableDetailsInput
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

if TYPE_CHECKING:
    from extension_modules.dbsphere.memory.search_memory import (
        SearchEngineDbSphereMemory,
    )

logger = logging.getLogger(__name__)

_TABLE_DETAILS_DESCRIPTION = (
    "Get detailed table schemas (DDL, columns) and related context "
    "(documentation, SQL examples, similar past queries). "
    "Use table_names for exact DDL lookup, query for semantic search, "
    "or both. Call dbsphere_info first to see available tables."
)


async def _run_table_details(
    dbsphere_memory: "SearchEngineDbSphereMemory",
    table_names: Optional[List[str]],
    query: Optional[str],
    runtime: ToolRuntime,
) -> Command:
    """Shared table-details search logic (single-DB and registry-routed paths)."""
    if not table_names and not query:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Error: At least one of table_names or query must be provided.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    sections = []

    try:
        # Case 1 & 3: table_names provided → exact DDL match
        if table_names:
            ddl_memories = await dbsphere_memory.get_table_schemas(
                table_names=table_names,
            )
            ddl_section = dbsphere_memory.format_ddl_context_for_prompt(
                [
                    _wrap_ddl_as_search_result(m, rank=i + 1)
                    for i, m in enumerate(ddl_memories)
                ]
            )
            if ddl_section:
                sections.append(ddl_section)

        # Determine the semantic search query
        search_query = query
        if not search_query and table_names:
            # Case 1: use table names as query for semantic search
            search_query = " ".join(table_names)

        # Semantic search for docs, examples, similar queries
        if search_query:
            unified_result = await dbsphere_memory.search_all_context(
                question=search_query,
                include_types=[
                    MemoryType.DOCUMENTATION,
                    MemoryType.SQL_EXAMPLE,
                    MemoryType.SQL_MEMORY,
                ],
                limit_per_type=3,
                similarity_threshold=0.4,
            )

            doc_section = dbsphere_memory.format_documentation_for_prompt(
                unified_result.documentation
            )
            if doc_section:
                sections.append(doc_section)

            example_section = dbsphere_memory.format_sql_examples_for_prompt(
                unified_result.sql_examples
            )
            if example_section:
                sections.append(example_section)

            similar_section = dbsphere_memory.format_similar_queries_for_prompt(
                unified_result.sql_memories
            )
            if (
                similar_section
                and similar_section != "No similar queries found in memory."
            ):
                sections.append(similar_section)
                # few-shot 참조(주입) 로깅 — 게이트 통과(실제 도구 결과에 포함)한 경우만.
                # chat_id 는 이 경로에서 접근 애매 → None(집계는 memory_id+user_id 로 충분).
                from extension_modules.dbsphere.memory.usage_logger import (
                    record_memory_references,
                )

                record_memory_references(
                    dbsphere_id=dbsphere_memory.dbsphere_id,
                    memory_ids=[
                        r.memory.memory_id for r in unified_result.sql_memories
                    ],
                    user_id=dbsphere_memory.user_id,
                    chat_id=None,
                    injection_point="tool_result",
                )

        if not sections:
            content = "No relevant details found for the given parameters."
        else:
            content = "\n\n".join(sections)

    except Exception as e:
        logger.error(f"Error in get_table_details: {e}", exc_info=True)
        content = f"Error retrieving table details: {str(e)}"

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


def create_get_table_details_tool(
    dbsphere_memory: "Optional[SearchEngineDbSphereMemory]" = None,
    *,
    registry: Optional[Dict[str, Any]] = None,
    dbsphere_ids: Optional[List[str]] = None,
) -> StructuredTool:
    """
    Create a tool that returns detailed table schemas and related context.

    Args:
        dbsphere_memory: single-DB memory (legacy / single-DB path).
        registry: per-DB registry (multi-DB path) — adds a dbsphere_id selector.
        dbsphere_ids: selectable ids when registry mode.

    Returns:
        StructuredTool for table detail retrieval
    """
    if registry is not None:
        return _create_get_table_details_tool_multi(
            registry, dbsphere_ids or list(registry.keys())
        )

    async def get_table_details(
        table_names: Optional[List[str]],
        query: Optional[str],
        runtime: ToolRuntime[None, DBSphereAgentState],
    ) -> Command:
        """Get detailed table schemas, documentation, SQL examples, similar queries."""
        return await _run_table_details(dbsphere_memory, table_names, query, runtime)

    return StructuredTool.from_function(
        coroutine=get_table_details,
        name="get_table_details",
        description=_TABLE_DETAILS_DESCRIPTION,
        args_schema=GetTableDetailsInput,
    )


def _create_get_table_details_tool_multi(
    registry: Dict[str, Any],
    dbsphere_ids: List[str],
) -> StructuredTool:
    """Multi-DB get_table_details: fixed name, dbsphere_id selector, registry routing."""
    from extension_modules.dbsphere.tools._routing import (
        invalid_db_message,
        make_dbsphere_id_field,
        resolve_entry,
    )
    from pydantic import create_model

    InputModel = create_model(
        "GetTableDetailsMultiInput",
        __base__=GetTableDetailsInput,
        dbsphere_id=make_dbsphere_id_field(dbsphere_ids),
    )

    async def get_table_details(
        table_names: Optional[List[str]],
        query: Optional[str],
        runtime: ToolRuntime[None, DBSphereAgentState],
        dbsphere_id: Optional[str] = None,
    ) -> Command:
        _resolved, entry = resolve_entry(dbsphere_id, registry, dbsphere_ids)
        if not entry or not entry.get("memory"):
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
        return await _run_table_details(entry["memory"], table_names, query, runtime)

    return StructuredTool.from_function(
        coroutine=get_table_details,
        name="get_table_details",
        description=(
            "Get detailed table schemas (DDL, columns) and related context "
            "(documentation, SQL examples, similar past queries) for ONE specific "
            "database. First call dbsphere_info to see the connected databases, then "
            "pass the chosen DB's id as dbsphere_id here. Use table_names for exact "
            "DDL lookup, query for semantic search, or both. Call this before "
            "run_sql to understand the schema."
        ),
        args_schema=InputModel,
    )


def _wrap_ddl_as_search_result(ddl_memory, rank: int = 1):
    """Wrap a DDLMemory as DDLMemorySearchResult for format_ddl_context_for_prompt."""
    from extension_modules.dbsphere.memory.search_memory import DDLMemorySearchResult

    return DDLMemorySearchResult(
        memory=ddl_memory,
        similarity_score=1.0,
        rank=rank,
    )
