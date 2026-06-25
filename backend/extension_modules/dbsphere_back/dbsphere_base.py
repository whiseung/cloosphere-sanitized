from enum import Enum

from pydantic import BaseModel
from vanna.core.llm import LlmRequest, LlmResponse
from vanna.core.middleware import LlmMiddleware


class DBSphereAgentState(BaseModel):
    chart_data: str = ""
    query_data: list[str] = []
    llm_response: str = ""


class DBSphereMiddleware(LlmMiddleware):
    async def before_llm_request(self, request: LlmRequest) -> LlmRequest:
        return request

    async def after_llm_response(
        self, request: LlmRequest, response: LlmResponse
    ) -> LlmResponse:
        return response


class DBType(Enum):
    POSTGRES = "postgres"
    MYSQL = "mysql"
    MSSQL = "mssql"


class DBConfig(BaseModel):
    db_type: DBType
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
