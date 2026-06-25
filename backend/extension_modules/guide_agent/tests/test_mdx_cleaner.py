"""mdx_cleaner.clean_mdx 단위 테스트."""

from __future__ import annotations

import pytest
from extension_modules.guide_agent.mdx_cleaner import (
    UNKNOWN_TAG_THRESHOLD,
    CleanResult,
    clean_mdx,
)


def _clean(mdx: str, *, strict: bool = True) -> CleanResult:
    return clean_mdx(mdx, source="test.mdx", strict=strict)


def test_extracts_frontmatter_title_and_description():
    result = _clean(
        '---\ntitle: "첫 대화하기"\ndescription: "AI 모델 선택 방법"\n---\n\n본문',
    )
    assert result.title == "첫 대화하기"
    assert result.description == "AI 모델 선택 방법"
    assert "본문" in result.content


def test_steps_step_converts_to_h3_headings():
    mdx = """---
title: "T"
---

<Steps>
  <Step title="새 채팅 열기">
    사이드바 클릭.
  </Step>
  <Step title="모델 선택">
    드롭다운 사용.
  </Step>
</Steps>
"""
    out = _clean(mdx).content
    assert "### 새 채팅 열기" in out
    assert "### 모델 선택" in out
    assert "사이드바 클릭" in out
    assert "<Step" not in out and "</Step>" not in out


def test_callouts_become_quoted_lines():
    mdx = "<Tip>유용한 팁</Tip>\n<Note>주의사항</Note>\n<Warning>경고!</Warning>\n<Info>정보</Info>\n<Danger>위험!</Danger>"
    out = _clean(mdx).content
    assert "> Tip: 유용한 팁" in out
    assert "> Note: 주의사항" in out
    assert "> Warning: 경고!" in out
    assert "> Info: 정보" in out
    assert "> Danger: 위험!" in out


def test_tabs_tab_becomes_h3_sections():
    mdx = """<Tabs>
  <Tab title="Python">
    pip install foo
  </Tab>
  <Tab title="Node">
    npm install foo
  </Tab>
</Tabs>"""
    out = _clean(mdx).content
    assert "### Python" in out
    assert "### Node" in out
    assert "pip install foo" in out


def test_accordion_with_title():
    mdx = """<AccordionGroup>
  <Accordion title="자주 묻는 질문">
    답변 내용
  </Accordion>
</AccordionGroup>"""
    out = _clean(mdx).content
    assert "### 자주 묻는 질문" in out
    assert "답변 내용" in out


def test_card_with_title_and_href():
    mdx = '<Card title="시작하기" href="/getting-started">설명 텍스트</Card>'
    out = _clean(mdx).content
    assert "**시작하기**" in out
    assert "설명 텍스트" in out
    assert "참조: /getting-started" in out


def test_update_with_label():
    mdx = '<Update label="2026-04 · 1.0.1 릴리즈" tags={["릴리즈"]}>변경사항 본문</Update>'
    out = _clean(mdx).content
    assert "### 2026-04 · 1.0.1 릴리즈" in out
    assert "변경사항 본문" in out


def test_code_fences_preserve_jsx_like_text():
    mdx = """텍스트.

```bash
TEAMS_BOT_APP_ID=<Azure Bot Client ID>
TEAMS_BOT_APP_PASSWORD=<Client Secret>
```

다음 본문."""
    out = _clean(mdx).content
    assert "<Azure Bot Client ID>" in out
    assert "<Client Secret>" in out
    assert "TEAMS_BOT_APP_ID" in out


def test_columns_strips_wrapper_and_keeps_inner_cards():
    mdx = """<Columns cols={2}>
  <Card title="A">설명1</Card>
  <Card title="B">설명2</Card>
</Columns>"""
    out = _clean(mdx).content
    assert "**A**" in out and "설명1" in out
    assert "**B**" in out and "설명2" in out


def test_html_comments_and_imports_removed():
    mdx = """import foo from 'bar';

<!-- 주석 내용 -->

본문 텍스트
"""
    out = _clean(mdx).content
    assert "import foo" not in out
    assert "주석 내용" not in out
    assert "본문 텍스트" in out


def test_self_closing_frame_dropped():
    mdx = "<Frame />\n본문"
    out = _clean(mdx).content
    assert "<Frame" not in out
    assert "본문" in out


def test_unknown_tag_below_threshold_logs_but_passes():
    mdx = "<UnknownTag>내용</UnknownTag>"
    result = _clean(mdx)
    assert "내용" in result.content
    assert "UnknownTag" in result.unknown_tags


def test_unknown_tag_above_threshold_raises_in_strict_mode():
    mdx = "\n".join(f"<Bad{i}>x</Bad{i}>" for i in range(UNKNOWN_TAG_THRESHOLD + 2))
    with pytest.raises(ValueError, match="exceeds threshold"):
        _clean(mdx, strict=True)


def test_unknown_tag_above_threshold_passes_when_non_strict():
    mdx = "\n".join(f"<Bad{i}>x</Bad{i}>" for i in range(UNKNOWN_TAG_THRESHOLD + 2))
    result = _clean(mdx, strict=False)
    assert len(result.unknown_tags) > UNKNOWN_TAG_THRESHOLD


def test_nested_components_innermost_first():
    mdx = """<Steps>
  <Step title="A">
    <Tip>중첩 팁</Tip>
    본문
  </Step>
</Steps>"""
    out = _clean(mdx).content
    assert "### A" in out
    assert "> Tip: 중첩 팁" in out
    assert "본문" in out


def test_br_hr_become_newlines():
    mdx = "한줄<br/>다음줄<br>또다음<hr />구분"
    out = _clean(mdx).content
    assert "한줄" in out
    assert "다음줄" in out
    assert "<br" not in out and "<hr" not in out
