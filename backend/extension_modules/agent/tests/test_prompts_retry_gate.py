"""Tool-call retry / sufficiency-gate hints gate on grounding capabilities.

The retry strategy and sufficiency gate only make sense when a grounding-data
tool (DB/KB/web/tool/KG/Google Workspace) is active. For an output-only model
(document_tools / code_interpreter) or a plain chat model they are noise, and the
"retry until the data covers it, else conclude no answer" framing pushes the LLM
to refuse general-knowledge questions. ``get_unified_system_prompt`` must omit
them unless a grounding capability is active.
"""

from __future__ import annotations

import pytest
from extension_modules.agent.prompts import get_unified_system_prompt

_MARKERS = ("Tool-call retry strategy", "Sufficiency gate")


@pytest.mark.parametrize(
    "caps",
    [
        [],
        ["document_tools"],
        ["code_interpreter"],
        ["document_tools", "code_interpreter"],
    ],
)
def test_retry_hint_omitted_without_grounding_capability(caps):
    p = get_unified_system_prompt(active_capabilities=caps)
    for marker in _MARKERS:
        assert marker not in p, caps


@pytest.mark.parametrize(
    "caps",
    [
        ["dbsphere"],
        ["kbsphere"],
        ["knowledge_graph"],
        ["web_search"],
        ["tool_connections"],
        ["glossary"],
        ["gmail"],
        # mixed: grounding + output-only → still present
        ["kbsphere", "document_tools"],
    ],
)
def test_retry_hint_present_with_grounding_capability(caps):
    p = get_unified_system_prompt(active_capabilities=caps)
    for marker in _MARKERS:
        assert marker in p, caps
