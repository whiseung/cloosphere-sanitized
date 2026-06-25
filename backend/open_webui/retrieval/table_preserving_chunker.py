"""
테이블 보존 청킹 전처리/후처리.

청킹 전에 문서에서 테이블을 분리하고,
텍스트만 청킹한 뒤, 테이블을 별도 청크로 보존한다.
"""

import logging
import re

from langchain_core.documents import Document

log = logging.getLogger(__name__)

# HTML 테이블 패턴 (중첩 지원: 가장 바깥 <table> 매칭)
_HTML_TABLE_PATTERN = re.compile(
    r"<table\b[^>]*>.*?</table>",
    re.DOTALL | re.IGNORECASE,
)

# 마크다운 테이블 패턴: | 로 시작하는 연속 행 (구분선 |---| 포함)
_MD_TABLE_PATTERN = re.compile(
    r"(?:^[ \t]*\|.+\|[ \t]*$\n?){2,}",
    re.MULTILINE,
)


def _find_tables(text: str) -> list[tuple[int, int, str]]:
    """
    텍스트에서 테이블 위치를 찾는다.
    Returns: [(start, end, table_text), ...]
    """
    tables = []

    # HTML 테이블
    for m in _HTML_TABLE_PATTERN.finditer(text):
        tables.append((m.start(), m.end(), m.group()))

    # 마크다운 테이블 (HTML 테이블과 겹치지 않는 것만)
    for m in _MD_TABLE_PATTERN.finditer(text):
        # 이미 HTML 테이블에 포함된 범위인지 확인
        overlaps = any(s <= m.start() < e or s < m.end() <= e for s, e, _ in tables)
        if not overlaps:
            tables.append((m.start(), m.end(), m.group()))

    # 위치 순으로 정렬
    tables.sort(key=lambda x: x[0])
    return tables


def _get_context_prefix(text_before: str, max_chars: int = 100) -> str:
    """테이블 앞 텍스트에서 마지막 문장/제목을 추출하여 컨텍스트로 사용."""
    text_before = text_before.rstrip()
    if not text_before:
        return ""

    # 마지막 줄 또는 마지막 문장
    lines = text_before.split("\n")
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped[:max_chars]
    return ""


def _split_table_by_rows(table_text: str, chunk_size: int, is_html: bool) -> list[str]:
    """대형 테이블을 헤더 유지하면서 행 단위로 분할."""
    if is_html:
        return _split_html_table_by_rows(table_text, chunk_size)
    else:
        return _split_md_table_by_rows(table_text, chunk_size)


def _split_html_table_by_rows(table_text: str, chunk_size: int) -> list[str]:
    """HTML 테이블을 행 단위로 분할."""
    # 헤더 행 추출 (첫 번째 <tr>...</tr>)
    header_match = re.search(
        r"(<table\b[^>]*>.*?<tr\b[^>]*>.*?</tr>)",
        table_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not header_match:
        return [table_text]

    header = header_match.group(1)
    # 나머지 행들 추출
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", table_text, re.DOTALL | re.IGNORECASE)
    if len(rows) <= 1:
        return [table_text]

    # 첫 행은 헤더이므로 제외
    data_rows = rows[1:]

    chunks = []
    current_rows = []
    current_size = len(header) + len("</table>")

    for row in data_rows:
        row_size = len(row)
        if current_size + row_size > chunk_size and current_rows:
            # 현재 청크 마무리
            chunk = header + "\n".join(current_rows) + "\n</table>"
            chunks.append(chunk)
            current_rows = []
            current_size = len(header) + len("</table>")

        current_rows.append(row)
        current_size += row_size

    # 마지막 청크
    if current_rows:
        chunk = header + "\n".join(current_rows) + "\n</table>"
        chunks.append(chunk)

    return chunks if chunks else [table_text]


def _split_md_table_by_rows(table_text: str, chunk_size: int) -> list[str]:
    """마크다운 테이블을 행 단위로 분할."""
    lines = table_text.strip().split("\n")
    if len(lines) <= 2:
        return [table_text]

    # 헤더: 첫 줄 + 구분선 (있으면)
    header_lines = [lines[0]]
    data_start = 1
    if len(lines) > 1 and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[1]):
        header_lines.append(lines[1])
        data_start = 2

    header = "\n".join(header_lines)
    data_rows = lines[data_start:]

    if not data_rows:
        return [table_text]

    chunks = []
    current_rows = []
    current_size = len(header)

    for row in data_rows:
        row_size = len(row) + 1  # +1 for newline
        if current_size + row_size > chunk_size and current_rows:
            chunk = header + "\n" + "\n".join(current_rows)
            chunks.append(chunk)
            current_rows = []
            current_size = len(header)

        current_rows.append(row)
        current_size += row_size

    if current_rows:
        chunk = header + "\n" + "\n".join(current_rows)
        chunks.append(chunk)

    return chunks if chunks else [table_text]


def split_preserving_tables(
    docs: list[Document],
    text_splitter,
    chunk_size: int = 500,
) -> list[Document]:
    """
    테이블을 보존하면서 문서를 청킹한다.

    1. 각 문서에서 테이블을 분리
    2. 텍스트 부분만 text_splitter로 청킹
    3. 테이블은 별도 청크로 보존 (대형 테이블은 행 단위 분할)
    4. 원래 순서대로 합침

    Args:
        docs: 원본 Document 리스트
        text_splitter: LangChain 텍스트 스플리터 (또는 None이면 텍스트도 분할 안 함)
        chunk_size: 테이블 분할 시 최대 청크 크기
    """
    result = []

    for doc in docs:
        text = doc.page_content
        metadata = doc.metadata or {}
        tables = _find_tables(text)

        if not tables:
            # 테이블 없으면 일반 청킹
            if text_splitter:
                result.extend(text_splitter.split_documents([doc]))
            else:
                result.append(doc)
            continue

        # 텍스트/테이블 세그먼트로 분리
        segments = []  # (type, content)
        prev_end = 0

        for start, end, table_text in tables:
            text_before = text[prev_end:start].strip()
            if text_before:
                segments.append(("text", text_before))
            segments.append(("table", table_text))
            prev_end = end

        text_after = text[prev_end:].strip()
        if text_after:
            segments.append(("text", text_after))

        # 세그먼트 처리: 텍스트는 일반 청킹, 테이블은 직전 청크에 붙임
        # 단, 직전 청크 + 테이블 크기가 chunk_size*2를 넘으면 새 청크로 분리한다
        # (임베딩 모델 토큰 한계 초과 방지)
        max_merged_size = chunk_size * 2
        for seg_type, content in segments:
            if seg_type == "text":
                if text_splitter and content:
                    text_doc = Document(page_content=content, metadata=metadata)
                    result.extend(text_splitter.split_documents([text_doc]))
                elif content:
                    result.append(Document(page_content=content, metadata=metadata))
            elif seg_type == "table":
                merged_size = (
                    len(result[-1].page_content) + len(content) + 2 if result else 0
                )
                if result and merged_size <= max_merged_size:
                    last = result[-1]
                    last.page_content = last.page_content + "\n\n" + content
                    last.metadata = {**last.metadata, "has_table": True}
                else:
                    result.append(
                        Document(
                            page_content=content,
                            metadata={**metadata, "has_table": True},
                        )
                    )

    log.info(
        f"Table-preserving chunking: {len(docs)} docs → {len(result)} chunks "
        f"(tables found: {sum(len(_find_tables(d.page_content)) for d in docs)})"
    )
    return result


def apply_chunk_overlap(
    chunks: list[Document],
    overlap_chars: int,
) -> list[Document]:
    """
    청크 결과에 문자 단위 오버랩을 후처리로 적용한다.

    각 청크 N+1의 앞에 청크 N의 마지막 `overlap_chars` 글자를 prepend한다.
    SemanticChunker처럼 오버랩을 자체 지원하지 않는 splitter의 후처리에 사용.

    - 첫 청크는 변경 없음
    - 단어 중간이 잘리지 않도록 공백/줄바꿈 경계로 정렬
    - has_table=True 청크는 표 보존을 위해 오버랩 적용 안 함
    """
    if len(chunks) <= 1 or overlap_chars <= 0:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        curr = chunks[i]

        # 표가 있는 청크는 오버랩 적용하지 않음 (표 구조 보존)
        if curr.metadata and curr.metadata.get("has_table"):
            result.append(curr)
            continue

        prev_text = prev.page_content
        if len(prev_text) <= overlap_chars:
            overlap_text = prev_text
        else:
            overlap_text = prev_text[-overlap_chars:]
            # 잘린 단어 방지: 첫 공백/줄바꿈 이후부터 시작
            for sep in ["\n", " "]:
                idx = overlap_text.find(sep)
                if 0 <= idx < 50:
                    overlap_text = overlap_text[idx + 1 :]
                    break

        overlap_text = overlap_text.strip()
        if not overlap_text:
            result.append(curr)
            continue

        new_chunk = Document(
            page_content=overlap_text + "\n\n" + curr.page_content,
            metadata=curr.metadata,
        )
        result.append(new_chunk)

    log.info(f"Applied chunk overlap ({overlap_chars} chars) to {len(chunks)} chunks")
    return result


_ENCODING_CACHE: dict = {}


def _get_encoding(encoding_name: str):
    """tiktoken 인코딩을 캐시하여 반환. 알 수 없는 이름은 cl100k_base 로 폴백."""
    import tiktoken

    enc = _ENCODING_CACHE.get(encoding_name)
    if enc is None:
        try:
            enc = tiktoken.get_encoding(encoding_name)
        except Exception:
            log.warning(
                f"Unknown tiktoken encoding '{encoding_name}', falling back to cl100k_base"
            )
            enc = tiktoken.get_encoding("cl100k_base")
        _ENCODING_CACHE[encoding_name] = enc
    return enc


def enforce_token_bounds(
    docs: list[Document],
    max_tokens: int = 0,
    min_tokens: int = 0,
    encoding_name: str = "cl100k_base",
    overlap_tokens: int = 0,
) -> list[Document]:
    """
    토큰 단위 청크 크기 안전망. 모든 splitter(character/token/semantic) + overlap +
    contextual 후처리 이후, 임베딩 직전에 호출하는 범용 후처리.

    - max_tokens > 0: 토큰 수가 max_tokens 를 초과하는 청크를 토큰 경계로 재분할한다.
      임베딩 모델 토큰 한도 초과로 배치 전체(generate_*_batch_embeddings → None)가
      실패하는 것을 방지. 표 청크(has_table)도 한도 초과 시 분할한다 (크래시 방지 우선).
    - min_tokens > 0: min_tokens 미만인 청크를 다음 인접 청크와 병합한다.
      단 max_tokens 를 넘기지 않고, has_table 청크는 구조 보존을 위해 병합 대상에서 제외.

    Args:
        docs: 청킹 결과 Document 리스트
        max_tokens: 청크당 최대 토큰 (0 = 비활성)
        min_tokens: 청크당 최소 토큰 — 미만이면 병합 (0 = 비활성)
        encoding_name: tiktoken 인코딩명 (TIKTOKEN_ENCODING_NAME)
        overlap_tokens: 재분할 시 sub-chunk 간 토큰 오버랩
    """
    if not docs or (max_tokens <= 0 and min_tokens <= 0):
        return docs

    enc = _get_encoding(encoding_name)

    # 1) 최대 토큰 초과 청크 재분할
    if max_tokens and max_tokens > 0:
        step = max_tokens - overlap_tokens
        if step <= 0:
            step = max_tokens

        bounded: list[Document] = []
        split_count = 0
        for doc in docs:
            tokens = enc.encode(doc.page_content)
            if len(tokens) <= max_tokens:
                bounded.append(doc)
                continue

            part = 0
            start = 0
            while start < len(tokens):
                window = tokens[start : start + max_tokens]
                sub_text = enc.decode(window).strip()
                if sub_text:
                    meta = {**(doc.metadata or {}), "token_split_part": part}
                    bounded.append(Document(page_content=sub_text, metadata=meta))
                    part += 1
                start += step
            split_count += 1
            log.info(
                f"enforce_token_bounds: split oversized chunk ({len(tokens)} tokens) "
                f"into {part} sub-chunks (max_tokens={max_tokens})"
            )

        if split_count:
            log.info(
                f"enforce_token_bounds: {split_count} oversized chunk(s) re-split "
                f"→ {len(bounded)} total chunks"
            )
        docs = bounded

    # 2) 최소 토큰 미만 청크 병합
    if min_tokens and min_tokens > 0 and len(docs) > 1:
        merged: list[Document] = []
        for doc in docs:
            if not merged:
                merged.append(doc)
                continue

            prev = merged[-1]
            # 표 청크는 병합하지 않음 (구조 보존)
            if (prev.metadata or {}).get("has_table") or (doc.metadata or {}).get(
                "has_table"
            ):
                merged.append(doc)
                continue

            if len(enc.encode(prev.page_content)) >= min_tokens:
                merged.append(doc)
                continue

            combined = prev.page_content + "\n\n" + doc.page_content
            # 병합이 max_tokens 를 넘기면 병합하지 않음 (1단계 보장 유지)
            if max_tokens and max_tokens > 0 and len(enc.encode(combined)) > max_tokens:
                merged.append(doc)
                continue

            prev.page_content = combined  # 메타데이터는 prev 유지

        if len(merged) != len(docs):
            log.info(
                f"enforce_token_bounds: merged undersized chunks "
                f"{len(docs)} → {len(merged)} (min_tokens={min_tokens})"
            )
        docs = merged

    return docs
