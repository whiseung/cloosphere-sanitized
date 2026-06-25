"""HITL (Human-in-the-Loop) 정책 빌더 + middleware subclass.

UnifiedAgent 가 들고 있는 도구 리스트를 받아 LangChain
HumanInTheLoopMiddleware 가 요구하는 `interrupt_on` dict 를 반환한다.

설계:
    - 디폴트는 "승인 필요" (보수적). 알 수 없는 도구는 일단 가로챈다.
    - read-only / safe 도구만 화이트리스트에서 자동승인.
    - tool connection 의 휴리스틱 (HTTP method / MCP readOnlyHint) 은 phase 5
      에서 이 모듈을 확장하여 도입한다 — 지금은 use_tool_server 통째로 승인.
    - run_sql 의 read/write split 은 phase 4 에서 도구 자체를 둘로 쪼갠 후
      정책에서 read 만 자동승인으로 옮긴다 — 지금은 통째로 승인.
    - ask_user 는 `respond` decision 만 허용 — upstream middleware 가 native
      로 지원하지 않아서 CloosphereHITLMiddleware 가 그 분기를 추가한다.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Union

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import ToolMessage

# Read-only / safe 도구 — 정확 이름 매칭. 이 목록에 없으면 "승인 필요".
_AUTO_APPROVE_EXACT = frozenset(
    {
        # 메타 / 프레임워크
        "extract_context_info",
        "evaluation_result",
        "submit_result",
        "get_recent_history",
        # KbSphere (모두 read)
        "knowledge_handler",
        "knowledge_search",
        "get_file_contents",
        "search_web",
        "load_web_page",
        # Glossary (read)
        "lookup_glossary_term",
        # DbSphere read 단계 도구 — run_sql_write 만 별도 승인
        "dbsphere_info",
        "get_table_details",
        "visualize_data",
        "run_sql_read",
        # Code interpreter 의 read 메타 도구 — code_interpreter 본체는 별도 (실행)
        "data_file_info",
        "get_file_details",
        # UI action read
        "read_form",
        "get_page_info",
        # Tool connection 메타 + read 경로 (write 만 use_tool_server_write 로 분리)
        "list_tool_servers",
        "use_tool_server_read",
        # Google Workspace read 도구 — write/마커 HITL 도구(gmail_send /
        # drive_create_doc / calendar_create_event)는 자체 confirmation marker 로
        # 통제하므로 여기서 제외.  read 는 ENABLE_HITL=true 에서도 자동 승인.
        "drive_search",
        "drive_get_content",
        "drive_get_contents",
        "gmail_search",
        "gmail_get",
        "gmail_get_batch",
        "calendar_list_events",
        "calendar_find_free_slots",
    }
)

# 특수 정책 — `respond` decision 만 허용. 사용자 응답이 ToolMessage 로 박혀야
# graph 가 자연스럽게 이어진다 (approve 면 NotImplementedError 가 raise 됨).
# - ask_user: 자유 텍스트/선택지 되묻기 (단일 질문)
# - ask_user_form: 여러 항목을 한 카드에 폼으로 묶어 한 번에 되묻기
# - drive_select_files: Drive 후보 중 넣을 파일 여러 개 선택
_RESPOND_ONLY = frozenset({"ask_user", "ask_user_form", "drive_select_files"})

# Prefix 매칭 — KG 도구 8종 모두 read-only (kg_cypher 만 위험, 별도 가드)
_AUTO_APPROVE_PREFIXES = ("kg_",)

# Prefix 자동승인이 아닌 예외 (KG 패밀리 중 위험한 것)
_PREFIX_EXCEPTIONS = frozenset(
    {
        "kg_cypher",  # 임의 cypher 실행
    }
)


def _is_auto_approve(tool_name: str) -> bool:
    if tool_name in _PREFIX_EXCEPTIONS:
        return False
    if tool_name in _AUTO_APPROVE_EXACT:
        return True
    return any(tool_name.startswith(p) for p in _AUTO_APPROVE_PREFIXES)


def build_interrupt_policy(
    tools: Iterable[Any],
) -> Dict[str, Union[bool, dict]]:
    """도구 리스트 → HumanInTheLoopMiddleware.interrupt_on dict.

    값 의미:
        - False: 자동승인 (가로채지 않음)
        - True : 모든 결정 허용 (approve / edit / reject / respond)
        - dict : 일부 결정만 허용 (예: {"allowed_decisions": ["approve", "reject"]})
    """
    policy: Dict[str, Union[bool, dict]] = {}
    for tool in tools:
        name = getattr(tool, "name", None)
        if not name:
            continue
        if name in _RESPOND_ONLY:
            policy[name] = {"allowed_decisions": ["respond"]}
        elif _is_auto_approve(name):
            policy[name] = False
        else:
            policy[name] = True
    return policy


def resolve_interrupt_policy(
    tools: Iterable[Any],
    *,
    enable_hitl: bool,
    picker_active: bool,
) -> Dict[str, Union[bool, dict]]:
    """3분기 정책 결정.

    - enable_hitl=True  → 전역 정책(build_interrupt_policy).  picker 는 _RESPOND_ONLY
      로 respond-only 가 되고 마커는 기존대로 interrupt(원 설계 의도, 회귀 보존).
    - enable_hitl=False & picker_active=True → **scoped**: drive_select_files 만 가로채고
      나머지(마커 포함)는 정책에 없어 자동승인 → 마커 카드 보존(C-1 회피).
    - 그 외 → 빈 정책(전부 자동승인).
    """
    if enable_hitl:
        return build_interrupt_policy(tools)
    # ENABLE_HITL=False 라도 RESPOND_ONLY 되묻기 도구(ask_user/drive_select_files)는
    # 승인 게이트가 아니라 "사용자 응답 수집" 용 interrupt 로만 동작한다. 등록돼 있는데
    # 정책에서 빠지면 가로채지 못해 도구 본체(NotImplementedError)까지 흘러가므로,
    # 도구가 존재하면 항상 respond-only 로 가로챈다.
    scoped: Dict[str, Union[bool, dict]] = {}
    if picker_active:
        scoped["drive_select_files"] = {"allowed_decisions": ["respond"]}
    for _name in ("ask_user", "ask_user_form"):
        if any(getattr(t, "name", None) == _name for t in tools):
            scoped[_name] = {"allowed_decisions": ["respond"]}
    return scoped


class CloosphereHITLMiddleware(HumanInTheLoopMiddleware):
    """upstream HumanInTheLoopMiddleware 에 `respond` decision 분기 추가.

    upstream 의 `_process_decision` 은 approve / edit / reject 만 처리하고,
    그 외 type (우리가 ask_user 용으로 쓰는 `respond`) 은 ValueError 로 raise
    한다. 이 subclass 는 `respond` 케이스를 추가해 사용자 답변을 ToolMessage
    (status=success) 로 박는다 — 도구 본체 (NotImplementedError) 는 실행되지
    않고, LLM 은 정상 도구 응답으로 보고 후속 답변을 이어간다.

    return value 규약 (upstream after_model 흐름 참조):
        - `(tool_call, tool_message)` → revised_tool_calls 에 tool_call 도 살리고
          artificial_tool_messages 에 tool_message 도 박는다. 같은 tool_call_id
          의 ToolMessage 가 이미 있으므로 ToolNode 는 그 호출을 skip 한다 —
          reject 와 동일 패턴.
    """

    def _process_decision(self, decision, tool_call, config):  # type: ignore[override]
        if decision.get("type") == "respond" and "respond" in config.get(
            "allowed_decisions", []
        ):
            user_message = decision.get("message") or ""
            tool_message = ToolMessage(
                content=user_message,
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
            )
            return tool_call, tool_message
        return super()._process_decision(decision, tool_call, config)
