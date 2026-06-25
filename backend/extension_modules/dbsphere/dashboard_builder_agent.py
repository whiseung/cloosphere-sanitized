"""Dashboard Builder Agent.

DbSphere 스키마를 분석하여 의미 있는 대시보드를 자동 생성하는 에이전트.
ReactAgentBase를 상속하고, DBSphereAgent 패턴을 따름.
"""

import copy
import logging
from typing import Any, Dict, List, Optional

from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.tools.dashboard_tools import (
    DashboardBuilderState,
    create_ask_user_tool,
    create_card_panel_tool,
    create_chart_panel_tool,
    create_delete_panel_tool,
    create_set_existing_layout_tool,
    create_set_layout_tool,
)
from extension_modules.dbsphere.tools.run_sql import create_run_sql_tool
from extension_modules.react.react_base import ReactAgentBase
from fastapi import Request
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)

DASHBOARD_BUILDER_SYSTEM_PROMPT = """You are a Dashboard Builder Agent. Your task is to analyze database schemas and create a useful data dashboard with card and chart panels.

## Rules
1. First analyze the schema to identify key business metrics and KPIs
2. Create 3-5 card panels for key metrics (totals, counts, averages)
3. Create 3-5 chart panels for trends, distributions, and comparisons
4. For chart panels: ALWAYS test the SQL with run_sql first, then pass the validated SQL to create_chart_panel
5. After creating all panels, call set_dashboard_layout to arrange them on a 12-column grid
6. Create DIVERSE chart types — do NOT make all charts the same type:
   - bar: category comparison (e.g., top models, usage by group)
   - line: time trends (e.g., daily usage over time) — only 1-2 line charts max
   - pie: proportions/distribution (e.g., message type ratio)
   - area: cumulative trends
   - table: detailed data listing
   - histogram: value distribution (e.g., response time distribution) — SQL should return raw numeric values, NOT aggregated counts
   - heatmap: 2D matrix with color intensity (e.g., usage by day-of-week × hour) — SQL should return 2 categorical columns + 1 numeric column
   - grouped_bar: multi-series comparison (e.g., usage by department per month) — SQL should return 2+ categorical columns + 1 numeric column
7. Use colors for card backgrounds: '#3B82F6' (blue), '#10B981' (green), '#F59E0B' (yellow), '#EF4444' (red), '#8B5CF6' (purple), '#06B6D4' (cyan)

## CRITICAL: Time Filter with SQL Template ($st/$ed)
Every panel must support the dashboard's time range filter (1d/7d/30d).
To achieve this, create a sql_template with $st and $ed placeholders.

### Process for each panel:
1. Write SQL WITHOUT date filter → test with run_sql (1st validation)
2. Add a date WHERE clause using the table's date/timestamp column → test with run_sql again (2nd validation)
3. In the 2nd SQL, replace the actual date values with $st and $ed → this becomes the sql_template
4. Pass both sql (original without date) and sql_template (with $st/$ed) to create_chart_panel

### $st and $ed definition:
- $st = start date (inclusive), format: 'YYYY-MM-DD'
- $ed = end date (inclusive), format: 'YYYY-MM-DD'
- When $st == $ed, it means a single day (e.g., yesterday only)
- The sql_template MUST handle single-day correctly based on column type and DATABASE TYPE

### Date filter by database type:
{date_filter_guide}

### For Snowflake/special columns:
- Integer key: use appropriate conversion (e.g., `TO_DATE(TO_CHAR(ORDER_DATE_KEY), 'YYYYMMDD')`)
- Always verify with run_sql that the date filter SQL actually works

## Layout Guidelines
- Cards: w=3, h=1 (fit 4 cards per row at the top)
- Charts: w=6, h=4 (2 charts per row below cards)
- Full-width chart: w=12, h=4
- Cards go in row y=0, charts start from y=1

## Database Schemas
{schema_info}

## Process
1. Analyze schemas → identify key tables, columns, relationships, and DATE/TIMESTAMP columns
2. For each card panel:
   a. Write SQL: `SELECT AGG(*) FROM table` → run_sql (1st validation)
   b. Add date filter → run_sql (2nd validation)
   c. Replace dates with $st/$ed → create_card_panel with sql_template
3. For each chart panel:
   a. Write SQL → run_sql (1st validation)
   b. Add date filter → run_sql (2nd validation)
   c. Replace dates with $st/$ed → create_chart_panel with sql and sql_template
4. Call set_dashboard_layout with positions for all panels

## IMPORTANT
- NEVER skip the 2-step validation (run_sql twice: without date, with date)
- If run_sql fails, fix the SQL and retry — do NOT skip the panel
- For COUNT in cards, always use column="*"
- Use proper table quoting for the database dialect (e.g., PostgreSQL: public."user", MySQL: `user`, MSSQL: [user])
"""


DASHBOARD_BUILDER_CHAT_PROMPT = """You are a Dashboard Builder Agent. Your task is to analyze database schemas and create a useful data dashboard with card and chart panels through multi-turn conversation.

## Available Resources
{available_resources}

## Asking the User
Use ask_user tool when you need the user's input. ONLY ask when truly necessary:
- Which database to use (if multiple databases are available)
- What kind of dashboard to build (if the user's intent is vague)
Do NOT ask about: chart types, colors, layout — decide these yourself based on data analysis.

## Rules
1. First analyze the schema to identify key business metrics and KPIs
2. Create 3-5 card panels for key metrics (totals, counts, averages)
3. Create 3-5 chart panels for trends, distributions, and comparisons
4. For chart panels: ALWAYS test the SQL with run_sql first, then pass the validated SQL to create_chart_panel
5. After creating all panels, call set_dashboard_layout to arrange them on a 12-column grid
6. Create DIVERSE chart types — do NOT make all charts the same type:
   - bar: category comparison
   - line: time trends (only 1-2 max)
   - pie: proportions/distribution
   - area: cumulative trends
   - table: detailed data listing
   - histogram: value distribution — SQL returns raw numeric values
   - heatmap: 2D matrix with color intensity — SQL returns 2 categorical + 1 numeric column
   - grouped_bar: multi-series comparison — SQL returns 2+ categorical + 1 numeric column
7. Use colors for card backgrounds: '#3B82F6' (blue), '#10B981' (green), '#F59E0B' (yellow), '#EF4444' (red), '#8B5CF6' (purple), '#06B6D4' (cyan)

## CRITICAL: Time Filter with SQL Template ($st/$ed)
Every panel must support the dashboard's time range filter.
### Process for each panel:
1. Write SQL WITHOUT date filter → test with run_sql (1st validation)
2. Add a date WHERE clause → test with run_sql again (2nd validation)
3. Replace actual date values with $st and $ed → this becomes the sql_template
4. Pass both sql and sql_template to create_chart_panel/create_card_panel

### $st/$ed date filter — use the correct syntax for the database type:
{date_filter_guide}

## Layout Guidelines
- Cards: w=3, h=1 (4 per row at y=0)
- Charts: w=6, h=4 (2 per row, start from y=1)
- Full-width: w=12, h=4

## Modifying Existing Dashboard
{existing_panels_context}

## IMPORTANT
- Use ONLY actual DbSphere resources from "Available Resources" above
- NEVER hardcode or invent database names or IDs
- ALWAYS respond in the same language as the user
- NEVER skip the 2-step validation (run_sql twice: without date, with date)
- If run_sql fails, fix the SQL and retry
- If modifying an existing dashboard, only add/modify requested panels — preserve existing ones
- To CHANGE an existing panel (chart type, data, SQL), FIRST delete_panel the old one, THEN create a new panel with the correct SQL and chart_type
- To REMOVE an existing panel, use delete_panel tool
- Use proper table quoting for the database dialect
"""


class DashboardBuilderAgent(ReactAgentBase):
    """DbSphere 스키마 분석 → 대시보드 자동 생성 에이전트."""

    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
        dbsphere_ids: List[str],
    ):
        super().__init__(api_config, base_url, api_key, metadata)
        self.request = request
        self.dbsphere_ids = dbsphere_ids
        self.sql_runners: Dict[str, Any] = {}
        self.schema_info_map: Dict[str, str] = {}
        self.dbsphere_names: Dict[str, str] = {}

    async def load_data_sources(self):
        """모든 선택된 DbSphere의 DB 설정 + 스키마 로드."""
        from open_webui.models.dbsphere import DbSpheres
        from open_webui.routers.dbsphere import decrypt_connection_password

        for dbsphere_id in self.dbsphere_ids:
            dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
            if not dbsphere:
                logger.warning(f"DbSphere not found: {dbsphere_id}")
                continue

            self.dbsphere_names[dbsphere_id] = dbsphere.name

            data = dbsphere.data
            if not data:
                continue

            data = decrypt_connection_password(copy.deepcopy(data))
            db_config = DBConfig.from_dbsphere_data(data)

            runner = self._create_sql_runner_for_config(db_config)
            if not runner:
                # No runner but still provide pre-extracted schema
                fallback = dbsphere.data.get("schema_summary") or ""
                overview = dbsphere.data.get("table_overview") or ""
                if fallback or overview:
                    self.schema_info_map[dbsphere_id] = (
                        (fallback + "\n\n" + overview).strip()
                        if fallback and overview
                        else (fallback or overview)
                    )
                continue
            if runner:
                self.sql_runners[dbsphere_id] = runner
                try:
                    schema = await runner.get_schema_info()
                    self.schema_info_map[dbsphere_id] = schema
                except Exception as e:
                    logger.warning(f"Failed to get live schema for {dbsphere_id}: {e}")
                    # Fallback: use pre-extracted schema from DbSphere data
                    fallback = dbsphere.data.get("schema_summary") or ""
                    overview = dbsphere.data.get("table_overview") or ""
                    if fallback or overview:
                        self.schema_info_map[dbsphere_id] = (
                            (fallback + "\n\n" + overview).strip()
                            if fallback and overview
                            else (fallback or overview)
                        )
                        logger.info(f"Using pre-extracted schema for {dbsphere_id}")
                    else:
                        self.schema_info_map[dbsphere_id] = "Schema unavailable"

    def _create_sql_runner_for_config(self, db_config: DBConfig):
        """DBConfig에서 SQL runner 생성 (factory 위임 — 단일 진실원)."""
        from extension_modules.dbsphere.sql_runners import create_sql_runner

        return create_sql_runner(db_config)

    def get_tools(self, include_ask_user: bool = False) -> List[StructuredTool]:
        """에이전트 도구 생성."""
        tools = []

        # 각 DbSphere에 대한 run_sql 도구 (첫 번째 runner 사용)
        if self.sql_runners:
            first_runner = next(iter(self.sql_runners.values()))
            tools.append(
                create_run_sql_tool(
                    sql_runner=first_runner,
                    working_directory="data/cache/dashboard_builder",
                )
            )

        # 대시보드 도구
        tools.append(create_card_panel_tool())
        tools.append(create_chart_panel_tool())
        tools.append(create_set_layout_tool())

        if include_ask_user:
            tools.append(create_ask_user_tool())
            tools.append(create_delete_panel_tool())
            tools.append(create_set_existing_layout_tool())

        return tools

    def _get_date_filter_guide(self) -> str:
        """DB 타입에 맞는 날짜 필터 가이드 생성."""
        from extension_modules.dbsphere.dbsphere_state import DBType

        db_types = set()
        for dbsphere_id, runner in self.sql_runners.items():
            if hasattr(runner, "db_config") and hasattr(
                runner.db_config, "get_db_type_enum"
            ):
                db_types.add(runner.db_config.get_db_type_enum())

        guides = []
        for db_type in db_types:
            if db_type == DBType.ORACLE:
                guides.append("""#### Oracle
- DATE column: `col >= TO_DATE('$st','YYYY-MM-DD') AND col < TO_DATE('$ed','YYYY-MM-DD') + 1`
- TIMESTAMP column: `col >= TO_TIMESTAMP('$st 00:00:00','YYYY-MM-DD HH24:MI:SS') AND col < TO_TIMESTAMP('$ed 00:00:00','YYYY-MM-DD HH24:MI:SS') + 1`
- NEVER use `INTERVAL '1 day'` — use `+ 1` instead
- NEVER use `DATE_TRUNC()` — use `TRUNC(col, 'DD')` instead
- NEVER use `EXTRACT(DOW FROM col)` — use `TO_CHAR(col, 'D')` instead""")
            elif db_type in (DBType.MSSQL, DBType.SYNAPSE, DBType.FABRIC):
                guides.append("""#### MSSQL / Synapse / Fabric
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= '$st' AND col < DATEADD(day, 1, '$ed')`""")
            elif db_type == DBType.MYSQL:
                guides.append("""#### MySQL
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= '$st' AND col < DATE_ADD('$ed', INTERVAL 1 DAY)`""")
            elif db_type == DBType.SNOWFLAKE:
                guides.append("""#### Snowflake
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= '$st' AND col < DATEADD(day, 1, '$ed'::DATE)`""")
            elif db_type == DBType.DATABRICKS:
                guides.append("""#### Databricks
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= '$st' AND col < DATE_ADD('$ed', 1)`""")
            elif db_type == DBType.BIGQUERY:
                guides.append("""#### BigQuery
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= TIMESTAMP('$st') AND col < TIMESTAMP(DATE_ADD(DATE('$ed'), INTERVAL 1 DAY))`""")
            else:
                guides.append("""#### PostgreSQL (default)
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= '$st' AND col < CAST('$ed' AS DATE) + INTERVAL '1 day'`""")

        if not guides:
            guides.append("""#### General
- DATE column: `col BETWEEN '$st' AND '$ed'`
- TIMESTAMP column: `col >= '$st' AND col < '$ed'::DATE + INTERVAL '1 day'`""")

        return "\n\n".join(guides)

    def _build_system_prompt(self) -> str:
        """스키마 정보를 포함한 시스템 프롬프트 생성."""
        schema_sections = []
        for dbsphere_id, schema in self.schema_info_map.items():
            name = self.dbsphere_names.get(dbsphere_id, dbsphere_id)
            schema_sections.append(f"### {name} (dbsphere_id: {dbsphere_id})\n{schema}")

        schema_info = "\n\n".join(schema_sections)
        date_filter_guide = self._get_date_filter_guide()
        return DASHBOARD_BUILDER_SYSTEM_PROMPT.format(
            schema_info=schema_info,
            date_filter_guide=date_filter_guide,
        )

    async def _build_resource_context(self) -> str:
        """Build available DbSphere resources context for chat system prompt.

        Only includes DbSpheres the user has read access to.
        """
        lines = []
        user_id = self.metadata.get("user_id", "")
        user_role = self.metadata.get("user_role", "user")
        is_admin = user_role == "admin"

        try:
            from open_webui.models.dbsphere import DbSpheres

            if is_admin:
                all_dbspheres = DbSpheres.get_dbspheres()
            else:
                all_dbspheres = DbSpheres.get_dbspheres_by_user_id(user_id, "read")

            if all_dbspheres:
                lines.append("### Available Databases (DbSphere)")
                for db in all_dbspheres:
                    db_type = ""
                    if db.data and isinstance(db.data, dict):
                        db_type = db.data.get("db_type", "")
                    lines.append(f"- ID: `{db.id}` | Name: {db.name} | Type: {db_type}")
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to load DbSpheres: {e}")

        return "\n".join(lines) if lines else "(No databases available)"

    async def run_chat(
        self,
        messages: list,
        model_id: str,
        existing_panels: Optional[List[Dict]] = None,
    ) -> Dict:
        """Multi-turn conversational dashboard building.

        Args:
            messages: Conversation history [{"role": "user"|"assistant", "content": "..."}]
            model_id: LLM model for the builder agent
            existing_panels: Current panels in dashboard (for modification context)

        Returns:
            {
                "assistant_message": str,
                "pending_input": {"question": str, "options": [str]} or None,
                "panel_definitions": [...] or None,
                "layout_config": {...} or None,
            }
        """
        from extension_modules.utils.llm import create_llm_from_app

        # If specific DbSpheres are already loaded (user selected or from existing panels),
        # only show those — don't list all available DBs to avoid LLM asking "which DB?"
        if self.schema_info_map:
            schema_sections = []
            for dbsphere_id, schema in self.schema_info_map.items():
                name = self.dbsphere_names.get(dbsphere_id, dbsphere_id)
                schema_sections.append(
                    f"### {name} (dbsphere_id: {dbsphere_id})\n{schema}"
                )
            resource_context = (
                "### Selected Database(s) — use these directly, do NOT ask which database to use.\n\n"
                + "### Database Schemas\n"
                + "\n\n".join(schema_sections)
            )
        else:
            resource_context = await self._build_resource_context()

        # Build existing panels context with layout info
        existing_context = "No existing panels."
        if existing_panels:
            panel_summary = []
            for i, p in enumerate(existing_panels):
                layout = p.get("layout", {})
                layout_str = ""
                if layout:
                    layout_str = (
                        f" @ x={layout.get('x', 0)},y={layout.get('y', 0)},"
                        f"w={layout.get('w', 6)},h={layout.get('h', 4)}"
                    )
                panel_summary.append(
                    f"  existing_{i}: {p.get('name', 'Panel')} "
                    f"(type={p.get('panel_type', p.get('type', 'chart'))}, "
                    f"chart={p.get('chart_type', 'N/A')}{layout_str})"
                )
            existing_context = (
                "The dashboard already has these panels with their grid positions:\n"
                + "\n".join(panel_summary)
                + "\n\nWhen adding panels, use panel_index starting from "
                + str(len(existing_panels))
                + " in set_dashboard_layout."
                + "\nTo place a NEW panel at the TOP (y=0), you must ALSO update "
                + "existing panels' y positions by shifting them down. Use "
                + "set_existing_panel_layout to reposition existing panels."
            )

        date_filter_guide = self._get_date_filter_guide()
        system_prompt = DASHBOARD_BUILDER_CHAT_PROMPT.format(
            available_resources=resource_context,
            existing_panels_context=existing_context,
            date_filter_guide=date_filter_guide,
        )

        llm = create_llm_from_app(
            self.request.app,
            model_id,
            model_kwargs={"temperature": 0.3, "max_tokens": 8192},
        )

        tools = self.get_tools(include_ask_user=True)
        agent = create_agent(
            llm,
            tools,
            system_prompt=system_prompt,
            state_schema=DashboardBuilderState,
        )

        logger.info(f"DashboardBuilderAgent chat: {len(messages)} messages")

        result = await agent.ainvoke({"messages": messages})

        # Extract last AI message
        assistant_message = ""
        result_messages = result.get("messages", [])
        for msg in reversed(result_messages):
            content = getattr(msg, "content", "") if hasattr(msg, "content") else ""
            msg_type = getattr(msg, "type", "")
            if msg_type == "ai" and content and "ASK_USER:" not in content:
                assistant_message = content
                break

        # Check if ask_user was called
        pending_input = None
        for msg in result_messages:
            content = getattr(msg, "content", "") if hasattr(msg, "content") else ""
            if "ASK_USER:" in str(content):
                try:
                    parts = content.split("::OPTIONS:")
                    question = parts[0].replace("ASK_USER:", "").strip()
                    options = parts[1].split("|") if len(parts) > 1 and parts[1] else []
                    options = [o.strip() for o in options if o.strip()]
                    pending_input = {"question": question, "options": options}
                    if not assistant_message:
                        assistant_message = question
                except Exception:
                    pass

        # Extract panel definitions + layout
        panel_definitions = result.get("panel_definitions", [])
        layout_config = result.get("layout_config", {})

        # Apply layout to panels
        if panel_definitions:
            layout_panels = layout_config.get("panels", [])
            for lp in layout_panels:
                idx = lp.get("panel_index", -1)
                if 0 <= idx < len(panel_definitions):
                    panel_definitions[idx]["layout"] = {
                        "x": lp.get("x", 0),
                        "y": lp.get("y", 0),
                        "w": lp.get("w", 6),
                        "h": lp.get("h", 4),
                    }
            # Default layouts for panels without one
            for i, panel in enumerate(panel_definitions):
                if "layout" not in panel:
                    if panel.get("type") == "card":
                        panel["layout"] = {"x": (i * 3) % 12, "y": 0, "w": 3, "h": 1}
                    else:
                        row = 1 + (i // 2) * 4
                        col = (i % 2) * 6
                        panel["layout"] = {"x": col, "y": row, "w": 6, "h": 4}

        return {
            "assistant_message": assistant_message,
            "pending_input": pending_input,
            "panel_definitions": panel_definitions if panel_definitions else None,
            "layout_config": layout_config if layout_config else None,
            "_raw_messages": result_messages,
        }

    async def save_panels(
        self,
        user_id: str,
        dashboard_id: str,
        panel_definitions: List[Dict],
    ) -> List[str]:
        """Save panel definitions to an existing dashboard. Returns panel IDs."""
        from open_webui.models.bi_dashboard import BiPanelForm, BiPanels

        panel_ids = []
        for panel_def in panel_definitions:
            panel_type = panel_def.get("type", "chart")
            panel = BiPanels.insert_new_panel(
                user_id,
                dashboard_id,
                BiPanelForm(
                    name=panel_def.get("name", "Panel"),
                    dbsphere_id=panel_def.get("dbsphere_id", ""),
                    data={
                        "panel_type": panel_type,
                        "nl_query": panel_def.get("nl_query", ""),
                        "sql": panel_def.get("sql", ""),
                        "sql_template": panel_def.get("sql_template", "")
                        or panel_def.get("sql", ""),
                        "chart_type": panel_def.get("chart_type", "bar"),
                        "card_source": panel_def.get("card_source", "db"),
                        "card_table": panel_def.get("card_table", ""),
                        "card_column": panel_def.get("card_column", ""),
                        "card_agg": panel_def.get("card_agg", ""),
                        "card_bg_color": panel_def.get("card_bg_color", ""),
                        "layout": panel_def.get(
                            "layout", {"x": 0, "y": 0, "w": 6, "h": 4}
                        ),
                        "show_title": panel_def.get("show_title", True),
                        "title_position": panel_def.get(
                            "title_position", "inside-bottom"
                        ),
                        "use_time_filter": panel_def.get("use_time_filter", False),
                        "date_column": panel_def.get("date_column", ""),
                    },
                ),
            )
            if panel:
                panel_ids.append(panel.id)
        return panel_ids

    async def run(
        self,
        model_id: str,
        dashboard_name: str,
        user_prompt: str | None = None,
    ) -> Dict[str, Any]:
        """에이전트 실행 → 대시보드 자동 생성 (단일 호출, 하위호환)."""
        from extension_modules.utils.llm import get_model_config_from_app

        model_config = get_model_config_from_app(self.request.app, model_id)
        if not model_config:
            raise ValueError(f"Model not found: {model_id}")

        # LLM 생성
        from extension_modules.utils.llm import create_llm

        llm = create_llm(model_config, model_kwargs={"temperature": 0.3})

        # 도구
        tools = self.get_tools()

        # 시스템 프롬프트
        system_prompt = self._build_system_prompt()

        # 에이전트 생성 (기존 DBSphereAgent와 동일한 패턴)
        agent = create_agent(
            llm,
            tools,
            system_prompt=system_prompt,
            state_schema=DashboardBuilderState,
        )

        # 실행
        user_message = (
            f"Analyze the database schemas and create a dashboard named '{dashboard_name}'. "
            f"Create meaningful card panels for KPIs and chart panels for data visualization."
        )
        if user_prompt:
            user_message += f"\n\nUser's specific request: {user_prompt}"

        result = await agent.ainvoke(
            {
                "messages": [{"role": "user", "content": user_message}],
                "schema_info": "\n".join(self.schema_info_map.values()),
            }
        )

        # 패널 정의 + 레이아웃 추출
        panel_definitions = result.get("panel_definitions", [])
        layout_config = result.get("layout_config", {})

        # 레이아웃을 패널에 적용
        layout_panels = layout_config.get("panels", [])
        for lp in layout_panels:
            idx = lp.get("panel_index", -1)
            if 0 <= idx < len(panel_definitions):
                panel_definitions[idx]["layout"] = {
                    "x": lp.get("x", 0),
                    "y": lp.get("y", 0),
                    "w": lp.get("w", 6),
                    "h": lp.get("h", 4),
                }

        # 레이아웃 미설정 패널에 기본값
        for i, panel in enumerate(panel_definitions):
            if "layout" not in panel:
                if panel.get("type") == "card":
                    panel["layout"] = {"x": (i * 3) % 12, "y": 0, "w": 3, "h": 1}
                else:
                    row = 1 + (i // 2) * 4
                    col = (i % 2) * 6
                    panel["layout"] = {"x": col, "y": row, "w": 6, "h": 4}

        return {
            "panel_definitions": panel_definitions,
            "dashboard_name": dashboard_name,
        }

    async def save_dashboard(
        self, user_id: str, dashboard_name: str, panel_definitions: List[Dict]
    ) -> str:
        """에이전트 결과를 BiDashboard + BiPanel로 저장."""
        from open_webui.models.bi_dashboard import (
            BiDashboardForm,
            BiDashboards,
            BiPanelForm,
            BiPanels,
        )

        # 대시보드 생성
        dashboard = BiDashboards.insert_new_dashboard(
            user_id, BiDashboardForm(name=dashboard_name)
        )
        if not dashboard:
            raise ValueError("Failed to create dashboard")

        # 패널 저장
        for panel_def in panel_definitions:
            panel_type = panel_def.get("type", "chart")
            BiPanels.insert_new_panel(
                user_id,
                dashboard.id,
                BiPanelForm(
                    name=panel_def.get("name", "Panel"),
                    dbsphere_id=panel_def.get("dbsphere_id", ""),
                    data={
                        "panel_type": panel_type,
                        "nl_query": panel_def.get("nl_query", ""),
                        "sql": panel_def.get("sql", ""),
                        "sql_template": panel_def.get("sql_template", "")
                        or panel_def.get("sql", ""),
                        "chart_type": panel_def.get("chart_type", "bar"),
                        "card_source": panel_def.get("card_source", "db"),
                        "card_table": panel_def.get("card_table", ""),
                        "card_column": panel_def.get("card_column", ""),
                        "card_agg": panel_def.get("card_agg", ""),
                        "card_bg_color": panel_def.get("card_bg_color", ""),
                        "layout": panel_def.get(
                            "layout", {"x": 0, "y": 0, "w": 6, "h": 4}
                        ),
                        "show_title": panel_def.get("show_title", True),
                        "title_position": panel_def.get(
                            "title_position", "inside-bottom"
                        ),
                        "use_time_filter": panel_def.get("use_time_filter", False),
                        "date_column": panel_def.get("date_column", ""),
                    },
                ),
            )

        return dashboard.id
