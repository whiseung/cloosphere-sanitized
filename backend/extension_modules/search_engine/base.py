"""
Search Engine - 추상 베이스 클래스
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Optional, Union

from .models import DocumentItem, IndexConfig, SearchQuery, SearchResult

if TYPE_CHECKING:
    from .embedding import EmbeddingConfig

log = logging.getLogger(__name__)


class SearchEngineBase(ABC):
    """
    검색 엔진 추상 베이스 클래스.

    모든 검색 엔진 구현체는 이 클래스를 상속받아야 합니다.
    비동기(async) 인터페이스를 사용합니다.

    Args:
        config: 인덱스 설정
        embedding_config: 임베딩 설정 (선택). 설정 시 검색 시 자동 임베딩 생성.
        reranker: 리랭커 인스턴스 (선택). 설정 시 검색 결과 재정렬.
    """

    def __init__(
        self,
        config: IndexConfig,
        embedding_config: Optional["EmbeddingConfig"] = None,
        reranker: Optional[Any] = None,
    ):
        self.config = config
        self.index_name = config.index_name
        self.embedding_config = embedding_config
        self._reranker = reranker

    # === 임베딩 헬퍼 ===

    async def generate_embedding(
        self,
        text: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[float]:
        """
        텍스트에 대한 임베딩 벡터를 생성합니다.

        Args:
            text: 임베딩할 텍스트
            user_id: 사용량 추적용 사용자 ID (선택)
            chat_id: 사용량 추적용 채팅 ID (선택)

        Returns:
            List[float]: 임베딩 벡터

        Raises:
            RuntimeError: embedding_config가 설정되지 않은 경우
        """
        if self.embedding_config is None:
            raise RuntimeError(
                "Embedding config not set. "
                "Pass embedding_config to constructor or use query_vector parameter."
            )

        from .embedding import generate_embedding_async

        return await generate_embedding_async(
            text=text,
            config=self.embedding_config,
            user_id=user_id,
            chat_id=chat_id,
        )

    async def generate_embeddings(
        self,
        texts: Union[str, List[str]],
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[List[float]]:
        """
        여러 텍스트에 대한 임베딩 벡터를 생성합니다.

        Args:
            texts: 임베딩할 텍스트 또는 텍스트 리스트
            user_id: 사용량 추적용 사용자 ID (선택)
            chat_id: 사용량 추적용 채팅 ID (선택)

        Returns:
            List[List[float]]: 임베딩 벡터 리스트

        Raises:
            RuntimeError: embedding_config가 설정되지 않은 경우
        """
        if self.embedding_config is None:
            raise RuntimeError(
                "Embedding config not set. Pass embedding_config to constructor."
            )

        from .embedding import generate_embeddings_async

        result = await generate_embeddings_async(
            texts=texts,
            config=self.embedding_config,
            user_id=user_id,
            chat_id=chat_id,
        )
        return result.embeddings

    # === Async Context Manager ===

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @abstractmethod
    async def close(self) -> None:
        """리소스 정리 및 연결 종료"""
        pass

    # === Index 관리 ===

    @abstractmethod
    async def create_index(self) -> bool:
        """
        인덱스 생성.

        Returns:
            bool: 생성 성공 여부 (이미 존재하면 False)
        """
        pass

    @abstractmethod
    async def delete_index(self) -> bool:
        """
        인덱스 삭제.

        Returns:
            bool: 삭제 성공 여부
        """
        pass

    @abstractmethod
    async def index_exists(self) -> bool:
        """
        인덱스 존재 여부 확인.

        Returns:
            bool: 존재 여부
        """
        pass

    # === CRUD ===

    @abstractmethod
    async def insert(self, documents: List[DocumentItem]) -> int:
        """
        문서 삽입 (bulk).

        Args:
            documents: 삽입할 문서 리스트

        Returns:
            int: 삽입된 문서 수
        """
        pass

    @abstractmethod
    async def get(self, ids: List[str]) -> List[DocumentItem]:
        """
        ID로 문서 조회.

        Args:
            ids: 조회할 문서 ID 리스트

        Returns:
            List[DocumentItem]: 조회된 문서 리스트
        """
        pass

    @abstractmethod
    async def update(self, documents: List[DocumentItem]) -> int:
        """
        문서 업데이트 (upsert).

        Args:
            documents: 업데이트할 문서 리스트

        Returns:
            int: 업데이트된 문서 수
        """
        pass

    @abstractmethod
    async def delete(self, ids: List[str]) -> int:
        """
        문서 삭제.

        Args:
            ids: 삭제할 문서 ID 리스트

        Returns:
            int: 삭제된 문서 수
        """
        pass

    @abstractmethod
    async def delete_by_filter(self, filter_expr: str) -> int:
        """
        필터 조건으로 문서 삭제.

        Args:
            filter_expr: 필터 표현식 (OData 형식)

        Returns:
            int: 삭제된 문서 수
        """
        pass

    # === 검색 ===

    @abstractmethod
    async def search(
        self,
        query: SearchQuery,
        query_vector: Optional[List[float]] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        하이브리드 검색 (벡터 + 키워드 + 시맨틱).

        Args:
            query: 검색 쿼리
            query_vector: 사전 계산된 임베딩 벡터 (선택).
                          embedding_config 설정 시 자동 생성.
            user_id: 임베딩 사용량 추적용 사용자 ID (선택)
            chat_id: 임베딩 사용량 추적용 채팅 ID (선택)

        Returns:
            List[SearchResult]: 검색 결과 리스트 (score 내림차순)
        """
        pass

    @abstractmethod
    async def vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        벡터 전용 검색.

        Args:
            vector: 검색 벡터
            top_k: 반환할 최대 결과 수
            filter_expr: 필터 표현식 (선택)

        Returns:
            List[SearchResult]: 검색 결과 리스트
        """
        pass

    async def hybrid_search(
        self,
        text: str,
        vector: Optional[List[float]] = None,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        하이브리드 검색 (벡터 + 키워드).

        search()의 편의 래퍼로, 간단한 파라미터로 하이브리드 검색을 수행합니다.
        구현체에서 오버라이드하여 최적화된 하이브리드 검색을 제공할 수 있습니다.

        Args:
            text: 검색 텍스트 (키워드 검색용)
            vector: 사전 계산된 임베딩 벡터 (선택). 없으면 자동 생성 시도.
            top_k: 반환할 최대 결과 수
            filter_expr: 필터 표현식 (선택)
            user_id: 임베딩 사용량 추적용 사용자 ID (선택)
            chat_id: 임베딩 사용량 추적용 채팅 ID (선택)

        Returns:
            List[SearchResult]: 검색 결과 리스트
        """
        query = SearchQuery(
            query=text,
            filter=filter_expr,
            top_k=top_k,
        )
        return await self.search(
            query=query,
            query_vector=vector,
            user_id=user_id,
            chat_id=chat_id,
        )

    async def multi_vector_search(
        self,
        text: str,
        vector: Optional[List[float]] = None,
        secondary_vector: Optional[List[float]] = None,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
        primary_weight: float = 0.5,
        secondary_weight: float = 0.5,
        reranker_threshold: float = 0.0,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Multi-vector 검색 (기본 벡터 + 보조 벡터 가중 앙상블).

        구현체에서 오버라이드하여 최적화된 검색 제공.
        기본 구현: primary_weight로 1차 검색만 수행.

        Args:
            text: 검색 텍스트
            vector: 사전 계산된 기본 임베딩 벡터 (선택)
            secondary_vector: 사전 계산된 보조 임베딩 벡터 (선택)
            top_k: 반환할 최대 결과 수
            filter_expr: 필터 표현식 (OData)
            primary_weight: 기본 벡터 가중치 (0-1 또는 0-4, 자동 감지)
            secondary_weight: 보조 벡터 가중치 (0-1 또는 0-4, 자동 감지)
            user_id: 임베딩 사용량 추적용
            chat_id: 임베딩 사용량 추적용

        Returns:
            List[SearchResult]: 검색 결과 리스트
        """
        # 기본 구현 - 단일 벡터만 사용
        return await self.hybrid_search(
            text=text,
            vector=vector,
            top_k=top_k,
            filter_expr=filter_expr,
            user_id=user_id,
            chat_id=chat_id,
        )

    # === 필터링 ===

    @abstractmethod
    async def filter_by_metadata(
        self,
        filter_expr: str,
        limit: int = 100,
    ) -> List[DocumentItem]:
        """
        메타데이터 기반 필터링.

        Args:
            filter_expr: 필터 표현식 (OData 형식)
            limit: 반환할 최대 문서 수

        Returns:
            List[DocumentItem]: 필터링된 문서 리스트
        """
        pass

    # === 유틸리티 ===

    @abstractmethod
    async def count(self, filter_expr: Optional[str] = None) -> int:
        """
        문서 수 조회.

        Args:
            filter_expr: 필터 표현식 (선택)

        Returns:
            int: 문서 수
        """
        pass
