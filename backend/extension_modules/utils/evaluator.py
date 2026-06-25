import os

from langchain.tools import ToolRuntime
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel, Field


class EvaluateSearchResultsOutput(BaseModel):
    score: int = Field(
        ...,
        description="""1~5 사이의 점수를 반환합니다.
    1: 검색 결과가 질의에 대한 답변이 불가능한 근거입니다.
    2: 검색 결과가 질의에 대한 약간의 답변이 가능한 근거입니다.
    3: 검색 결과가 질의에 대한 일부 답변이 가능한 근거입니다.
    4: 검색 결과가 질의에 대한 답변이 충분히 가능한 근거입니다.
    5: 검색 결과가 질의에 대한 답변 및 추가적인 정보를 제공 가능한 근거입니다.""",
    )
    reason: str = Field(
        ...,
        description="검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하는 이유를 반환합니다.",
    )


class EvaluateSearchResultsInput(BaseModel):
    pass


AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")


async def evaluate_search_results(runtime: ToolRuntime) -> EvaluateSearchResultsOutput:
    model = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT,
        api_version=AZURE_OPENAI_API_VERSION,
        api_key=AZURE_OPENAI_API_KEY,
        temperature=0.0,
    )
    sources = runtime.state.get("sources", [])
    question = runtime.state.get("user_question", "")

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                f"""당신은 검색 결과를 평가하는 도우미입니다. 검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하고 점수와 이유를 반환합니다. 응답 스키마는 아래와 같습니다.
            {PydanticOutputParser(pydantic_object=EvaluateSearchResultsOutput).get_format_instructions()}
            """,
            ),
            ("user", "질의: {question} 검색 결과: {sources}"),
        ]
    )

    chain = (
        prompt
        | model
        | PydanticOutputParser(pydantic_object=EvaluateSearchResultsOutput)
    )
    result = await chain.ainvoke({"question": question, "sources": sources})
    return result.get("output")
