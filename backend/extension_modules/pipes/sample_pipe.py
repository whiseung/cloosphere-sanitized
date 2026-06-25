import os
from datetime import date
from typing import Any, Dict

from extension_modules.pipes.base import ReactAgentBasePipe
from extension_modules.tools.sscnt_design import DesignModel

# LangChain / LangGraph / Azure OpenAI
from langchain_openai import AzureChatOpenAI

# MCP Client
from pydantic import BaseModel, Field

SLEEP_TIME = float(os.getenv("SLEEP_TIME", "0.05"))


class Pipe(ReactAgentBasePipe):
    class Valves(BaseModel):
        SYSTEM_PROMPT: str = Field(
            default=(
                f"""
                현재 날짜는 {date.today()} 입니다.
                
                """
            )
        )
        PROJECT_INDEX_NAME: str = Field(default="project_list_v2")
        AZURE_ENDPOINT: str = Field(default="")
        AZURE_DEPLOYMENT: str = Field(default="")
        AZURE_API_VERSION: str = Field(default="2025-04-01-preview")
        AZURE_API_KEY: str = Field(default="")
        TOP_K: int = Field(default=10)

    def __init__(self):
        valves = self.Valves()
        tool = DesignModel(valves)
        model = AzureChatOpenAI(
            azure_endpoint=valves.AZURE_ENDPOINT,
            azure_deployment=valves.AZURE_DEPLOYMENT,
            api_version=valves.AZURE_API_VERSION,
            api_key=valves.AZURE_API_KEY,
            model_kwargs={"stream_options": {"include_usage": True}},
        )

        super().__init__(model=model, tool=tool, valves=valves)

    async def pipe(
        self,
        body: Dict[str, Any],
        __user__: dict,
        __event_emitter__=None,
        __metadata__=None,
        __task__=None,
        __request__=None,
    ):
        async for chunk in self._pipe(
            body=body,
            __user__=__user__,
            __event_emitter__=__event_emitter__,
            __metadata__=__metadata__,
            __task__=__task__,
            __request__=__request__,
        ):
            yield chunk
