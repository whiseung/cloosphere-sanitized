from typing import Any, Dict, Iterable, List, Optional, Union

from extension_modules.utils.azure_search import (
    AsyncAzureSearchClient,
    SearchSchemaBase,
)
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field


class HRSearchSchema(SearchSchemaBase):
    index_name: str = "default"
    id_field: str = "id"
    filter_expression: Optional[str] = (
        "collection eq '0ea7747b-7824-4d2d-9a7b-a96eedab4efd'"
    )
    select_fields: Optional[Union[str, List[str]]] = ["id", "content", "metadata"]
    text_search_fields: Optional[Union[str, List[str]]] = "content"
    vector_query_fields: Optional[Union[str, List[str]]] = "vector"
    semantic_configuration_name: Optional[str] = "my-semantic-config"


class HRSearchToolInput(BaseModel):
    queries: Union[str, Iterable[str]] = Field(
        ...,
        description="검색어를 제공하세요. 검색에 용이할 수 있는 문장으로 제공하며 필요 시 rewrite 해서 여러 질의를 제공할 수 있습니다.",
    )


class HRSearchToolItem(BaseModel):
    id: str = Field(..., description="문서 ID")
    content: str = Field(..., description="문서 내용")
    metadata: Dict[str, Any] = Field(..., description="문서 메타데이터")
    score: float = Field(..., description="문서 점수")


class HRSearchToolOutput(BaseModel):
    items: List[HRSearchToolItem] = Field(..., description="문서 목록")


@tool(name="_hr_search", args_schema=HRSearchToolInput)
async def _hr_search(queries: Union[str, Iterable[str]]) -> HRSearchToolOutput:
    """
    HR 검색 툴
    클루커스 사내 규정 및 사내 다양한 문서들을 검색할 수 있습니다.
    """
    qlist = [
        q.strip()
        for q in ([queries] if isinstance(queries, str) else list(queries))
        if q and q.strip()
    ]
    if not qlist:
        return "검색어가 없습니다."
    schema = HRSearchSchema()
    try:
        async with AsyncAzureSearchClient() as client:
            res = await client.asearch_hybrid(
                schemas=schema, queries=qlist, top_k=5, top_k_vector=8
            )
    except Exception:
        return "검색 중 일시적 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    items = res.get("items", [])
    if not items:
        return "검색 결과가 없습니다."
    return items


class HRSearchModel:
    def get_tool():
        hr_search_tool = StructuredTool.from_function(
            # 비동기 함수 사용. 동기 함수 사용 시 coroutine이 아닌 func을 사용해야 함
            coroutine=_hr_search,
            name="_hr_search",
            description="""
                        HR 검색 툴
                        클루커스 사내 규정 및 사내 다양한 문서들을 검색할 수 있습니다.
                    """,
            args_schema=HRSearchToolInput,
            # return_direct=True,
        )
        return [hr_search_tool]
