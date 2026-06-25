"""ask_user 도구 — 정보 부족 / 의도 모호 시 사용자에게 되묻는 HITL 게이트.

LLM 이 이 도구를 호출하면 HumanInTheLoopMiddleware 가 가로채서 클라이언트에
질문(+ 선택지)을 보내고 그래프를 멈춘다. 사용자가 답하면 `respond` decision 으로
재개되며, **사용자 답변이 곧 ToolMessage 로 graph state 에 박힌다** —
도구 함수 본체는 절대 실행되지 않는다.

따라서 본체는 NotImplementedError 로 두어도 동작에 영향 없음.
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class AskUserInput(BaseModel):
    """ask_user 도구 입력 스키마."""

    question: str = Field(
        ...,
        description=(
            "사용자에게 보여줄 질문. 한 문장으로 명확하게. 사용자가 마지막으로 사용한 "
            "언어로 작성한다."
        ),
    )
    choices: Optional[List[str]] = Field(
        default=None,
        description=(
            "선택지 버튼 목록 — **가능하면 반드시 채워라** (2~5개 권장). 자유 "
            "입력보다 버튼 클릭이 사용자 부담이 훨씬 적다. 실행 가능한 옵션이 "
            "한 개라도 떠오르면 채운다.\n\n"
            "구성 규칙:\n"
            "1. 각 항목은 현재 등록된 리소스 (Knowledge Base / DbSphere / "
            "Knowledge Graph / Tool Connection / Glossary) 또는 가용한 도구로 "
            "실제 실행 가능한 옵션이어야 한다.\n"
            "2. 시스템 프롬프트의 리소스/도구 목록에 없는 자원은 넣지 않는다 "
            "(예: 등록된 DB 가 'sales_db' 하나뿐인데 '재무 DB' 같은 옵션 금지).\n"
            '3. 단순 카테고리 나열 ("매출 / 비용 / 재고") 대신 실제 처리 단위 '
            '("sales_db 의 어제 일자 매출 요약" 같은 식) 로 작성한다.\n'
            "4. 일부 옵션만 확실하면 그 옵션들로만 채워라 — 전부 빼버리지 말 것. "
            "정말 0개도 떠오르지 않을 때만 choices 를 비운다 (그땐 자유 입력 "
            "textarea 만 노출)."
        ),
    )


async def _ask_user_impl(question: str, choices: Optional[List[str]] = None) -> str:
    """절대 실행되지 않음 — HITL middleware 의 respond decision 이 가로채고
    사용자 응답을 ToolMessage 로 직접 박는다. 만약 어쩌다 호출되면(정책 누락
    같은 버그), graph 가 멈추지 않고 계속 진행하지 않도록 명시적으로 raise.
    """
    raise NotImplementedError(
        "ask_user must be intercepted by HumanInTheLoopMiddleware "
        "(allowed_decisions=['respond']). If you see this, the HITL policy "
        "is misconfigured for ask_user."
    )


def create_ask_user_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_ask_user_impl,
        name="ask_user",
        description=(
            "사용자에게 직접 되묻는 도구. 먼저 합리적 기본값으로 진행을 시도하고, "
            "이 도구는 마지막 수단으로만 사용한다. 다음 상황에서만 호출:\n"
            "- 질문에 핵심 정보 (대상, 기간, 범위 등) 가 빠져 추론으로도 채울 수 없을 때\n"
            "- 두 가지 이상 합리적 해석이 가능해 어느 쪽인지 확정해야 할 때\n"
            "- 위험한 작업 (삭제/외부 발송 등) 의 의도를 한 번 더 확인해야 할 때\n\n"
            "주의:\n"
            "- 한 번의 호출로 한 가지만 묻는다. 진행에 필요한 독립 항목이 2개 이상이고 "
            "한꺼번에 받는 게 자연스러우면 ask_user 대신 ask_user_form 을 쓴다 "
            "(답에 따라 다음 질문이 갈리는 분기형이면 ask_user 로 하나씩).\n"
            "- `choices` 의 각 항목은 반드시 등록된 리소스 (KB/DB/KG/Tool/Glossary) "
            "또는 가용한 도구로 실제 처리 가능한 옵션이어야 한다. 일반론이나 카테고리 "
            "나열은 금지 (예: 등록 DB 가 sales 뿐인데 '재무 데이터' 옵션 제시 금지). "
            "확신이 없으면 choices 를 비우고 자유 입력으로 받는다.\n"
            "- 일반 정보 검색/탐색은 ask_user 로 우회하지 말고 다른 도구로 직접 처리한다."
        ),
        args_schema=AskUserInput,
    )
