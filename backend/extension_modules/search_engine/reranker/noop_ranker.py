"""
Reranker - No-op 구현

리랭커 미사용 시 fallback. threshold 필터링만 적용하고 순서를 유지합니다.
"""

from typing import List

from ..models import SearchResult
from .base import RerankerBase


class NoopRanker(RerankerBase):
    """리랭커 미사용 시 fallback. threshold 필터링만 적용."""

    async def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> List[SearchResult]:
        filtered = [r for r in results if r.score >= threshold]
        return filtered[:top_k]
