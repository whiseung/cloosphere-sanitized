"""
DBSphere V2 Agent - LangChain/LangGraph based SQL agent.

This agent provides natural language to SQL conversion using LangChain tools
and LangGraph for orchestration. Database connection info is loaded from
the DbSphere model configuration.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from extension_modules.dbsphere.chart.plotly_generator import PlotlyChartGenerator
from extension_modules.dbsphere.dbsphere_state import (
    DBConfig,
    DBSphereAgentState,
)
from extension_modules.dbsphere.memory.models import MemoryType, UnifiedSearchResult
from extension_modules.dbsphere.memory.search_memory import (
    SearchEngineDbSphereMemory,
)
from extension_modules.dbsphere.prompts import (
    get_dbsphere_system_prompt,
    get_final_answer_prompt,
)
from extension_modules.dbsphere.sql_runners import (
    create_sql_runner,
    get_dialect_name,
)
from extension_modules.dbsphere.sql_runners.base import SqlRunnerBase
from extension_modules.dbsphere.tools.run_sql import create_run_sql_tool
from extension_modules.dbsphere.tools.visualize_data import (
    create_visualize_data_tool,
)
from extension_modules.react.react_base import ReactAgentBase
from extension_modules.react.react_middleware_base import MiddlewareBase
from fastapi import Request
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from open_webui.models.dbsphere import DbSpheres
from open_webui.models.message_trace import RunType
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.models.users import Users
from open_webui.routers.dbsphere import decrypt_connection_password
from open_webui.socket.main import get_event_call, get_event_emitter
from open_webui.utils.misc import openai_chat_chunk_message_template
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


class DBSphereV2AgentState(DBSphereAgentState):
    """Extended state for DBSphere V2 with agent-specific fields."""

    db_dialect: str = "PostgreSQL"


class DBSphereV2AgentOutput:
    """Output schema for DBSphere V2 agent."""

    pass


class DBSphereAgent(ReactAgentBase):
    """
    DBSphere V2 Agent - LangChain/LangGraph based SQL agent.

    This agent provides natural language to SQL conversion using LangChain tools
    and LangGraph for orchestration. Database connection info is loaded from
    the DbSphere model selected in the agent configuration.
    """

    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
    ):
        """
        Initialize DBSphere V2 Agent.

        Args:
            api_config: API configuration (model settings, etc.)
            base_url: LLM API base URL
            api_key: LLM API key
            metadata: Request metadata (user_id, chat_id, model info, etc.)
            request: FastAPI request object
        """
        super().__init__(api_config, base_url, api_key, metadata)

        self.request = request
        self.metadata = metadata
        self.chart_generator = PlotlyChartGenerator()

        # Get dbsphere ID from model meta
        self.dbsphere_id = self._get_dbsphere_id_from_metadata()
        self.dbsphere_info = None
        self.db_config: Optional[DBConfig] = None
        self.sql_runner: Optional[SqlRunnerBase] = None
        self.memory: Optional[SearchEngineDbSphereMemory] = None

        # Working directory for query results
        self.working_directory = "data/cache/dbsphere_v2"
        os.makedirs(self.working_directory, exist_ok=True)

    def _get_dbsphere_id_from_metadata(self) -> Optional[str]:
        """
        Get dbsphere ID from model metadata.

        The dbsphere is referenced in model.info.meta.dbsphere
        similar to how knowledge is referenced in model.info.meta.knowledge
        """
        # New pattern: use agent_config
        if self.agent_config:
            dbsphere_id = self.agent_config.get_first_dbsphere_id()
            if dbsphere_id:
                return dbsphere_id

        # Legacy pattern (fallback for backward compatibility)
        model_info = self.metadata.get("model", {})
        meta = model_info.get("info", {}).get("meta", {})

        # Try to get dbsphere from meta (support both singular and plural)
        dbsphere_list = meta.get("dbspheres", []) or meta.get("dbsphere", [])
        if isinstance(dbsphere_list, list) and dbsphere_list:
            # Return the first dbsphere ID
            first_dbsphere = dbsphere_list[0]
            if isinstance(first_dbsphere, dict):
                return first_dbsphere.get("id")
            elif isinstance(first_dbsphere, str):
                return first_dbsphere

        # Fallback: check enhanced_params
        enhanced_params = self.metadata.get("enhanced_params", {})
        return enhanced_params.get("dbsphere_id")

    def _load_dbsphere_config(self) -> Optional[DBConfig]:
        """
        Load database configuration from DbSphere model.

        Returns:
            DBConfig if found, None otherwise
        """
        if not self.dbsphere_id:
            logger.warning("No dbsphere_id found in metadata")
            return None

        # Verify user has read access to this DbSphere
        user_id = self.metadata.get("user_id", "")
        user = Users.get_user_by_id(user_id) if user_id else None

        if not user or user.role != "admin":
            user_dbspheres = DbSpheres.get_dbspheres_by_user_id(user_id, "read")
            if self.dbsphere_id not in [db.id for db in user_dbspheres]:
                logger.warning(
                    f"User {user_id} has no access to DbSphere {self.dbsphere_id}"
                )
                return None

        # Get DbSphere from database
        dbsphere = DbSpheres.get_dbsphere_by_id(self.dbsphere_id)
        if not dbsphere:
            logger.error(f"DbSphere not found: {self.dbsphere_id}")
            return None

        self.dbsphere_info = dbsphere

        # Decrypt password and create DBConfig
        data = dbsphere.data
        if data:
            data = decrypt_connection_password(data)
            return DBConfig.from_dbsphere_data(data)

        logger.error(f"DbSphere {self.dbsphere_id} has no connection data")
        return None

    def _create_sql_runner(self) -> Optional[SqlRunnerBase]:
        """Create SQL runner based on database type."""
        if not self.db_config:
            return None

        runner = create_sql_runner(self.db_config)
        if runner is None:
            logger.error(
                f"Unsupported database type: {self.db_config.get_db_type_enum()}"
            )
        return runner

    def _create_memory(self) -> Optional[SearchEngineDbSphereMemory]:
        """Create DbSphere memory using search_engine."""
        if not self.dbsphere_id:
            return None

        user_id = self.metadata.get("user_id", "")
        chat_id = self.metadata.get("chat_id")

        # Get embedding config from app
        from extension_modules.search_engine import get_embedding_config_from_app

        embedding_config = get_embedding_config_from_app(self.request.app)

        # Get trace context from request
        from open_webui.utils.tracing import get_trace_context

        trace_context = get_trace_context(self.request)

        # Create embedding function with tracing support
        async def create_embedding(text: str) -> Optional[List[float]]:
            try:
                from extension_modules.search_engine import generate_embedding_async

                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=user_id,
                    chat_id=chat_id,
                    trace_context=trace_context,
                )
            except Exception as e:
                logger.warning(f"Failed to generate embedding: {e}")
                return None

        return SearchEngineDbSphereMemory(
            app=self.request.app,
            dbsphere_id=self.dbsphere_id,
            user_id=user_id,
            embedding_func=create_embedding,
        )

    def _get_db_dialect(self) -> str:
        """Get database dialect name for prompts."""
        if not self.db_config:
            return "SQL"

        return get_dialect_name(self.db_config.get_db_type_enum())

    def get_tools(self) -> List[StructuredTool]:
        """Get the tools available to this agent."""
        tools = []

        if self.sql_runner:
            # SQL execution tool
            tools.append(
                create_run_sql_tool(
                    sql_runner=self.sql_runner,
                    working_directory=self.working_directory,
                )
            )

            # Visualization tool
            tools.append(
                create_visualize_data_tool(
                    working_directory=self.working_directory,
                    chart_generator=self.chart_generator,
                )
            )
        return tools

    async def _get_schema_info(self) -> str:
        """Get database schema information."""
        if not self.sql_runner:
            return "Database connection not configured."

        try:
            schema = await self.sql_runner.get_schema_info()
            return schema
        except Exception as e:
            logger.error(f"Failed to get schema info: {e}")
            return "Schema information unavailable."

    async def _get_similar_queries(self, question: str) -> str:
        """Search for similar queries in memory (backward compatible)."""
        if not self.memory:
            return ""

        try:
            results = await self.memory.search_similar_queries(
                question=question,
                limit=3,
                similarity_threshold=0.5,
            )
            return self.memory.format_similar_queries_for_prompt(results)
        except Exception as e:
            logger.warning(f"Failed to search similar queries: {e}")
            return ""

    async def _get_memory_context(
        self,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """
        Search all memory types for relevant context.

        Args:
            messages: The conversation messages (extracts last user message for search)

        Returns:
            Dict with keys: similar_queries, ddl_context, documentation, sql_examples
        """
        context = {
            "similar_queries": "",
            "ddl_context": "",
            "documentation": "",
            "sql_examples": "",
        }

        if not self.memory:
            return context

        # Extract last user message as the search query
        question = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    question = content
                elif isinstance(content, list):
                    # Handle multi-part content blocks
                    text_parts = [
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    question = " ".join(text_parts)
                break

        if not question:
            return context

        middleware = getattr(self, "_middleware", None)
        retrieval_run_id = None
        if middleware:
            retrieval_run_id = middleware.start_trace_run(
                run_type=RunType.RETRIEVAL.value,
                name="memory_search",
                inputs={"question": question},
            )

        try:
            # Search all memory types
            unified_result: UnifiedSearchResult = await self.memory.search_all_context(
                question=question,
                include_types=[
                    MemoryType.SQL_MEMORY,
                    MemoryType.DDL_SCHEMA,
                    MemoryType.DOCUMENTATION,
                    MemoryType.SQL_EXAMPLE,
                ],
                limit_per_type=3,
                similarity_threshold=0.4,
            )

            # Format each type
            context["similar_queries"] = self.memory.format_similar_queries_for_prompt(
                unified_result.sql_memories
            )
            context["ddl_context"] = self.memory.format_ddl_context_for_prompt(
                unified_result.ddl_memories
            )
            context["documentation"] = self.memory.format_documentation_for_prompt(
                unified_result.documentation
            )
            context["sql_examples"] = self.memory.format_sql_examples_for_prompt(
                unified_result.sql_examples
            )

            # few-shot 참조(주입) 로깅 — non-empty sql_memories 는 시스템 프롬프트에
            # 항상 주입되므로 여기서 fire-and-forget 기록(주입=참조). 비차단·실패무시.
            if unified_result.sql_memories:
                from extension_modules.dbsphere.memory.usage_logger import (
                    record_memory_references,
                )

                record_memory_references(
                    dbsphere_id=self.memory.dbsphere_id,
                    memory_ids=[
                        r.memory.memory_id for r in unified_result.sql_memories
                    ],
                    user_id=self.metadata.get("user_id"),
                    chat_id=self.metadata.get("chat_id"),
                    injection_point="system_prompt",
                )

            if middleware and retrieval_run_id:
                middleware.complete_trace_run(
                    retrieval_run_id,
                    outputs={
                        "sql_memories": [
                            {
                                "question": r.memory.question,
                                "sql": r.memory.sql,
                                "score": r.similarity_score,
                            }
                            for r in unified_result.sql_memories
                        ],
                        "ddl_schemas": [
                            {
                                "table": r.memory.table_name,
                                "description": r.memory.table_description,
                                "score": r.similarity_score,
                            }
                            for r in unified_result.ddl_memories
                        ],
                        "documentation": [
                            {
                                "title": r.memory.title,
                                "content": r.memory.content[:200],
                                "score": r.similarity_score,
                            }
                            for r in unified_result.documentation
                        ],
                        "sql_examples": [
                            {
                                "description": r.memory.description,
                                "sql": r.memory.sql,
                                "score": r.similarity_score,
                            }
                            for r in unified_result.sql_examples
                        ],
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to search memory context: {e}")
            if middleware and retrieval_run_id:
                middleware.complete_trace_run(retrieval_run_id, error=str(e))

        return context

    async def _run_agent(
        self,
        payload: Dict[str, Any],
        tools: List[StructuredTool],
        schema_info: str,
        memory_context: Dict[str, str],
    ) -> DBSphereV2AgentState:
        """Run the LangGraph agent."""
        llm = self._create_llm(payload, stream=False)
        messages, _ = self._extract_messages_and_prompt(payload)

        # Get DB dialect
        dialect = self._get_db_dialect()

        # Always-inject the relationship/JOIN graph from dbsphere.data (Option C):
        # verified FK + inferred (gated) edges surfaced on every query so the join
        # signal is never pruned by similarity retrieval. None/missing/empty → no
        # injection (graceful). This _run_agent path is the single live prompt path.
        ds = getattr(self, "dbsphere_info", None)
        ds_data = (ds.data or {}) if ds else {}
        join_graph = ds_data.get("join_graph") or ""
        inject_inferred = ds_data.get("inject_inferred", True)

        # Build system prompt with all context types
        system_prompt = get_dbsphere_system_prompt(
            dialect=dialect,
            schema_ddl=schema_info,
            similar_queries=memory_context.get("similar_queries", ""),
            ddl_context=memory_context.get("ddl_context", ""),
            documentation=memory_context.get("documentation", ""),
            sql_examples=memory_context.get("sql_examples", ""),
            join_graph=join_graph,
            inject_inferred=inject_inferred,
        )

        # Create agent with middleware
        middleware_metadata = {
            **self.metadata,
            "llm_model_id": payload.get("model"),
        }

        from open_webui.utils.tracing import get_trace_context

        trace_context = get_trace_context(self.request)
        middleware = MiddlewareBase(
            self.event_emitter,
            self.event_call,
            middleware_metadata,
            trace_context=trace_context,
        )
        self._middleware = middleware  # Store for _run_final_stream tracing

        agent = create_agent(
            llm,
            tools,
            system_prompt=system_prompt,
            state_schema=DBSphereV2AgentState,
            middleware=[middleware],
        )

        # Initial state
        state_snapshot = {
            "messages": messages,
            "schema_info": schema_info,
            "similar_queries_text": memory_context.get("similar_queries", ""),
            "db_dialect": dialect,
        }

        result = await agent.ainvoke(state_snapshot)
        return result

    def _check_chart_data(self, chart_data_list: List[Dict]) -> str:
        """Check chart data list status and return appropriate message."""
        if not chart_data_list:
            return ""

        issues = []
        for chart_data in chart_data_list:
            status = chart_data.get("status")
            error_reason = chart_data.get("error_reason")
            requested = chart_data.get("requested_chart_type")
            used = chart_data.get("used_chart_type")

            if status in ("explicit_success", "auto_success") and requested == used:
                continue

            if status == "fallback_auto":
                if requested and used and requested == used:
                    continue

                reason_text = (
                    f"요청한 차트 유형('{requested}')은 데이터 구조상 생성할 수 없었습니다."
                    if requested
                    else "요청한 차트 유형은 데이터 구조상 생성할 수 없었습니다."
                )

                if error_reason:
                    reason_text += f" 실패 사유: {error_reason}."

                if used:
                    reason_text += f" 대신 데이터를 가장 잘 표현할 수 있는 '{used}' 차트로 시각화했습니다."

                issues.append(reason_text)

            elif status == "error":
                base = "데이터를 시각화할 수 있는 차트를 생성하지 못했습니다."
                if error_reason:
                    base += f" 사유: {error_reason}."
                issues.append(base)

        return " ".join(issues)

    def _create_streaming_response(
        self,
        agent_result: DBSphereV2AgentState,
        payload: Dict[str, Any],
    ) -> StreamingResponse:
        """Create streaming response to user."""
        # Get LLM response from messages
        llm_response = ""
        for msg in reversed(agent_result.get("messages", [])):
            if hasattr(msg, "content") and isinstance(msg.content, str):
                if not isinstance(msg, ToolMessage):
                    llm_response = msg.content
                    break

        chart_status = self._check_chart_data(agent_result.get("chart_data_list", []))

        system_prompt = get_final_answer_prompt(
            llm_response=llm_response,
            chart_status_message=chart_status,
            language=agent_result.get("language", "Korean"),
        )

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

        return StreamingResponse(
            self._run_final_stream(payload, system_prompt, agent_result),
            media_type="text/event-stream",
            headers=headers,
        )

    def _create_error_response(
        self,
        error_msg: str,
        model_name: str,
    ) -> StreamingResponse:
        """Create error streaming response."""

        async def error_generator():
            yield self._sse(
                openai_chat_chunk_message_template(model_name, content=error_msg)
            )

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    async def _run_final_stream(
        self,
        payload: Dict[str, Any],
        system_prompt: str,
        agent_result: DBSphereV2AgentState,
    ):
        """Generate final streaming response."""
        model_name = payload.get("model")
        payload["stream_options"] = {"include_usage": True}

        # Output SQL queries first
        query_history = agent_result.get("query_history", [])
        if query_history:
            query_data = "\n".join(query_history)
            query_data = f"```sql\n{query_data}\n```\n\n"
            yield self._sse(
                openai_chat_chunk_message_template(model_name, content=query_data)
            )

        _MAX_PREVIEW = 1000

        # Extract user question for conversation log preview
        _input_preview = ""
        messages = payload.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    content = " ".join(text_parts)
                _input_preview = content[:500] if isinstance(content, str) else ""
                break

        # Stream LLM response
        full_response_parts = []

        async def insert_usage(usage: dict):
            model_info = self.metadata.get("model", {})
            base_model_id = model_info.get("info", {}).get("base_model_id")
            agent_id = model_info.get("id") if base_model_id else None

            # Enrich with conversation preview for conversation logs
            enriched = dict(usage) if usage else {}
            if _input_preview:
                enriched["request_summary"] = {
                    "input_preview": _input_preview,
                    "message_count": len(messages),
                }
            output_text = "".join(full_response_parts)
            if output_text:
                enriched["output_preview"] = output_text[:_MAX_PREVIEW]
            if self.metadata.get("client_type"):
                enriched["client_type"] = self.metadata["client_type"]

            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: Usages.insert_new_usage(
                    user_id=self.metadata.get("user_id"),
                    chat_id=self.metadata.get("chat_id"),
                    agent_id=agent_id,
                    model_id=model_name,
                    message_id=self.metadata.get("message_id"),
                    message_type=UsageMessageType.GENERATION,
                    total_tokens=usage.get("total_tokens"),
                    usage=enriched,
                ),
            )

        # Start trace for final answer
        final_answer_run_id = None
        if hasattr(self, "_middleware") and self._middleware:
            final_answer_run_id = self._middleware.start_trace_run(
                run_type=RunType.LLM.value,
                name="final_answer",
                inputs={
                    "normalized_question": agent_result.get("normalized_question", ""),
                    "query_count": len(agent_result.get("query_history", [])),
                },
                model_id=model_name,
            )
        final_token_usage = None
        async for chunk in self._create_llm(payload, stream=True).astream(
            system_prompt
        ):
            if chunk.usage_metadata:
                final_token_usage = chunk.usage_metadata
                await insert_usage(chunk.usage_metadata)
            piece = getattr(chunk, "content", "")
            # Gemini/Vertex AI returns list of content blocks
            if isinstance(piece, list):
                piece = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in piece
                )
            if isinstance(piece, str) and piece:
                full_response_parts.append(piece)
                yield self._sse(
                    openai_chat_chunk_message_template(model_name, content=piece)
                )

        # Complete trace
        if final_answer_run_id and hasattr(self, "_middleware") and self._middleware:
            full_response = "".join(full_response_parts)
            self._middleware.complete_trace_run(
                final_answer_run_id,
                outputs={
                    "response": (
                        full_response[:5000] + "..."
                        if len(full_response) > 5000
                        else full_response
                    ),
                    "response_length": len(full_response),
                },
                token_usage=final_token_usage,
            )

        # Output chart data if available
        chart_data_list = agent_result.get("chart_data_list", [])
        if chart_data_list:
            charts_json = []
            for chart_data in chart_data_list:
                chart_result = chart_data.get("chart_result", {})
                charts_json.append(chart_result)
            chart_content = (
                f"\n\n[[dbsphere:chart]]\n```json\n{json.dumps(charts_json)}\n```\n\n"
            )
            yield self._sse(
                openai_chat_chunk_message_template(model_name, content=chart_content)
            )

        # Save final SQL query to memory
        # Only save when ALL conditions are met:
        # 1. query_result_file exists (= SQL returned 1+ rows)
        # 2. executed_sql exists (= paired with the result file)
        # 3. question is meaningful (>= 5 chars)
        # This prevents saving exploratory queries (SELECT * LIMIT 5)
        # or failed queries (0 rows) as "successful" few-shot examples.
        final_sql = agent_result.get("executed_sql", "")
        result_file = agent_result.get("query_result_file", "")
        # Use normalized_question if available, otherwise fall back to
        # the original user message (normalized_question is only set when
        # the LLM calls rewrite_question tool, which DBSphere doesn't use).
        save_question = agent_result.get("normalized_question", "")
        if not save_question:
            for msg in reversed(agent_result.get("messages", [])):
                if hasattr(msg, "type") and msg.type == "human":
                    content = msg.content
                    if isinstance(content, str):
                        save_question = content
                    elif isinstance(content, list):
                        text_parts = [
                            p.get("text", "")
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        save_question = " ".join(text_parts)
                    break
        if (
            self.memory
            and result_file
            and final_sql
            and save_question
            and len(save_question.strip()) >= 5
        ):
            try:
                await self.memory.save_sql_memory(
                    question=save_question,
                    sql=final_sql,
                    success=True,
                    metadata={
                        "user_id": self.metadata.get("user_id"),
                        "chat_id": self.metadata.get("chat_id"),
                        "origin": "llm_auto",  # 에이전트 자동저장
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to save query to memory: {e}")

        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Task completed!",
                    "done": True,
                    "detail": "Task completed!",
                },
            }
        )

        # Cleanup SQL runner connection
        if self.sql_runner:
            try:
                await self.sql_runner.close()
            except Exception as e:
                logger.debug(f"Failed to close SQL runner: {e}")

    async def run(
        self,
        *,
        request,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        user,
    ) -> StreamingResponse:
        """
        Run the DBSphere V2 agent.

        Args:
            request: FastAPI request
            payload: Request payload with messages and model settings
            metadata: Request metadata
            user: User object

        Returns:
            StreamingResponse with agent results
        """
        self.event_emitter = get_event_emitter(metadata)
        self.event_call = get_event_call(metadata)

        model_name = payload.get("model", "")

        # Load database configuration
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Loading database configuration...",
                    "done": False,
                },
            }
        )

        self.db_config = self._load_dbsphere_config()
        if not self.db_config:
            error_msg = "Database configuration not found. Please configure a database in the agent settings."
            return self._create_error_response(error_msg, model_name)

        # Create SQL runner and memory
        self.sql_runner = self._create_sql_runner()
        self.memory = self._create_memory()

        if not self.sql_runner:
            error_msg = f"Unsupported database type: {self.db_config.db_type}"
            return self._create_error_response(error_msg, model_name)

        # Get tools
        tools = self.get_tools()

        # Extract and normalize message
        messages, _ = self._extract_messages_and_prompt(payload)

        # Get schema info
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Fetching database schema...",
                    "done": False,
                },
            }
        )
        schema_info = await self._get_schema_info()

        # Get memory context (all types: SQL, DDL, Documentation, Examples)
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Searching memory for context...",
                    "done": False,
                },
            }
        )
        memory_context = await self._get_memory_context(messages)

        # Run agent
        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": "Generating SQL query...",
                    "done": False,
                },
            }
        )
        result = await self._run_agent(
            payload=payload,
            tools=tools,
            schema_info=schema_info,
            memory_context=memory_context,
        )

        # Return streaming response
        return self._create_streaming_response(result, payload)
