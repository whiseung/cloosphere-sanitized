"""
Glossary LangChain Tools

LLM이 사용자 질의에서 모르는 용어를 찾을 때 사용하는 도구입니다.
검색 엔진에 색인된 용어집에서 용어를 검색하여 정의, 동의어, 예시를 제공합니다.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI
from langchain_core.tools import StructuredTool
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, Field, create_model

from .service import GlossaryIndexService

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class GlossaryLookupInput(BaseModel):
    """용어집 용어 검색 도구 입력"""

    query: str = Field(
        ...,
        description="검색할 용어 또는 설명. 모르는 용어, 약어, 전문 용어 등을 검색합니다.",
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="반환할 최대 결과 수 (기본값: 3)",
    )


class GlossaryLookupOutput(BaseModel):
    """용어집 용어 검색 결과"""

    found: bool = Field(description="검색 결과 존재 여부")
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="검색된 용어 목록",
    )
    message: str = Field(
        default="",
        description="사용자에게 표시할 메시지",
    )


class GlossaryTools:
    """
    용어집 LangChain 도구 모음.

    Usage:
        >>> tools = GlossaryTools(app)
        >>> langchain_tools = tools.get_tools()
        >>> # 또는 특정 glossary_id로 제한
        >>> langchain_tools = tools.get_tools(glossary_ids=["glossary-123"])
    """

    def __init__(
        self,
        app: FastAPI,
        glossary_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
    ):
        """
        초기화.

        Args:
            app: FastAPI 앱 인스턴스 (설정 접근용)
            glossary_ids: 검색을 제한할 용어집 ID 목록 (None이면 전체 검색)
            description: 동적 도구 설명 (None이면 기본값 사용)
        """
        self.app = app
        self.glossary_ids = glossary_ids
        self._description = description
        self._service: Optional[GlossaryIndexService] = None

    @property
    def service(self) -> GlossaryIndexService:
        """용어집 서비스 인스턴스 (lazy initialization)"""
        if self._service is None:
            self._service = GlossaryIndexService(self.app)
        return self._service

    async def lookup_term(
        self,
        query: str,
        top_k: int = 3,
        glossary_ids: Optional[List[str]] = None,
    ) -> str:
        """
        용어집에서 용어를 검색합니다.

        Args:
            query: 검색할 용어 또는 설명
            top_k: 반환할 최대 결과 수
            glossary_ids: 검색 대상 용어집 id 목록. 생략하면 연결된 전체 검색.

        Returns:
            str: JSON 형식의 검색 결과
        """
        try:
            # 여러 glossary_id가 있으면 각각 검색 후 병합
            all_results = []

            # LLM 이 glossary_ids 로 검색 대상을 좁힐 수 있음. 연결된 용어집과
            # 교집합; 비거나 불일치면 연결된 전체로 fallback. 생략 시 전체.
            effective_ids = self.glossary_ids
            if self.glossary_ids and glossary_ids:
                sel = [g for g in glossary_ids if g in set(self.glossary_ids)]
                effective_ids = sel or self.glossary_ids

            if effective_ids:
                for gid in effective_ids:
                    results = await self.service.search(
                        query=query,
                        glossary_id=gid,
                        top_k=top_k,
                    )
                    all_results.extend(results)

                # 점수순 정렬 후 top_k 제한
                all_results.sort(key=lambda x: x.score or 0, reverse=True)
                all_results = all_results[:top_k]
            else:
                # 전체 검색
                all_results = await self.service.search(
                    query=query,
                    glossary_id=None,
                    top_k=top_k,
                )

            if not all_results:
                output = GlossaryLookupOutput(
                    found=False,
                    results=[],
                    message=f"'{query}'에 대한 용어를 찾을 수 없습니다.",
                )
                return output.model_dump_json()

            # 결과 변환
            formatted_results = []
            for r in all_results:
                formatted_results.append(
                    {
                        "term": r.term,
                        "synonyms": r.synonyms if r.synonyms else [],
                        "description": r.description,
                        "example": r.example,
                        "category": r.category,
                        "score": r.score,
                    }
                )

            output = GlossaryLookupOutput(
                found=True,
                results=formatted_results,
                message=f"'{query}'에 대해 {len(formatted_results)}개의 용어를 찾았습니다.",
            )
            return output.model_dump_json()

        except ValueError as e:
            # 검색 엔진 미설정
            log.warning(f"Glossary search failed: {e}")
            output = GlossaryLookupOutput(
                found=False,
                results=[],
                message="용어집 검색 엔진이 설정되지 않았습니다.",
            )
            return output.model_dump_json()
        except Exception as e:
            log.error(f"Glossary search error: {e}")
            output = GlossaryLookupOutput(
                found=False,
                results=[],
                message=f"용어 검색 중 오류가 발생했습니다: {str(e)}",
            )
            return output.model_dump_json()

    def get_tools(self) -> List[StructuredTool]:
        """
        LangChain 도구 목록 반환.

        Returns:
            List[StructuredTool]: 용어집 관련 도구 목록
        """
        base_desc = """용어집에서 용어를 검색합니다.

중요: 답을 안다고 생각해도 건너뛰지 말고, 사용자 질문의 핵심 용어·약어·도메인 단어는 답변 전에 먼저 이 도구로 조회하세요.

사용 시점:
- 사용자 질문에 모르는 약어, 전문 용어, 업무 용어가 있을 때
- 용어의 정확한 의미나 정의가 필요할 때
- 동의어나 유사 표현을 알고 싶을 때

반환값:
- term: 용어 이름
- synonyms: 동의어 목록
- description: 용어 설명/정의
- example: 사용 예시
- category: 분류 (선택)

참고: 검색 결과가 없으면 해당 용어가 용어집에 등록되지 않은 것입니다."""

        description = self._description if self._description else base_desc

        # When specific glossaries are connected, expose a glossary_ids selector
        # (Literal enum) so the LLM can scope the lookup; omit = search all.
        if self.glossary_ids:
            args_schema = create_model(
                "GlossaryLookupInputSelectable",
                __base__=GlossaryLookupInput,
                glossary_ids=(
                    Optional[List[Literal[tuple(self.glossary_ids)]]],
                    Field(
                        default=None,
                        description=(
                            "검색할 용어집 id 목록. 생략하면 연결된 전체 용어집을 "
                            "검색합니다."
                        ),
                    ),
                ),
            )
        else:
            args_schema = GlossaryLookupInput

        lookup_tool = StructuredTool.from_function(
            coroutine=self.lookup_term,
            name="lookup_glossary_term",
            description=description,
            args_schema=args_schema,
        )

        return [lookup_tool]


def create_glossary_lookup_tool(
    app: FastAPI,
    glossary_ids: Optional[List[str]] = None,
) -> StructuredTool:
    """
    용어집 검색 도구를 생성합니다.

    단일 도구만 필요한 경우 이 함수를 사용하세요.

    Args:
        app: FastAPI 앱 인스턴스
        glossary_ids: 검색을 제한할 용어집 ID 목록 (None이면 전체 검색)

    Returns:
        StructuredTool: LangChain 도구

    Example:
        >>> from extension_modules.glossary.tools import create_glossary_lookup_tool
        >>> tool = create_glossary_lookup_tool(request.app)
        >>> result = await tool.ainvoke({"query": "RAG", "top_k": 3})
    """
    tools_instance = GlossaryTools(app, glossary_ids, description=None)
    return tools_instance.get_tools()[0]
