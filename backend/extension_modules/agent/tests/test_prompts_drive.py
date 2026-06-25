"""Drive 프롬프트 hint / cap-guide 문자열 존재 검증.

prompts.py 의 system / final-answer 프롬프트가 drive capability 를 인식하고
drive_search / drive_get_content / drive_create_doc(HITL) 가이드를 노출하는지
+ unavailable 시 폴더 이모지 가이드를 노출하는지 확인.
"""

from __future__ import annotations

from extension_modules.agent.prompts import (
    get_unified_final_answer_prompt,
    get_unified_system_prompt,
)


def test_system_prompt_includes_drive_hint_when_active():
    prompt = get_unified_system_prompt(active_capabilities=["drive"])
    assert "drive_search" in prompt
    assert "drive_get_content" in prompt
    assert "drive_create_doc" in prompt
    assert "HITL" in prompt


def test_system_prompt_drive_unavailable_hint():
    prompt = get_unified_system_prompt(
        active_capabilities=[], unavailable_capabilities=["drive"]
    )
    assert "Google Drive" in prompt
    assert "📁" in prompt


def test_final_answer_prompt_drive_unavailable_section():
    # get_unified_final_answer_prompt 는 [SystemMessage, HumanMessage, ...]
    # 메시지 리스트를 반환한다. unavailable 섹션은 SystemMessage.content 안에
    # 렌더되므로 첫 메시지 content 에서 문자열을 확인한다.
    messages = get_unified_final_answer_prompt(unavailable_capabilities=["drive"])
    system_content = messages[0].content
    assert "Google Drive" in system_content
    assert "📁" in system_content


def test_system_prompt_drive_hint_mentions_fulltext():
    # T3 — 제목+내용(fullText) 병행 검색 안내가 hint 에 포함.
    prompt = get_unified_system_prompt(active_capabilities=["drive"])
    assert "fullText" in prompt
