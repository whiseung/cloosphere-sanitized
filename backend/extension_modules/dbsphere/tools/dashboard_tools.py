"""Dashboard Builder Agent 도구 정의.

대시보드 패널 생성/배치를 위한 LangChain StructuredTool 세트.
"""

import logging
import operator
from typing import Annotated, Any, Dict, List

from extension_modules.react.react_base import AgentStateBase
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


####################
# Agent State
####################


class DashboardBuilderState(AgentStateBase):
    """대시보드 빌더 에이전트 상태."""

    panel_definitions: Annotated[List[Dict[str, Any]], operator.add] = []
    layout_config: Dict[str, Any] = {}
    schema_info: str = ""
    executed_queries: Annotated[List[str], operator.add] = []


####################
# Input Schemas
####################


class CreateCardPanelInput(BaseModel):
    """카드 패널 생성 입력."""

    name: str = Field(description="Panel display name (e.g., 'Total Orders')")
    nl_query: str = Field(
        default="",
        description="Natural language description (e.g., 'Total number of orders')",
    )
    dbsphere_id: str = Field(description="DbSphere ID for this panel")
    sql: str = Field(
        description="Validated SQL query that returns a single value. "
        "Must be tested with run_sql first. e.g., SELECT COUNT(*) AS value FROM orders",
    )
    sql_template: str = Field(
        default="",
        description="SQL with $st/$ed placeholders for time filter. "
        "e.g., SELECT COUNT(*) AS value FROM orders WHERE order_date BETWEEN '$st' AND '$ed'",
    )
    date_column: str = Field(
        default="",
        description="The date/timestamp column name used in sql_template for $st/$ed filtering.",
    )
    bg_color: str = Field(
        default="",
        description="Background color hex (e.g., '#3B82F6' for blue, '#10B981' for green, '#F59E0B' for yellow, '#EF4444' for red). Empty for default.",
    )


class CreateChartPanelInput(BaseModel):
    """차트 패널 생성 입력."""

    name: str = Field(description="Panel display name (e.g., 'Monthly Sales Trend')")
    nl_query: str = Field(
        default="",
        description="Natural language description of what this panel shows (e.g., 'Top 10 models by token usage')",
    )
    dbsphere_id: str = Field(description="DbSphere ID for this panel")
    sql: str = Field(
        description="Validated SQL query WITHOUT date filter (tested with run_sql)"
    )
    sql_template: str = Field(
        default="",
        description="SQL with $st/$ed placeholders for time filter. "
        "e.g., SELECT * FROM orders WHERE order_date BETWEEN '$st' AND '$ed'",
    )
    date_column: str = Field(
        default="",
        description="The date/timestamp column name used in sql_template for $st/$ed filtering. "
        "e.g., 'created_at', 'order_date'. MUST match the column in sql_template.",
    )
    chart_type: str = Field(
        default="bar",
        description="Chart type: bar, line, pie, area, scatter, table, histogram, heatmap, grouped_bar",
    )


class SetLayoutInput(BaseModel):
    """패널 배치 설정 입력."""

    panels: List[Dict[str, Any]] = Field(
        description="List of panel layouts: [{panel_index: 0, x: 0, y: 0, w: 3, h: 1}, ...]. "
        "Grid is 12 columns. panel_index is 0-based order of panel creation."
    )


####################
# Tool Factories
####################


def create_card_panel_tool() -> StructuredTool:
    """카드 패널 생성 도구."""

    async def create_card_panel(
        name: str,
        dbsphere_id: str,
        sql: str,
        nl_query: str = "",
        sql_template: str = "",
        date_column: str = "",
        bg_color: str = "",
        runtime: ToolRuntime[None, DashboardBuilderState] = None,
    ) -> Command:
        panel_def = {
            "type": "card",
            "name": name,
            "nl_query": nl_query,
            "dbsphere_id": dbsphere_id,
            "sql": sql,
            "sql_template": sql_template,
            "date_column": date_column,
            "chart_type": "card",
            "card_source": "db",
            "card_bg_color": bg_color,
            "use_time_filter": bool(
                sql_template and ("$st" in sql_template or "$ed" in sql_template)
            ),
            "show_title": True,
            "title_position": "inside-bottom",
        }

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Card panel created: '{name}'",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "panel_definitions": [panel_def],
            }
        )

    return StructuredTool.from_function(
        coroutine=create_card_panel,
        name="create_card_panel",
        description="Create a card panel showing a single aggregated value. "
        "MUST test the SQL with run_sql first, then pass validated sql and sql_template with $st/$ed.",
        args_schema=CreateCardPanelInput,
    )


def create_chart_panel_tool() -> StructuredTool:
    """차트 패널 생성 도구."""

    async def create_chart_panel(
        name: str,
        dbsphere_id: str,
        sql: str,
        nl_query: str = "",
        sql_template: str = "",
        date_column: str = "",
        chart_type: str = "bar",
        runtime: ToolRuntime[None, DashboardBuilderState] = None,
    ) -> Command:
        panel_def = {
            "type": "chart",
            "name": name,
            "nl_query": nl_query,
            "dbsphere_id": dbsphere_id,
            "sql": sql,
            "sql_template": sql_template,
            "date_column": date_column,
            "chart_type": chart_type,
            "panel_type": "chart",
            "use_time_filter": bool(
                sql_template and ("$st" in sql_template or "$ed" in sql_template)
            ),
            "show_title": True,
            "title_position": "top",
        }

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Chart panel created: '{name}' (type={chart_type})",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "panel_definitions": [panel_def],
            }
        )

    return StructuredTool.from_function(
        coroutine=create_chart_panel,
        name="create_chart_panel",
        description="Create a chart panel with a SQL query. "
        "IMPORTANT: Always test the SQL with run_sql first before creating the panel. "
        "Chart types: bar (categories), line (trends), pie (proportions), area (cumulative), scatter (correlation), table (raw data), "
        "histogram (value distribution), heatmap (2D categorical matrix with color intensity), grouped_bar (multi-series category comparison).",
        args_schema=CreateChartPanelInput,
    )


####################
# Ask User (Human-in-the-Loop)
####################


class AskUserInput(BaseModel):
    """사용자에게 질문하기 위한 입력."""

    question: str = Field(description="Question to ask the user")
    options: List[str] = Field(
        default=[],
        description="Suggested options as clickable buttons. If empty, user types freely.",
    )


def create_ask_user_tool() -> StructuredTool:
    """사용자에게 질문하는 도구 — Human-in-the-Loop."""

    async def ask_user(
        question: str,
        options: List[str] = [],
        runtime: ToolRuntime[None, DashboardBuilderState] = None,
    ) -> Command:
        options_json = "|".join(options) if options else ""
        marker = f"ASK_USER:{question}::OPTIONS:{options_json}"
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=marker,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return StructuredTool.from_function(
        coroutine=ask_user,
        name="ask_user",
        description="Ask the user a question when you need their input. "
        "Use this ONLY when truly necessary: which database to use, "
        "what kind of dashboard to build, etc. "
        "Provide clear options when possible.",
        args_schema=AskUserInput,
    )


####################
# Modify / Delete Existing Panels
####################


class DeletePanelInput(BaseModel):
    """패널 삭제 입력."""

    panel_name: str = Field(
        description="Name of the panel to delete (exact or partial match)"
    )


def create_delete_panel_tool() -> StructuredTool:
    """패널 삭제 도구."""

    async def delete_panel(
        panel_name: str,
        runtime: ToolRuntime[None, DashboardBuilderState] = None,
    ) -> Command:
        msg = f"DELETE_PANEL:{panel_name}"
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=msg,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return StructuredTool.from_function(
        coroutine=delete_panel,
        name="delete_panel",
        description="Delete an existing panel from the dashboard. "
        "The panel_name should match (exact or partial) an existing panel.",
        args_schema=DeletePanelInput,
    )


class SetExistingLayoutInput(BaseModel):
    """기존 패널 레이아웃 변경 입력."""

    panels: List[Dict[str, Any]] = Field(
        description="List of existing panel repositions: "
        "[{existing_index: 0, x: 0, y: 1, w: 3, h: 1}, ...]. "
        "existing_index refers to the panel's index in the 'existing_N' list. "
        "Use this to shift existing panels down/up when inserting at a specific position."
    )


def create_set_existing_layout_tool() -> StructuredTool:
    """기존 패널 레이아웃 재배치 도구."""

    async def set_existing_layout(
        panels: List[Dict[str, Any]],
        runtime: ToolRuntime[None, DashboardBuilderState] = None,
    ) -> Command:
        marker = "REPOSITION_EXISTING:" + str(panels)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=marker,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return StructuredTool.from_function(
        coroutine=set_existing_layout,
        name="set_existing_panel_layout",
        description="Reposition EXISTING panels on the grid. Use this when you need to "
        "shift existing panels down to make room at the top, or rearrange the layout. "
        "Each item needs: existing_index (from the existing panel list), x, y, w, h.",
        args_schema=SetExistingLayoutInput,
    )


def create_set_layout_tool() -> StructuredTool:
    """패널 배치 도구."""

    async def set_layout(
        panels: List[Dict[str, Any]],
        runtime: ToolRuntime[None, DashboardBuilderState] = None,
    ) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Layout configured for {len(panels)} panels.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "layout_config": {"panels": panels},
            }
        )

    return StructuredTool.from_function(
        coroutine=set_layout,
        name="set_dashboard_layout",
        description="Set the grid layout for all panels. Grid has 12 columns, each row is 80px. "
        "Each panel needs: panel_index (0-based creation order), x (column), y (row), w (width), h (height). "
        "IMPORTANT: chart panels (line, bar, pie, scatter, histogram, heatmap, grouped_bar) MUST have h>=3 (min 240px). "
        "Guidelines: cards w=3,h=1 (4 per row); charts w=6,h=4 (2 per row); full-width w=12,h=4. "
        "NEVER set h=1 or h=2 for chart panels — Plotly requires at least 240px height to render axes.",
        args_schema=SetLayoutInput,
    )
