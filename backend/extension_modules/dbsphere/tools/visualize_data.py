"""Data visualization tool for DBSphere V2."""

import io
import logging
import os
from typing import Optional

import pandas as pd
from extension_modules.dbsphere.chart.plotly_generator import (
    ChartType,
    PlotlyChartGenerator,
)
from extension_modules.dbsphere.dbsphere_state import DBSphereAgentState
from extension_modules.dbsphere.tools.schemas import VisualizeDataInput
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

logger = logging.getLogger(__name__)


def create_visualize_data_tool(
    working_directory: str = "data/cache/dbsphere_v2",
    chart_generator: Optional[PlotlyChartGenerator] = None,
) -> StructuredTool:
    """
    Create a LangChain StructuredTool for data visualization.

    Args:
        working_directory: Directory where CSV files are stored
        chart_generator: PlotlyChartGenerator instance (optional)

    Returns:
        StructuredTool for visualization
    """
    generator = chart_generator or PlotlyChartGenerator()

    async def visualize_data(
        filename: str,
        title: Optional[str],
        chart_type: ChartType,
        runtime: ToolRuntime[None, DBSphereAgentState],
    ) -> Command:
        """
        Create a visualization from a CSV file.

        Args:
            filename: Name of the CSV file to visualize
            title: Optional chart title
            chart_type: Type of chart to generate
            runtime: Tool runtime context

        Returns:
            Command with state updates and tool message
        """
        try:
            logger.info(f"Creating visualization for file: {filename}")

            # Read the CSV file
            filepath = os.path.join(working_directory, filename)
            if not os.path.exists(filepath):
                error_msg = f"File not found: {filename}"
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=error_msg,
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )

            with open(filepath, "r", encoding="utf-8") as f:
                csv_content = f.read()

            # Parse CSV into DataFrame
            df = pd.read_csv(io.StringIO(csv_content))
            logger.info(f"Parsed DataFrame with shape {df.shape}")

            if df.empty:
                error_msg = "Cannot visualize empty DataFrame"
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=error_msg,
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )

            # Generate title if not provided
            chart_title = title or f"Visualization of {filename}"

            # Generate chart
            chart_dict = generator.generate_chart(df, chart_title, chart_type)
            logger.info(
                f"Chart generated with type: {chart_dict.get('used_chart_type')}"
            )

            # Prepare result message
            row_count = len(df)
            col_count = len(df.columns)
            used_type = chart_dict.get("used_chart_type", "auto")
            status = chart_dict.get("status", "")

            result_message = f"""Visualization created successfully.

**Data:** {row_count} rows, {col_count} columns
**Chart type:** {used_type}
**Title:** {chart_title}
"""

            if status == "fallback_auto" and chart_dict.get("error_reason"):
                result_message += f"\n**Note:** {chart_dict['error_reason']}"

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=result_message,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                    "chart_data_list": [chart_dict],
                }
            )

        except pd.errors.ParserError as e:
            error_message = f"Failed to parse CSV file '{filename}': {str(e)}"
            logger.error(error_message, exc_info=True)

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=error_message,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )

        except ValueError as e:
            error_message = f"Cannot visualize data: {str(e)}"
            logger.error(error_message, exc_info=True)

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=error_message,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )

        except Exception as e:
            error_message = f"Error creating visualization: {str(e)}"
            logger.error(error_message, exc_info=True)

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=error_message,
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )

    return StructuredTool.from_function(
        coroutine=visualize_data,
        name="visualize_data",
        description=(
            "Create a visualization from a CSV file. "
            "The tool automatically selects an appropriate chart type based on the data structure. "
            "Only specify a chart_type if the user explicitly requests a specific type."
        ),
        args_schema=VisualizeDataInput,
    )
