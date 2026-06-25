"""drive_select_files 도구 — 스키마/그레이스풀 fallback."""

from __future__ import annotations

import pytest
from extension_modules.agent.drive_select_files_tool import (
    DriveSelectFilesInput,
    create_drive_select_files_tool,
)
from pydantic import ValidationError


def test_tool_name_and_schema():
    tool = create_drive_select_files_tool()
    assert tool.name == "drive_select_files"
    assert tool.args_schema is DriveSelectFilesInput


def test_schema_requires_two_candidates():
    with pytest.raises(ValidationError):
        DriveSelectFilesInput(
            candidates=[{"file_id": "a", "name": "A", "mime_type": "x"}]
        )


def test_schema_accepts_optional_metadata():
    m = DriveSelectFilesInput(
        candidates=[
            {"file_id": "a", "name": "A", "mime_type": "x", "location": "my_drive"},
            {"file_id": "b", "name": "B", "mime_type": "y"},
        ],
        purpose="메일 작성",
    )
    assert m.candidates[0].location == "my_drive"
    assert m.candidates[1].owner is None


async def test_body_returns_graceful_fallback_not_raise():
    tool = create_drive_select_files_tool()
    result = await tool.coroutine(
        candidates=[
            {"file_id": "a", "name": "A", "mime_type": "x"},
            {"file_id": "b", "name": "B", "mime_type": "y"},
        ]
    )
    assert isinstance(result, str)
    assert "선택" in result
