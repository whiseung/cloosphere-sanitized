"""Gmail compose-intent 프롬프트 지시 검증.

라이브 회귀(H_LLM): 사용자가 "메일 템플릿 생성/메일 작성/공지 발송"을 요청할 때
모델이 gmail_send(HITL 카드)를 호출하지 않고 본문을 평문으로만 써버려 "메일
보내기 창"이 들쭉날쭉 뜨던 문제.  프롬프트가 compose/send 의도에서 gmail_send
호출을 명시적으로 강제하는지 가드.
"""

from __future__ import annotations

from extension_modules.agent.prompts import get_unified_system_prompt


def test_gmail_prompt_mandates_send_tool_for_compose():
    prompt = get_unified_system_prompt(active_capabilities=["gmail"])
    assert "gmail_send" in prompt
    # 핵심 지시: 본문을 평문으로만 쓰지 말고 도구를 호출하라.
    assert "Do NOT just write the subject/body as plain text" in prompt


def test_gmail_prompt_template_word_still_calls_send():
    # "템플릿/초안" 이라는 단어가 있어도 발송 의도면 gmail_send.
    prompt = get_unified_system_prompt(active_capabilities=["gmail"])
    assert "template" in prompt.lower()
