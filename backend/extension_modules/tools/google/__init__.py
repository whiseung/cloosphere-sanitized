"""Google Workspace 채팅 통합 툴 패키지.

LLM 이 Gmail / Google Calendar 와 상호작용하기 위한 LangChain @tool 모음을
export.  ``make_google_tools(user_id, enabled, conversation_id=None)`` 가 단일
entry — 호출자는 5축 AND 게이트 (admin enable + group permission + agent
capability + per-conversation toggle + OAuth token) 를 사전 평가한 결과 중
활성화된 feature set 만 enabled 인자로 전달한다.

``make_document_tools`` 와 시그니처 정렬: request 인자 없음.  admin enable
flag 검증은 caller 책임.  factory 는 단순히 tool 인스턴스 빌드 + 반환.

``conversation_id`` 는 per-turn write quota (T-B21) 정확도 + 측정 hook (T-X03)
의 conversation tagging 에 사용.  None 이면 user 단위 quota 로 fallback.

미래 ToolConnection (MCP / OpenAPI) swap 위치는 `inprocess/` 디렉토리 옆에
provider 디렉토리 추가하는 형태로 확장 (예: `tool_connection/`).
"""

from typing import Optional

from extension_modules.tools.google.inprocess import (
    make_calendar_tools,
    make_drive_tools,
    make_gmail_tools,
)
from langchain_core.tools import StructuredTool

__all__ = [
    "make_google_tools",
    "make_gmail_tools",
    "make_calendar_tools",
    "make_drive_tools",
]


def make_google_tools(
    user_id: str,
    enabled: set[str],
    conversation_id: Optional[str] = None,
    *,
    extraction_config: Optional[dict] = None,
) -> list[StructuredTool]:
    """user_id 바인딩 + enabled feature 별 Google 툴 list 반환.

    Args:
        user_id: 도구 호출의 주체 사용자 (감사 + OAuth lookup 용).
        enabled: 활성화된 feature 이름 집합.  지원: ``{"gmail", "calendar", "drive"}``.
            호출자가 5축 게이트를 통과시킨 항목만 포함.
        conversation_id: per-turn write quota + 측정 hook 의 scope.  None →
            user 단위 quota.
        extraction_config: caller(unified_agent)가 ``request.app.state.config`` 에서
            resolve 한 RAG 추출 설정 평문 dict.  Drive 바이너리·Gmail 첨부 본문
            추출에 사용.  None → 추출 비활성(메타데이터 fallback).  [P2] builder
            에 request 객체를 넘기지 않기 위한 평문 전달.

    Returns:
        LangChain ``StructuredTool`` list.  enabled 가 빈 set 이면 빈 list.
    """
    tools: list[StructuredTool] = []
    if "gmail" in enabled:
        tools.extend(
            make_gmail_tools(
                user_id,
                conversation_id=conversation_id,
                extraction_config=extraction_config,
            )
        )
    if "calendar" in enabled:
        tools.extend(make_calendar_tools(user_id, conversation_id=conversation_id))
    if "drive" in enabled:
        tools.extend(
            make_drive_tools(
                user_id,
                conversation_id=conversation_id,
                extraction_config=extraction_config,
            )
        )
    return tools
