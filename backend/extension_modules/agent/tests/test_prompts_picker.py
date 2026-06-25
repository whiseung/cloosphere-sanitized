"""picker carve-out 이 drive_hint + gws_workflow_hint 양쪽에 들어갔는지."""

from __future__ import annotations

from extension_modules.agent.prompts import get_unified_system_prompt


def test_drive_active_mentions_picker_in_both_hints():
    prompt = get_unified_system_prompt(active_capabilities=["drive", "gmail"])
    assert prompt.count("drive_select_files") >= 2  # drive_hint + gws_workflow_hint
    assert "[file_id:" in prompt  # 추출 규약


def test_no_drive_no_picker_mention():
    prompt = get_unified_system_prompt(active_capabilities=["dbsphere"])
    assert "drive_select_files" not in prompt
