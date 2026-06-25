"""drive_select_files 도구 — Drive 자료로 작성 전, 검색 후보 중 사용자가 넣을 파일을
여러 개 골라 확정하는 정확성/큐레이션 게이트 (HITL respond-only).

ask_user 패턴 — 본체는 미실행(미들웨어가 가로채 선택을 ToolMessage 로 박음). 단 가로채는
미들웨어가 없으면 raise 대신 graceful fallback 문자열 반환(fail-safe). 가로채기 결선은
unified_agent.py 의 scoped HITL policy.
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class DriveCandidate(BaseModel):
    """후보 1건. file_id/name 만 load-bearing, 나머지 표시용."""

    file_id: str = Field(..., description="Drive 파일 ID (drive_search 결과의 id).")
    name: str = Field(..., description="파일 이름.")
    mime_type: str = Field(..., description="MIME 타입.")
    modified_time: Optional[str] = Field(
        default=None, description="수정 시각(ISO8601)."
    )
    owner: Optional[str] = Field(
        default=None, description="소유자 표시명(공유 드라이브는 빈 값 가능)."
    )
    location: Optional[str] = Field(
        default=None,
        description="위치 enum: 'my_drive'|'shared_drive'|'shared_with_me'.",
    )


class DriveSelectFilesInput(BaseModel):
    """drive_select_files 입력."""

    candidates: List[DriveCandidate] = Field(
        ...,
        min_length=2,
        description=(
            "사용자가 고를 파일 후보(2개 이상). drive_search 결과에서 작성에 쓸 만한 후보를 "
            "추려 넣되 많으면 상위 8개 이내."
        ),
    )
    purpose: Optional[str] = Field(
        default=None, description="선택 목적(카드 헤더). 예: '메일에 넣을 파일'."
    )


async def _drive_select_files_impl(
    candidates: list, purpose: Optional[str] = None
) -> str:
    """미들웨어 미가로채 시 graceful fallback (raise 안 함)."""
    return (
        "파일 선택 UI를 표시할 수 없습니다. 잘못된 파일로 진행하지 말고, 사용자에게 "
        "후보 파일명을 보여주고 어떤 파일을 쓸지 직접 확인한 뒤 진행하세요."
    )


def create_drive_select_files_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_drive_select_files_impl,
        name="drive_select_files",
        description=(
            "Let the user pick WHICH Drive files to use BEFORE you read/compose. "
            "Call this when the user asks you to compose an email or document FROM "
            "Drive materials AND drive_search returned 2+ candidates. The user "
            "checks the files to include; their selection comes back as one or more "
            "`[file_id:<id>]` tokens — read ALL of them with drive_get_contents, then "
            "compose from only those. Do NOT read-and-synthesize all search results "
            "without this confirmation. Pass the search candidates (id/name/mime/"
            "location/modified/owner) as `candidates`."
        ),
        args_schema=DriveSelectFilesInput,
    )
