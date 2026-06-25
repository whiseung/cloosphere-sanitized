"""Heading 기반 청크 생성 (Q3).

mdx_cleaner.clean_mdx 결과 plaintext 를 H2 단위로 분할한다.
H2 청크가 MAX_TOKENS 초과 시 H3 로 재분할, 그래도 초과 시 token-window 분할.

각 청크는 LLM 답변 시 인용에 사용할 heading_path 메타데이터를 포함한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

import tiktoken

log = logging.getLogger(__name__)

MAX_TOKENS = 1500
HARD_MAX_TOKENS = 1800
WINDOW_OVERLAP_TOKENS = 100
ENCODING_NAME = "cl100k_base"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)


@dataclass
class Chunk:
    category: str
    lang: str
    audience: str
    title: str
    heading_path: str
    content: str
    token_count: int
    file_path: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _get_encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING_NAME)


def _count_tokens(text: str, enc: tiktoken.Encoding | None = None) -> int:
    enc = enc or _get_encoder()
    return len(enc.encode(text, disallowed_special=()))


def _split_by_window(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
    enc: tiktoken.Encoding,
) -> list[str]:
    """긴 단일 섹션을 토큰 윈도우로 분할 (마지막 수단)."""
    tokens = enc.encode(text, disallowed_special=())
    out: list[str] = []
    step = max_tokens - overlap_tokens
    if step <= 0:
        step = max_tokens
    for start in range(0, len(tokens), step):
        chunk_tokens = tokens[start : start + max_tokens]
        if not chunk_tokens:
            break
        out.append(enc.decode(chunk_tokens))
        if start + max_tokens >= len(tokens):
            break
    return out


def _is_in_code_fence(text: str, pos: int) -> bool:
    """text[pos] 가 코드 펜스 안에 있는지 — 헤딩 분할 시 코드 내 ## 무시."""
    fences_before = sum(1 for m in _CODE_FENCE_RE.finditer(text[:pos]))
    return fences_before % 2 == 1


def _find_headings(text: str, levels: Iterable[int]) -> list[tuple[int, int, str]]:
    """주어진 헤딩 레벨에 해당하는 (start, level, title) 리스트.

    코드 펜스 내 # 라인은 제외.
    """
    levels_set = set(levels)
    out: list[tuple[int, int, str]] = []
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        if level not in levels_set:
            continue
        if _is_in_code_fence(text, m.start()):
            continue
        out.append((m.start(), level, m.group(2).strip()))
    return out


def _slice_sections(
    text: str, headings: list[tuple[int, int, str]]
) -> list[tuple[str, str]]:
    """heading 위치 기준으로 (heading_title, body) 섹션 리스트 생성.

    첫 heading 앞 prefix 가 있으면 ("", prefix) 로 포함.
    body 는 다음 heading 직전까지 (자체 heading line 포함).
    """
    sections: list[tuple[str, str]] = []
    if not headings:
        return [("", text)] if text.strip() else []

    first_start = headings[0][0]
    if first_start > 0:
        prefix = text[:first_start]
        if prefix.strip():
            sections.append(("", prefix))

    for i, (start, _, title) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        body = text[start:end]
        sections.append((title, body))
    return sections


def chunk_document(
    *,
    content: str,
    title: str,
    category: str,
    lang: str,
    audience: str,
    file_path: str = "",
    max_tokens: int = MAX_TOKENS,
    hard_max_tokens: int = HARD_MAX_TOKENS,
) -> list[Chunk]:
    """단일 페이지를 heading 기반으로 청크화.

    Args:
        content: clean_mdx 결과 평문
        title: frontmatter title (heading_path prefix 로 사용)
        category: canonical id (예: 'admin/users')
        lang: 'ko' | 'en'
        audience: 'admin' | 'user'
        file_path: 디스크 상의 .mdx 경로 (메타로 보존)
        max_tokens: H2 분할 임계
        hard_max_tokens: H2/H3 도 초과 시 window 분할 트리거

    Returns:
        [Chunk, ...] — 본문 비어있으면 빈 리스트
    """
    enc = _get_encoder()
    body = content.strip()
    if not body:
        return []

    h2_headings = _find_headings(body, levels={2})
    h2_sections = _slice_sections(body, h2_headings)

    chunks: list[Chunk] = []
    for h2_title, h2_body in h2_sections:
        h2_token_count = _count_tokens(h2_body, enc)
        heading_path_h2 = f"[{title}]" + (f" {h2_title}" if h2_title else "")
        if h2_token_count <= max_tokens:
            chunks.append(
                Chunk(
                    category=category,
                    lang=lang,
                    audience=audience,
                    title=title,
                    heading_path=heading_path_h2,
                    content=h2_body.strip(),
                    token_count=h2_token_count,
                    file_path=file_path,
                )
            )
            continue

        # H3 재분할
        h3_headings = _find_headings(h2_body, levels={3})
        if not h3_headings:
            chunks.extend(
                _window_chunks(
                    h2_body,
                    title=title,
                    category=category,
                    lang=lang,
                    audience=audience,
                    file_path=file_path,
                    heading_path=heading_path_h2,
                    max_tokens=max_tokens,
                    enc=enc,
                )
            )
            continue

        h3_sections = _slice_sections(h2_body, h3_headings)
        for h3_title, h3_body in h3_sections:
            h3_path = heading_path_h2 + (f" > {h3_title}" if h3_title else "")
            h3_token_count = _count_tokens(h3_body, enc)
            if h3_token_count <= hard_max_tokens:
                chunks.append(
                    Chunk(
                        category=category,
                        lang=lang,
                        audience=audience,
                        title=title,
                        heading_path=h3_path,
                        content=h3_body.strip(),
                        token_count=h3_token_count,
                        file_path=file_path,
                    )
                )
            else:
                chunks.extend(
                    _window_chunks(
                        h3_body,
                        title=title,
                        category=category,
                        lang=lang,
                        audience=audience,
                        file_path=file_path,
                        heading_path=h3_path,
                        max_tokens=max_tokens,
                        enc=enc,
                    )
                )

    return [c for c in chunks if c.content.strip()]


def _window_chunks(
    body: str,
    *,
    title: str,
    category: str,
    lang: str,
    audience: str,
    file_path: str,
    heading_path: str,
    max_tokens: int,
    enc: tiktoken.Encoding,
) -> list[Chunk]:
    pieces = _split_by_window(
        body,
        max_tokens=max_tokens,
        overlap_tokens=WINDOW_OVERLAP_TOKENS,
        enc=enc,
    )
    log.info(
        "Window-split %s into %d pieces (max=%d, overlap=%d)",
        heading_path,
        len(pieces),
        max_tokens,
        WINDOW_OVERLAP_TOKENS,
    )
    return [
        Chunk(
            category=category,
            lang=lang,
            audience=audience,
            title=title,
            heading_path=heading_path,
            content=piece.strip(),
            token_count=_count_tokens(piece, enc),
            file_path=file_path,
            extra={"window_idx": i, "window_count": len(pieces)},
        )
        for i, piece in enumerate(pieces)
    ]
