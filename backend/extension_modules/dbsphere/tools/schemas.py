"""Pydantic input schemas for DBSphere V2 tools."""

from typing import Optional

from extension_modules.dbsphere.chart.plotly_generator import ChartType
from pydantic import BaseModel, Field


class RunSqlInput(BaseModel):
    """Input schema for the run_sql tool."""

    sql: str = Field(
        description="The SQL query to execute. Must be a SELECT query for safety."
    )


class VisualizeDataInput(BaseModel):
    """Input schema for the visualize_data tool."""

    filename: str = Field(
        description="Name of the CSV file to visualize (from run_sql output)"
    )
    title: Optional[str] = Field(
        default=None,
        description="Optional title for the chart. If not provided, will be auto-generated.",
    )
    chart_type: ChartType = Field(
        default=ChartType.AUTO,
        description=(
            "Chart type to generate. "
            "Only specify a chart type if the user explicitly requests it. "
            "Otherwise, use 'auto' and the system will select the best chart type "
            "based on the data structure."
        ),
    )


class GetTableDetailsInput(BaseModel):
    """Input schema for the get_table_details tool."""

    table_names: Optional[list[str]] = Field(
        default=None,
        description="Table names from dbsphere_info to get DDL and column details",
    )
    query: Optional[str] = Field(
        default=None,
        description=(
            "Natural language query to find related documentation, "
            "SQL examples, and similar past queries"
        ),
    )


class ExtractContextInfoInput(BaseModel):
    """Input schema for extracting context information from questions."""

    language: str = Field(
        description="The detected language of the question (e.g., 'Korean', 'English')"
    )
    normalized_question: str = Field(
        description="The question rewritten to be standalone and clear without conversation context"
    )
