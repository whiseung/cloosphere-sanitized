"""State definitions for UnifiedAgent (DbSphere + KbSphere)."""

import operator
from typing import Annotated, Any, Dict, List

from extension_modules.react.react_base import AgentStateBase
from pydantic import BaseModel, Field


def _last_value(left, right):
    """Reducer that keeps the last value. Used for fields updated by parallel tool calls."""
    return right


class UnifiedAgentState(AgentStateBase):
    """
    Combined agent state for UnifiedAgent.

    Inherits from AgentStateBase which includes:
    - messages: List of conversation messages
    - normalized_question: str
    - language: str
    - eval_score: int
    - eval_reason: str
    - answerable: bool
    - attached_files: List[str]

    KbSphere fields:
    - country_codes: Language/country detection

    DbSphere fields:
    - executed_sql: The SQL query that was executed
    - query_result_file: Path to the CSV file containing query results
    - chart_data_list: Chart generation result data (list, supports multiple charts)
    - query_history: SQL queries executed in this session
    - db_dialect: Database dialect (PostgreSQL, MySQL, etc.)

    Unified fields:
    - active_capabilities: List of enabled capabilities (dbsphere, kbsphere)

    Note: Fields updated by tools use Annotated reducers to support
    parallel tool calls within the same LangGraph step.
    """

    # === KbSphere fields ===
    country_codes: List[str] = Field(default_factory=list)

    # === DbSphere fields ===
    # SQL execution state (last value wins when parallel tool calls)
    executed_sql: Annotated[str, _last_value] = ""
    query_result_file: Annotated[str, _last_value] = ""
    # Which dbsphere the last run_sql targeted (multi-DB: routes Q-SQL memory save)
    last_sql_dbsphere_id: Annotated[str, _last_value] = ""

    # Chart generation state (accumulates across multiple visualize_data calls)
    chart_data_list: Annotated[List[Dict[str, Any]], operator.add] = Field(
        default_factory=list
    )

    # Query history for this session (accumulates across tool calls)
    query_history: Annotated[List[str], operator.add] = Field(default_factory=list)

    # Database dialect
    db_dialect: str = "SQL"

    # === Unified fields ===
    active_capabilities: List[str] = Field(default_factory=list)
    task_prompt: str = ""


class UnifiedAgentOutput(BaseModel):
    """Lightweight structured output — signals data gathering is complete."""

    answerable: bool = Field(
        default=True,
        description=(
            "Set to true if you gathered enough information to answer the user's question. "
            "Set to false if no relevant data was found despite searching."
        ),
    )
    language: str = Field(
        default="Korean",
        description=(
            "The language to use for the response. "
            "1. If the user explicitly requests a specific language (e.g. '영어로 답해줘', 'answer in Japanese'), use that language. "
            "2. Otherwise, detect and match the language of the user's latest message. "
            "Examples: Korean, English, Japanese, Chinese, etc."
        ),
    )
