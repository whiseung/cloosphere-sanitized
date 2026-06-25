"""
Reranker - 추상 베이스 클래스

검색 결과를 의미론적으로 재정렬하는 리랭커 인터페이스.
"""

from abc import ABC, abstractmethod
from typing import List

from ..models import SearchResult


class RerankerBase(ABC):
    """
    리랭커 추상 인터페이스.

    구현체 추가 시 이 클래스를 상속하고 rerank() 메서드를 구현합니다.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> List[SearchResult]:
        """
        검색 결과를 의미론적으로 재정렬.

        Args:
            query: 원본 검색 쿼리
            results: 재정렬할 검색 결과 리스트
            top_k: 반환할 최대 결과 수
            threshold: 최소 점수 임계값 (0-1). 이 값 미만의 결과는 제거.

        Returns:
            List[SearchResult]: 재정렬된 검색 결과 (score 0-1 범위, 내림차순)
        """
        ...

    async def close(self) -> None:
        """리소스 정리"""
        pass
