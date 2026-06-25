"""문서 생성 툴 패키지.

LLM이 PPT/Word/Excel 파일을 생성하기 위한 LangChain @tool 3종을 export한다.
UnifiedAgent.get_tools()에서 user_id를 바인딩한 팩토리로 사용.
"""

import logging

from extension_modules.tools.document.docx_tool import make_create_docx
from extension_modules.tools.document.pptx_tool import make_create_pptx
from extension_modules.tools.document.xlsx_tool import make_create_xlsx
from langchain_core.tools import StructuredTool

log = logging.getLogger(__name__)

__all__ = [
    "make_document_tools",
    "make_create_pptx",
    "make_create_presentation",
    "make_create_docx",
    "make_create_xlsx",
]


def make_document_tools(
    user_id: str,
    event_emitter=None,
    attached_files: list[str] | None = None,
) -> list[StructuredTool]:
    """user_id에 바인딩된 PPT/Word/Excel 생성 툴을 반환.

    PRESENTON_ENABLED 이면 PPT 경로는 Presenton(create_presentation)로 대체된다
    (내장 python-pptx create_pptx 대신). 둘을 동시에 노출하지 않아 LLM 혼동 방지.

    event_emitter: 주어지면 Presenton 경로가 생성 단계별 진행상황을 사용자에게 표시한다
    (Socket.IO). python-pptx 폴백은 sync 라 사용 안 함.
    attached_files: 채팅에 첨부된 파일 ID 리스트. Presenton 경로에서 .pptx 첨부를
    템플릿으로 on-the-fly 추출하는 데 사용 (use_attached_template=True 시).
    """
    try:
        from open_webui.config import PRESENTON_ENABLED

        presenton_on = bool(PRESENTON_ENABLED.value)
    except Exception as e:  # noqa: BLE001 — config 미존재 등 → 안전하게 비활성
        log.warning("PRESENTON_ENABLED 조회 실패, python-pptx 사용: %s", e)
        presenton_on = False

    if presenton_on:
        from extension_modules.tools.document.presenton_tool import (
            make_create_presentation,
        )

        ppt_tool = make_create_presentation(
            user_id,
            event_emitter=event_emitter,
            attached_files=attached_files or [],
        )
    else:
        ppt_tool = make_create_pptx(user_id)

    return [
        ppt_tool,
        make_create_docx(user_id),
        make_create_xlsx(user_id),
    ]
