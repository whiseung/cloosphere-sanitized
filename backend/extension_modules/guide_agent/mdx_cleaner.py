"""MDX → 평문 정제기 (Q1).

Mintlify MDX 콘텐츠를 LLM 검색용 평문으로 변환한다.
- 화이트리스트 16종 컴포넌트 평문화
- 코드 펜스(```...```) 내부는 보존
- frontmatter(title, description) 추출
- unknown JSX 태그 임계 초과 시 ValueError
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import yaml

log = logging.getLogger(__name__)

WHITELIST_TAGS = {
    "Steps",
    "Step",
    "Accordion",
    "AccordionGroup",
    "Card",
    "CardGroup",
    "Frame",
    "Note",
    "Tip",
    "Warning",
    "Info",
    "Danger",
    "Tabs",
    "Tab",
    "Columns",
    "Column",
    "Update",
}

UNKNOWN_TAG_THRESHOLD = 5


@dataclass
class CleanResult:
    title: str
    description: str
    content: str
    unknown_tags: list[str] = field(default_factory=list)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_IMPORT_RE = re.compile(r"^import\s+.*?$", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\{([^}]*)\}|\'([^\']*)\')')
_SELF_CLOSING_RE = re.compile(r"<([A-Z][a-zA-Z0-9]*)((?:\s+[^/>]*)?)\s*/>")
# Inner cannot contain another opening JSX tag — finds only innermost paired blocks.
_PAIRED_INNERMOST_RE = re.compile(
    r"<([A-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?)>"
    r"((?:(?!<[A-Z][a-zA-Z0-9]*).)*?)"
    r"</\1>",
    re.DOTALL,
)
_OPENER_RE = re.compile(r"<([A-Z][a-zA-Z0-9]*)(?:\s+[^>]*)?>")
_CLOSER_RE = re.compile(r"</([A-Z][a-zA-Z0-9]*)>")


def _extract_frontmatter(mdx: str) -> tuple[str, str, str]:
    m = _FRONTMATTER_RE.match(mdx)
    if not m:
        return "", "", mdx
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        log.warning("Failed to parse frontmatter")
        meta = {}
    title = str(meta.get("title", "")).strip().strip("\"'")
    description = str(meta.get("description", "")).strip().strip("\"'")
    return title, description, mdx[m.end() :]


def _split_code_fences(text: str) -> list[tuple[bool, str]]:
    segments: list[tuple[bool, str]] = []
    pos = 0
    for m in _CODE_FENCE_RE.finditer(text):
        if m.start() > pos:
            segments.append((False, text[pos : m.start()]))
        segments.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        segments.append((False, text[pos:]))
    return segments


def _parse_attrs(attrs_str: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attrs_str or ""):
        key = m.group(1)
        val = m.group(2) or m.group(3) or m.group(4) or ""
        result[key] = val.strip()
    return result


def _convert_component(tag: str, attrs: dict[str, str], inner: str) -> str:
    inner = inner.strip()
    if tag in {"Tip", "Note", "Warning", "Info", "Danger"}:
        return f"\n> {tag}: {inner}\n"
    if tag in {
        "Steps",
        "AccordionGroup",
        "Tabs",
        "Columns",
        "Column",
        "CardGroup",
        "Frame",
    }:
        return f"\n{inner}\n"
    if tag in {"Step", "Tab", "Accordion"}:
        title = attrs.get("title", "")
        return f"\n### {title}\n{inner}\n" if title else f"\n{inner}\n"
    if tag == "Card":
        title = attrs.get("title", "")
        href = attrs.get("href", "")
        ref = f" (참조: {href})" if href else ""
        return f"\n- **{title}**: {inner}{ref}\n" if title else f"\n{inner}\n"
    if tag == "Update":
        label = attrs.get("label", "")
        return f"\n### {label}\n{inner}\n" if label else f"\n{inner}\n"
    return inner


def _convert_self_closing(text: str, unknown: list[str]) -> str:
    def repl(m: re.Match) -> str:
        tag = m.group(1)
        if tag not in WHITELIST_TAGS:
            unknown.append(tag)
        return ""

    return _SELF_CLOSING_RE.sub(repl, text)


def _convert_paired(text: str, unknown: list[str]) -> str:
    """Innermost-first 반복 평문화. _PAIRED_INNERMOST_RE 가 nested 없는 매칭만 반환."""
    max_iterations = 50
    for _ in range(max_iterations):

        def _replace(m: re.Match) -> str:
            tag = m.group(1)
            attrs_str = m.group(2) or ""
            inner = m.group(3)
            if tag not in WHITELIST_TAGS:
                unknown.append(tag)
                return inner
            return _convert_component(tag, _parse_attrs(attrs_str), inner)

        new_text, n = _PAIRED_INNERMOST_RE.subn(_replace, text)
        if n == 0:
            return new_text
        text = new_text
    log.warning(
        "clean_mdx: paired-component conversion did not converge in %d iterations",
        max_iterations,
    )
    return text


def _strip_remaining_jsx(text: str, unknown: list[str]) -> str:
    def opener_repl(m: re.Match) -> str:
        tag = m.group(1)
        if tag not in WHITELIST_TAGS:
            unknown.append(tag)
        return ""

    text = _OPENER_RE.sub(opener_repl, text)
    text = _CLOSER_RE.sub("", text)
    text = re.sub(r"</?(br|hr)\s*/?>", "\n", text, flags=re.IGNORECASE)
    return text


def clean_mdx(
    mdx: str, *, source: str = "<unknown>", strict: bool = True
) -> CleanResult:
    """MDX → 평문 + frontmatter 추출.

    Args:
        mdx: 원본 MDX 문자열
        source: 로깅용 파일 경로
        strict: True 면 unknown 태그가 UNKNOWN_TAG_THRESHOLD 초과 시 ValueError raise

    Returns:
        CleanResult(title, description, content, unknown_tags)
    """
    title, description, body = _extract_frontmatter(mdx)
    body = _HTML_COMMENT_RE.sub("", body)
    body = _IMPORT_RE.sub("", body)

    unknown: list[str] = []
    segments = _split_code_fences(body)
    cleaned_segments: list[str] = []
    for is_code, segment in segments:
        if is_code:
            cleaned_segments.append(segment)
            continue
        segment = _convert_self_closing(segment, unknown)
        segment = _convert_paired(segment, unknown)
        segment = _strip_remaining_jsx(segment, unknown)
        cleaned_segments.append(segment)

    content = re.sub(r"\n{3,}", "\n\n", "".join(cleaned_segments)).strip()

    if unknown:
        unique = sorted(set(unknown))
        log.warning(
            "[%s] unknown JSX tags (%d total): %s", source, len(unknown), unique
        )
        if strict and len(unknown) > UNKNOWN_TAG_THRESHOLD:
            raise ValueError(
                f"{source}: unknown JSX tag count {len(unknown)} exceeds threshold "
                f"{UNKNOWN_TAG_THRESHOLD}: {unique}"
            )

    return CleanResult(
        title=title,
        description=description,
        content=content,
        unknown_tags=unknown,
    )
