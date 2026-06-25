"""ask_user_form 도구 — 여러 항목을 한 카드에 폼으로 묶어 한 번에 되묻는 HITL 게이트.

`ask_user` 와 동일한 respond-only interrupt 메커니즘으로 동작한다. 차이는 단일 질문이
아니라 **서로 독립적인 여러 입력을 한 번에** 묻는다는 점 — 프론트가 한 카드에 폼으로
렌더하고, 사용자가 (필수) 항목을 전부 채워 제출하면 `{key: answer}` 형태의 JSON 이
respond message 로 들어온다. 이 JSON 이 곧 ToolMessage 로 graph state 에 박힌다 —
도구 함수 본체는 절대 실행되지 않는다 (`ask_user` 와 동일).

따라서 본체는 NotImplementedError 로 두어도 동작에 영향 없음.

ask_user vs ask_user_form 선택 기준:
    - 물어볼 게 한 가지면 → ask_user (모달 부담이 더 적다)
    - 진행에 필요한 독립 항목이 2개 이상이고 동시에 받는 게 자연스러우면 → ask_user_form
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class AskUserFormField(BaseModel):
    """폼의 항목 한 개."""

    key: str = Field(
        ...,
        description=(
            "응답 매핑 키. 영문 snake_case (예: 'database', 'period', 'format'). "
            "제출된 답변은 이 키로 묶인 JSON 으로 돌아온다."
        ),
    )
    question: str = Field(
        ...,
        description="이 항목의 질문/라벨. 사용자가 마지막으로 사용한 언어로 한 문장.",
    )
    type: str = Field(
        default="text",
        description=(
            "'choice' = 버튼 선택지, 'text' = 자유 입력. 기본값 'text'. "
            "선택 가능한 옵션이 명확하면 'choice' 로 둬서 사용자 부담을 줄여라."
        ),
    )
    choices: Optional[List[str]] = Field(
        default=None,
        description=(
            "type='choice' 일 때 버튼 옵션 목록 (2~5개 권장). 규칙은 ask_user 의 "
            "choices 와 동일 — 각 항목은 현재 등록된 리소스 (Knowledge Base / "
            "DbSphere / Knowledge Graph / Tool Connection / Glossary) 또는 가용한 "
            "도구로 실제 처리 가능한 옵션이어야 한다. 일반론/카테고리 나열 금지."
        ),
    )
    required: bool = Field(
        default=True,
        description="필수 여부. false 면 사용자가 비워둔 채로도 제출할 수 있다.",
    )
    allow_custom: bool = Field(
        default=True,
        description="type='choice' 에서 선택지 외 자유 입력도 허용할지. 기본 true.",
    )


class AskUserFormInput(BaseModel):
    """ask_user_form 도구 입력 스키마."""

    fields: List[AskUserFormField] = Field(
        ...,
        min_length=2,
        description=(
            "물어볼 항목들 (2개 이상). 한 카드에 폼으로 함께 표시된다. 서로 독립적이고 "
            "동시에 받는 게 자연스러운 항목만 묶어라 — 답에 따라 다음 질문이 달라지는 "
            "분기형이면 ask_user 로 하나씩 묻는다."
        ),
    )
    title: Optional[str] = Field(
        default=None,
        description="카드 헤더 제목 (예: '리포트 생성에 필요한 정보'). 없으면 기본 제목.",
    )
    intro: Optional[str] = Field(
        default=None,
        description="폼 상단 안내문 한두 문장. 왜 이 정보가 필요한지 짧게.",
    )


async def _ask_user_form_impl(
    fields: List[AskUserFormField],
    title: Optional[str] = None,
    intro: Optional[str] = None,
) -> str:
    """절대 실행되지 않음 — HITL middleware 의 respond decision 이 가로채고
    사용자 응답(JSON)을 ToolMessage 로 직접 박는다. 어쩌다 호출되면(정책 누락)
    graph 가 멈추지 않고 계속 진행하지 않도록 명시적으로 raise.
    """
    raise NotImplementedError(
        "ask_user_form must be intercepted by HumanInTheLoopMiddleware "
        "(allowed_decisions=['respond']). If you see this, the HITL policy "
        "is misconfigured for ask_user_form."
    )


def create_ask_user_form_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_ask_user_form_impl,
        name="ask_user_form",
        description=(
            "사용자에게 여러 항목을 한 번에 되묻는 폼 도구. 먼저 합리적 기본값으로 "
            "진행을 시도하고, 정보가 부족할 때만 사용한다. ask_user 와 달리 "
            "**서로 독립적인 입력 2개 이상을 한 카드에 모아** 한 번에 받는다.\n\n"
            "사용 기준:\n"
            "- 진행에 필요한 핵심 정보가 여러 개이고 (예: 대상 DB + 기간 + 출력형식) "
            "서로 독립적이라 한꺼번에 받는 게 자연스러울 때.\n"
            "- 답에 따라 다음 질문이 달라지는 분기형이면 쓰지 말고 ask_user 로 하나씩.\n"
            "- 물어볼 게 한 가지뿐이면 ask_user 를 쓴다.\n\n"
            "주의:\n"
            "- 각 field 의 key 는 영문 snake_case 로 고유하게. 답변은 {key: answer} "
            "JSON 으로 돌아온다.\n"
            "- choice 타입 항목의 choices 는 ask_user 규칙과 동일 — 등록된 리소스/도구로 "
            "실제 처리 가능한 옵션만. 확신 없으면 type='text' 로 자유 입력을 받는다.\n"
            "- 항목은 꼭 필요한 것만 (3~5개 이내 권장). 과한 폼은 사용자 부담이 크다."
        ),
        args_schema=AskUserFormInput,
    )
