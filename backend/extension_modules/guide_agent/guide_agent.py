"""
Guide Q&A Agent

가이드 문서를 기반으로 사용자 질문에 답변하는 ReAct 에이전트.
도구를 사용하여 가이드 카테고리 탐색 → 섹션 조회 → 답변 생성.
"""

import logging
from typing import Any, Dict, List

from extension_modules.guide_agent.tools import create_guide_tools
from extension_modules.react.react_base import AgentStateBase, ReactAgentBase
from fastapi import Request
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

GUIDE_QA_SYSTEM_PROMPT = """당신은 Cloosphere 플랫폼의 사용자 도움말 어시스턴트입니다.
사용자가 Cloosphere 기능에 대해 질문하면 가이드 문서를 검색해 정확하게 답변합니다.

## 도구 사용 우선순위

1. **`search_guides`** — 사용자 질문이 들어오면 가장 먼저 호출. BM25 키워드 검색(한글 bigram + 영문 word) 으로 관련 청크 top_k=8 을 찾습니다.
2. **`get_guide_section`** — 위 검색에서 부족할 때, 또는 사용자가 특정 카테고리(`category` ID)를 명시할 때 해당 카테고리 전문을 조회.
3. **`list_guide_categories`** — 어떤 카테고리가 있는지 확인이 필요할 때만 호출.

## 답변 규칙

1. **반드시 가이드 도구가 반환한 내용을 근거로** 답변하세요. 도구 결과 외 정보는 추측하지 마세요.
2. 답변은 사용자가 사용한 언어(한국어/영어)로 일치시키세요.
3. 답변 끝에 **출처를 명시**하세요. 예: `> 출처: [chat/overview] 대화 시작하기`
   - **카테고리 단위로 중복 제거**: 같은 카테고리 ID 가 여러 청크에서 매칭돼도 출처에는 1회만 표기.
   - 실제로 답변 본문 작성에 사용한 카테고리만 출처에 기재 (검색만 되고 인용 안 한 카테고리는 제외).
4. 메뉴 경로가 있으면 포함하세요 (예: "관리자 > 설정 > 연결").
5. 단계별 설명은 번호 매기기를 사용하세요.
6. **검색 결과가 완전히 0건일 때만** "해당 내용은 현재 가이드에 포함되어 있지 않습니다." 라고 답하세요. 그 외에는 검색된 내용으로 본문을 구성하고 끝내세요 — 부족한 부분에 대한 변명을 덧붙이지 마세요.
7. 같은 도구를 동일한 인자로 반복 호출하지 마세요. 첫 검색이 부족하면 키워드를 바꿔 1~2회 추가 시도 후 6번 규칙대로 처리하세요.
8. **메타 코멘트 금지** — 다음과 같은 표현은 어떤 경우에도 답변에 포함하지 마세요:
   - "검색 결과에 따르면", "가이드 검색 결과에 따르면", "도구가 반환한 내용입니다"
   - "현재 가이드에서는 ~ 자세한 본문은 확인되지 않습니다"
   - "~ 직접 조회할 수 없어", "~ 카테고리를 조회할 수 없어"
   - "권한이 없어서", "접근 권한이 없어서"
   - "다만", "추가로 ~ 안내도 있습니다" 같이 도구 호출 결과를 메타적으로 정리하는 어투
   사용자가 알아야 하는 건 "기능이 어떻게 동작하는가" 뿐입니다. 모르는 부분은 그냥 답변에서 빼고 끝내세요.
9. 답변 도입부에 "가이드 검색 결과에 따르면", "다음과 같습니다" 같은 보일러플레이트를 쓰지 말고 **첫 문장부터 기능 설명**으로 시작하세요.
10. 답변 본문이 사실상 정보 0건(예: "설정 방법이나 메뉴 경로는 확인되지 않음" 같은 말만 남는 경우)이면 6번 규칙대로 처리하고, 절대 "확인되지 않습니다" 형태의 면피 문장 + 출처 만 적힌 답변을 만들지 마세요.
"""


class GuideQAState(AgentStateBase):
    """Guide Q&A 에이전트 상태."""

    pass  # AgentStateBase의 messages만 사용


class GuideQAAgent(ReactAgentBase):
    """가이드 문서 기반 Q&A ReAct 에이전트."""

    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
    ):
        super().__init__(api_config, base_url, api_key, metadata)
        self.request = request

    def run(self, question: str) -> str:
        """동기 실행 (사용하지 않음)."""
        raise NotImplementedError("Use run_chat() instead")

    async def run_chat(
        self,
        messages: List[dict],
        model_id: str,
    ) -> Dict[str, Any]:
        """멀티턴 Q&A 채팅 실행."""
        from extension_modules.utils.llm import create_llm_from_app

        # 1. LLM 생성
        llm = create_llm_from_app(
            self.request.app,
            model_id,
            temperature=0.3,
            max_tokens=4096,
        )

        # 2. 도구 생성 (role 컨텍스트 주입)
        user = self.metadata.get("user") or {}
        role = (
            user.get("role", "user")
            if isinstance(user, dict)
            else getattr(user, "role", "user")
        )
        tools = create_guide_tools(role=role)

        # 3. ReAct 에이전트 생성
        agent = create_agent(
            llm,
            tools,
            system_prompt=GUIDE_QA_SYSTEM_PROMPT,
            state_schema=GuideQAState,
        )

        # 4. 실행
        try:
            result = await agent.ainvoke({"messages": messages})
            # 마지막 AI 메시지 추출
            ai_messages = [
                m
                for m in result.get("messages", [])
                if isinstance(m, AIMessage) and m.content and not m.tool_calls
            ]
            if ai_messages:
                content = ai_messages[-1].content
                # Gemini/Vertex AI는 content를 list로 반환할 수 있음
                if isinstance(content, list):
                    content = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                assistant_message = content
            else:
                assistant_message = "답변을 생성할 수 없습니다."
        except Exception as e:
            log.error(f"Guide Q&A agent error: {e}", exc_info=True)
            assistant_message = f"죄송합니다, 답변 중 오류가 발생했습니다: {e}"

        return {"assistant_message": assistant_message}
