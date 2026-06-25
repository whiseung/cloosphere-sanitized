"""Guide BM25 in-memory retriever.

고객사 임베딩 비용 0 + admin 재빌드 버튼 불필요. startup 시 한 번 빌드 후 메모리 상주.
콘텐츠 hash 변경 감지 시 자동 재빌드.

Tokenizer: 영문은 word-level, 한글은 char-bigram (agglutinative 언어 대응).
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

from extension_modules.guide_agent.catalog import (
    CATALOG_PATH,
    load_catalog,
    resolve_doc_path,
)
from extension_modules.guide_agent.chunker import Chunk, chunk_document
from extension_modules.guide_agent.mdx_cleaner import clean_mdx
from rank_bm25 import BM25Okapi

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")
_NON_HANGUL_RE = re.compile(r"[^가-힣]+")


def _tokenize(text: str) -> list[str]:
    """Bilingual tokenizer: 영문 word + 한글 char-bigram."""
    if not text:
        return []
    lower = text.lower()
    tokens = list(_WORD_RE.findall(lower))
    for word in _NON_HANGUL_RE.split(lower):
        if not word:
            continue
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


@dataclass
class IndexedChunk:
    chunk: Chunk
    tokens: list[str]


@dataclass
class BM25Index:
    bm25_ko: BM25Okapi | None
    bm25_en: BM25Okapi | None
    chunks_ko: list[IndexedChunk]
    chunks_en: list[IndexedChunk]
    content_hash: str
    chunk_count: int


_INDEX_LOCK = threading.Lock()
_INDEX: BM25Index | None = None


def _hash_inputs(catalog: dict[str, Any]) -> str:
    """카탈로그 + 모든 mdx 파일 hash → 콘텐츠 변경 자동 감지."""
    h = hashlib.sha256()
    if CATALOG_PATH.exists():
        h.update(CATALOG_PATH.read_bytes())
    for entry in catalog.get("categories", []):
        for lang in ("ko", "en"):
            abs_path = resolve_doc_path(entry.get(f"file_{lang}", ""))
            if abs_path is not None:
                h.update(abs_path.read_bytes())
    return h.hexdigest()


def _collect_chunks(catalog: dict[str, Any]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for entry in catalog.get("categories", []):
        for lang in ("ko", "en"):
            file_path = entry.get(f"file_{lang}")
            abs_path = resolve_doc_path(file_path) if file_path else None
            if abs_path is None:
                continue
            cleaned = clean_mdx(
                abs_path.read_text(encoding="utf-8"), source=str(abs_path), strict=False
            )
            doc_chunks = chunk_document(
                content=cleaned.content,
                title=entry.get(f"title_{lang}") or cleaned.title,
                category=entry["id"],
                lang=lang,
                audience=entry["audience"],
                file_path=file_path,
            )
            chunks.extend(doc_chunks)
    return chunks


def _build_index() -> BM25Index:
    catalog = load_catalog()
    content_hash = _hash_inputs(catalog)
    chunks = _collect_chunks(catalog)

    indexed_ko: list[IndexedChunk] = []
    indexed_en: list[IndexedChunk] = []
    for c in chunks:
        # heading_path 와 content 모두 토큰화 (제목 매칭 가중치)
        tokens = _tokenize(f"{c.heading_path}\n{c.content}")
        if not tokens:
            continue
        ic = IndexedChunk(chunk=c, tokens=tokens)
        if c.lang == "en":
            indexed_en.append(ic)
        else:
            indexed_ko.append(ic)

    bm25_ko = BM25Okapi([ic.tokens for ic in indexed_ko]) if indexed_ko else None
    bm25_en = BM25Okapi([ic.tokens for ic in indexed_en]) if indexed_en else None
    log.info(
        "Built guide BM25 index: ko=%d en=%d hash=%s",
        len(indexed_ko),
        len(indexed_en),
        content_hash[:8],
    )
    return BM25Index(
        bm25_ko=bm25_ko,
        bm25_en=bm25_en,
        chunks_ko=indexed_ko,
        chunks_en=indexed_en,
        content_hash=content_hash,
        chunk_count=len(indexed_ko) + len(indexed_en),
    )


def get_index(force_rebuild: bool = False) -> BM25Index:
    """Cached BM25 인덱스 반환. 콘텐츠 hash 변경 시 자동 재빌드."""
    global _INDEX
    if _INDEX is not None and not force_rebuild:
        try:
            current_hash = _hash_inputs(load_catalog())
            if current_hash == _INDEX.content_hash:
                return _INDEX
            log.info(
                "Guide content hash changed (%s → %s), rebuilding",
                _INDEX.content_hash[:8],
                current_hash[:8],
            )
        except Exception as e:
            log.warning("Failed to check content hash, using cached index: %s", e)
            return _INDEX

    with _INDEX_LOCK:
        if _INDEX is None or force_rebuild:
            _INDEX = _build_index()
        else:
            # double-check after acquiring lock
            current_hash = _hash_inputs(load_catalog())
            if current_hash != _INDEX.content_hash:
                _INDEX = _build_index()
    return _INDEX


def search(
    query: str,
    *,
    role: str,
    lang: str = "ko",
    top_k: int = 8,
    max_per_category: int = 3,
) -> list[tuple[Chunk, float]]:
    """BM25 검색 + audience 필터 + 카테고리 다양성.

    Args:
        query: 자연어 질문
        role: 'user' | 'admin' — admin/* + monitoring/* 카테고리 필터링
        lang: 'ko' | 'en' — 우선 검색 언어, 부족 시 다른 언어로 보충
        top_k: 반환할 청크 수
        max_per_category: 카테고리당 최대 결과 수 (다양성)

    Returns:
        [(Chunk, score), ...] 점수 내림차순
    """
    index = get_index()
    if index.chunk_count == 0:
        return []

    primary_chunks, primary_bm25 = (
        (index.chunks_en, index.bm25_en)
        if lang == "en"
        else (index.chunks_ko, index.bm25_ko)
    )
    secondary_chunks, secondary_bm25 = (
        (index.chunks_ko, index.bm25_ko)
        if lang == "en"
        else (index.chunks_en, index.bm25_en)
    )

    tokens = _tokenize(query)
    if not tokens:
        return []

    is_admin = role == "admin"

    def _score(
        bm25: BM25Okapi | None, indexed: list[IndexedChunk]
    ) -> list[tuple[IndexedChunk, float]]:
        if bm25 is None or not indexed:
            return []
        scores = bm25.get_scores(tokens)
        ranked = sorted(zip(indexed, scores), key=lambda x: x[1], reverse=True)
        return ranked

    pool = _score(primary_bm25, primary_chunks)
    # 동일 언어 결과가 임계치 미달이거나 점수 0 인 경우 다른 언어 보충
    if not pool or pool[0][1] <= 0 or len([p for p in pool if p[1] > 0]) < top_k:
        pool = pool + _score(secondary_bm25, secondary_chunks)

    counts: dict[str, int] = {}
    out: list[tuple[Chunk, float]] = []
    for ic, score in pool:
        if score <= 0:
            continue
        chunk = ic.chunk
        if not is_admin and chunk.audience == "admin":
            continue
        if counts.get(chunk.category, 0) >= max_per_category:
            continue
        counts[chunk.category] = counts.get(chunk.category, 0) + 1
        out.append((chunk, float(score)))
        if len(out) >= top_k:
            break
    return out


def warmup() -> None:
    """Application startup hook: 인덱스 미리 빌드해 첫 쿼리 지연 제거."""
    try:
        idx = get_index()
        log.info("Guide BM25 warmup complete: %d chunks indexed", idx.chunk_count)
    except Exception as e:
        log.warning("Guide BM25 warmup failed (non-fatal): %s", e)


__all__ = [
    "BM25Index",
    "IndexedChunk",
    "get_index",
    "search",
    "warmup",
]
