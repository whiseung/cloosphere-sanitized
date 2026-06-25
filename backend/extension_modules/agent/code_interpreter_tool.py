"""Code Interpreter tools for data analysis projects.

3-stage tool design (like DbSphere):
  Stage 1: data_file_info — file list + column overview (always call first)
  Stage 2: get_file_details — detailed column info + sample data for a specific file
  Stage 3: code_interpreter — execute Python code in Jupyter
"""

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PLOTLY_JSON_MARKER = "__PLOTLY_JSON__"


# ──────────────────────────────────────
# Input schemas
# ──────────────────────────────────────


class GetFileDetailsInput(BaseModel):
    filename: str = Field(
        ...,
        description="The filename to get detailed column information for.",
    )


class CodeInterpreterInput(BaseModel):
    code: str = Field(
        ...,
        description="Complete Python code to execute. Always use print() to output results.",
    )


# ──────────────────────────────────────
# Result formatting
# ──────────────────────────────────────


def _format_result(result) -> str:
    """Format Jupyter execution result for the agent."""
    parts = []
    if result.stdout:
        for line in result.stdout.split("\n"):
            parts.append(line)
    if result.result:
        for item in result.result.split("\n"):
            if item.startswith("data:image/png;base64,"):
                parts.append(f"![chart]({item})")
            else:
                parts.append(item)
    if result.stderr:
        stderr = result.stderr
        if stderr and "UserWarning" not in stderr and "FutureWarning" not in stderr:
            parts.append(f"Error:\n```\n{stderr}\n```")
    return "\n".join(parts) if parts else "(No output)"


# ──────────────────────────────────────
# Stage 1: data_file_info
# ──────────────────────────────────────


def create_data_file_info_tool(
    file_metadata: Dict[str, Any],
    workspace_path: str,
) -> StructuredTool:
    """Stage 1: Returns overview of all uploaded data files."""

    async def data_file_info() -> str:
        if not file_metadata:
            return "No data files uploaded."

        lines = [f"# Uploaded Data Files ({len(file_metadata)} files)\n"]
        for file_id, meta in file_metadata.items():
            filename = meta.get("filename", file_id)
            row_count = meta.get("row_count", "?")
            columns = meta.get("columns", [])

            col_names = ", ".join(columns[:10])
            if len(columns) > 10:
                col_names += f", ... (+{len(columns) - 10})"

            lines.append(f"- **{filename}** ({row_count} rows)")
            lines.append(f"  Columns: {col_names}")

            sheets = meta.get("sheets")
            if sheets:
                sheet_counts = meta.get("sheet_row_counts", {})
                sheet_info = ", ".join(
                    f"{s}({sheet_counts.get(s, '?')}행)" for s in sheets
                )
                lines.append(f"  Sheets: {sheet_info}")

        lines.append("")
        lines.append(
            "Call `get_file_details` with a filename to see data types, "
            "unique/null counts, sample values, and first rows."
        )
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=data_file_info,
        name="data_file_info",
        description=(
            "Get an overview of all uploaded data files including file names, "
            "row counts, column names, and sheet info (for Excel). "
            "Call this FIRST to understand what data is available."
        ),
    )


# ──────────────────────────────────────
# Stage 2: get_file_details
# ──────────────────────────────────────


def create_get_file_details_tool(
    file_metadata: Dict[str, Any],
    workspace_path: str,
) -> StructuredTool:
    """Stage 2: Returns detailed column info + sample data for a specific file."""

    async def get_file_details(filename: str) -> str:
        target_meta = None
        for file_id, meta in file_metadata.items():
            if meta.get("filename") == filename:
                target_meta = meta
                break

        if not target_meta:
            available = [m.get("filename", fid) for fid, m in file_metadata.items()]
            return f"File '{filename}' not found. Available files: {available}"

        lines = [f"# {filename} — Detailed Column Info\n"]
        lines.append(f"Path: `{filename}` (use filename directly, no path prefix)")
        lines.append(f"Rows: {target_meta.get('row_count', '?')}\n")

        column_details = target_meta.get("column_details", {})
        if column_details:
            lines.append("## Columns\n")
            lines.append("| Column | Type | Unique | Nulls | Sample Values |")
            lines.append("|--------|------|--------|-------|---------------|")
            for col, detail in column_details.items():
                dtype = detail.get("dtype", "?")
                unique = detail.get("unique_count", "?")
                nulls = detail.get("null_count", 0)
                samples = detail.get("sample_values", [])[:3]
                sample_str = ", ".join(str(s) for s in samples)
                lines.append(f"| {col} | {dtype} | {unique} | {nulls} | {sample_str} |")
        else:
            dtypes = target_meta.get("dtypes", {})
            for col, dtype in dtypes.items():
                lines.append(f"- **{col}**: {dtype}")

        sample = target_meta.get("sample_markdown", "")
        if sample:
            lines.append(f"\n## Sample Data (first 3 rows)\n\n{sample}")

        sheets = target_meta.get("sheets")
        if sheets and len(sheets) > 1:
            lines.append(f"\n## Sheets: {', '.join(sheets)}")
            lines.append(
                f"Default sheet loaded: '{sheets[0]}'. "
                f"Use `pd.read_excel(path, sheet_name='시트명')` for other sheets."
            )

        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=get_file_details,
        name="get_file_details",
        description=(
            "Get detailed column information for a specific data file, "
            "including data types, unique/null counts, sample values, "
            "and first 3 rows of data. "
            "Call this after data_file_info to understand a file's structure "
            "before writing analysis code."
        ),
        args_schema=GetFileDetailsInput,
    )


# ──────────────────────────────────────
# Stage 3: code_interpreter
# ──────────────────────────────────────


def create_code_interpreter_tool(
    app,
    project_context: Dict[str, Any],
    event_emitter: Optional[Callable] = None,
) -> Optional[StructuredTool]:
    """Stage 3: Execute Python code in Jupyter with access to data files."""
    engine = app.state.config.CODE_EXECUTION_ENGINE
    jupyter_url = app.state.config.CODE_EXECUTION_JUPYTER_URL

    if engine != "jupyter" or not jupyter_url:
        logger.warning(
            "Code interpreter requires Jupyter engine. Current engine: %s, URL: %s",
            engine,
            jupyter_url,
        )
        return None

    # Verify Jupyter connectivity at tool creation time
    import aiohttp

    async def _check_jupyter():
        try:
            token = app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN
            params = {"token": token} if token else {}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{jupyter_url}/api/status",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.ok
        except Exception as e:
            logger.warning("Jupyter connectivity check failed: %s", e)
            return False

    project_id = project_context["id"]
    stored_kernel_id = project_context.get("jupyter_kernel_id")

    async def code_interpreter(code: str) -> str:
        from open_webui.models.projects import Projects
        from open_webui.utils.jupyter_session import JupyterSessionManager

        # Check Jupyter connectivity
        if not await _check_jupyter():
            error_msg = (
                "Jupyter server is not reachable. "
                "Please check Admin > Settings > Code Execution configuration."
            )
            if event_emitter:
                await event_emitter(
                    {
                        "type": "source",
                        "data": {
                            "type": "code_execution",
                            "id": str(uuid.uuid4()),
                            "name": "Code Interpreter",
                            "code": code,
                            "language": "python",
                            "status": "error",
                            "result": {"error": error_msg},
                        },
                    }
                )
            return f"Error: {error_msg}"

        execution_id = str(uuid.uuid4())

        # Emit: code execution started (shows code in frontend)
        if event_emitter:
            await event_emitter(
                {
                    "type": "source",
                    "data": {
                        "type": "code_execution",
                        "id": execution_id,
                        "name": "Code Interpreter",
                        "code": code,
                        "language": "python",
                        "status": "running",
                    },
                }
            )

        mgr = JupyterSessionManager(
            base_url=jupyter_url,
            token=app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
            password=app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
            timeout=app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        )

        kernel_id = await mgr.ensure_kernel(project_id, stored_kernel_id)
        if kernel_id != stored_kernel_id:
            Projects.update_project_data(project_id, {"jupyter_kernel_id": kernel_id})

        result = await mgr.execute_code(kernel_id, code)
        formatted = _format_result(result)

        # Emit: code execution completed (shows result in frontend)
        if event_emitter:
            await event_emitter(
                {
                    "type": "source",
                    "data": {
                        "type": "code_execution",
                        "id": execution_id,
                        "name": "Code Interpreter",
                        "code": code,
                        "language": "python",
                        "status": "completed" if not result.stderr else "error",
                        "result": {
                            "output": result.stdout or "",
                            "error": result.stderr or "",
                        },
                    },
                }
            )

        return formatted

    return StructuredTool.from_function(
        coroutine=code_interpreter,
        name="code_interpreter",
        description=f"""Execute Python code in a Jupyter environment for data analysis.
Available packages: pandas, numpy, plotly, scipy, sklearn.
Working directory is set to the project workspace — use filenames directly (no path prefix needed).

CRITICAL: You MUST call this tool to execute code BEFORE producing your final result — do NOT finish (submit_result) until at least one code_interpreter execution has run. NEVER write code as plain text; always execute it here. NEVER assume or fabricate data values — run code to get real results. The data files are already loaded in the workspace; never ask the user to upload files.

How to use:
- Load: pd.read_csv('<file>.csv') or pd.read_excel('<file>.xlsx', sheet_name='시트명')
- Tables: print(df.to_markdown(index=False)) — renders as downloadable table
- Charts: Use plotly (NOT matplotlib):
    import plotly.express as px
    fig = px.pie(df, names='col', values='val', title='Title')
    print('{PLOTLY_JSON_MARKER}' + fig.to_json())
- Always print() results. Variable state persists across calls.""",
        args_schema=CodeInterpreterInput,
    )


# ──────────────────────────────────────
# Create all tools
# ──────────────────────────────────────


def create_code_interpreter_tools(
    app,
    project_context: Dict[str, Any],
    event_emitter: Optional[Callable] = None,
) -> List[StructuredTool]:
    """Create the 3-stage code interpreter tool set.

    Returns:
        List of tools: [data_file_info, get_file_details, code_interpreter]
    """
    file_metadata = project_context.get("file_metadata", {})
    project_id = project_context["id"]
    workspace_path = f"workspace/{project_id}"

    tools = [
        create_data_file_info_tool(file_metadata, workspace_path),
        create_get_file_details_tool(file_metadata, workspace_path),
    ]

    ci_tool = create_code_interpreter_tool(app, project_context, event_emitter)
    if ci_tool:
        tools.append(ci_tool)

    return tools
