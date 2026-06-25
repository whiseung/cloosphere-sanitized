"""make_document_tools 통합 테스트."""

from extension_modules.tools.document import make_document_tools
from langchain_core.tools import StructuredTool


def test_returns_three_tools():
    tools = make_document_tools(user_id="u-1")
    assert len(tools) == 3
    names = {t.name for t in tools}
    assert names == {"create_pptx", "create_docx", "create_xlsx"}


def test_all_are_structured_tools():
    tools = make_document_tools(user_id="u-1")
    for t in tools:
        assert isinstance(t, StructuredTool)
        assert t.description and len(t.description) > 20
