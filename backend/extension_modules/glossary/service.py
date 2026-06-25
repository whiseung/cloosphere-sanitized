"""
Glossary - 검색 엔진 색인 서비스

워크스페이스 > 용어집에서 입력된 용어를 검색 엔진에 색인합니다.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from extension_modules.search_engine import (
    DocumentItem,
    SearchQuery,
    create_glossary_config,
    get_configured_search_engine,
)
from fastapi import FastAPI
from open_webui.env import SRC_LOG_LEVELS

from .embedding import generate_embedding, get_vector_dimension
from .models import GlossaryEntryInput, GlossarySearchResult

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class GlossaryIndexService:
    """
    용어집 검색 엔진 색인 서비스.

    관리자 > 설정 > 검색 엔진 설정을 사용하여 용어를 색인합니다.
    임베딩은 관리자 > 설정 > 문서의 RAG 설정을 사용합니다.

    Usage:
        >>> service = GlossaryIndexService(request.app)
        >>> await service.index_entry(entry)
        >>> await service.delete_entry(entry_id, glossary_id)
    """

    def __init__(self, app: FastAPI):
        """
        서비스 초기화.

        Args:
            app: FastAPI 앱 인스턴스 (설정 접근용)
        """
        self.app = app

    def _get_engine(self):
        """검색 엔진 인스턴스 생성."""
        vector_dim = get_vector_dimension(self.app)
        index_config = create_glossary_config(vector_dim=vector_dim)
        engine = get_configured_search_engine(self.app, index_config)

        if not engine:
            raise ValueError(
                "Search engine not configured. "
                "Please configure in Admin > Settings > Search Engine."
            )

        return engine

    async def ensure_index_exists(self) -> bool:
        """
        인덱스가 존재하는지 확인하고, 없으면 생성.

        Returns:
            bool: 인덱스가 새로 생성되었으면 True, 이미 존재하면 False
        """
        engine = self._get_engine()

        async with engine:
            if await engine.index_exists():
                log.debug("Glossary index already exists")
                return False

            log.info("Creating glossary index: default_glossary")
            await engine.create_index()
            return True

    async def index_entry(self, entry: GlossaryEntryInput) -> str:
        """
        용어를 검색 엔진에 색인.

        Args:
            entry: 색인할 용어 정보

        Returns:
            str: 색인된 문서 ID

        Raises:
            ValueError: 검색 엔진 또는 임베딩이 설정되지 않은 경우
            RuntimeError: 색인 실패 시
        """
        # 1. 임베딩 컨텐츠 생성
        embedding_content = entry.to_embedding_content()
        log.debug(f"Embedding content for {entry.term}: {embedding_content[:100]}...")

        # 2. 임베딩 생성
        vector = generate_embedding(self.app, embedding_content)
        log.debug(f"Generated embedding vector with {len(vector)} dimensions")

        # 3. DocumentItem 생성
        now = datetime.now(timezone.utc)
        document = DocumentItem(
            id=entry.id,
            content=embedding_content,
            vector=vector,
            metadata={
                "term": entry.term,
                "synonyms": entry.synonyms,
                "description": entry.description,
                "example": entry.example,
                "category": entry.category,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
            collection=entry.glossary_id,  # glossary_id를 collection으로 사용
        )

        # 4. 검색 엔진에 색인
        engine = self._get_engine()

        async with engine:
            # 인덱스 없으면 생성
            if not await engine.index_exists():
                log.info("Creating glossary index")
                await engine.create_index()

            # upsert (이미 존재하면 업데이트)
            await engine.update([document])
            log.info(f"Indexed glossary entry: {entry.term} (id={entry.id})")

        return entry.id

    async def index_entries(self, entries: list[GlossaryEntryInput]) -> int:
        """여러 용어를 일괄 색인 (upsert).

        Adapter 가 batch chunking 을 책임지므로 여기서는 임베딩 생성 + 단일
        ``engine.update`` 호출만. partial doc-level 실패 시 adapter 가 warning
        로깅 + count<len 반환, caller(router) 가 meta 기록.
        """
        if not entries:
            return 0

        # 1. 임베딩 일괄 생성
        contents = [entry.to_embedding_content() for entry in entries]
        log.debug(
            "[GLOSSARY_INDEX] generate_embedding input: entries=%d, total_chars=%d",
            len(entries),
            sum(len(c) for c in contents),
        )
        vectors = generate_embedding(self.app, contents)

        # generate_embedding 은 list 입력에 list[list[float]] 반환이 계약.
        # 위반 시 단건은 wrap 으로 복구하지만 멀티 entries 에 scalar 가 돌아오면
        # silent truncation 이라 raise — search 실패가 아니라 코드 버그이므로
        # caller 의 error 분기로 명확히 흐른다.
        if vectors and not isinstance(vectors[0], list):
            if len(entries) > 1:
                raise RuntimeError(
                    f"embedding contract violation: list input (n={len(entries)}) "
                    f"returned scalar — would truncate to 1 entry"
                )
            log.warning(
                "[GLOSSARY_INDEX] single-entry embedding returned scalar — wrapping"
            )
            vectors = [vectors]
        elif len(vectors) != len(entries):
            raise RuntimeError(
                f"embedding count mismatch: entries={len(entries)} vs "
                f"vectors={len(vectors)} — would truncate via zip()"
            )

        # 2. DocumentItem 목록 생성
        now = datetime.now(timezone.utc)
        documents = [
            DocumentItem(
                id=entry.id,
                content=entry.to_embedding_content(),
                vector=vector,
                metadata={
                    "term": entry.term,
                    "synonyms": entry.synonyms,
                    "description": entry.description,
                    "example": entry.example,
                    "category": entry.category,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                },
                collection=entry.glossary_id,
            )
            for entry, vector in zip(entries, vectors)
        ]

        # 3. 검색 엔진에 일괄 색인 (adapter 가 chunk 분할)
        engine = self._get_engine()
        async with engine:
            if not await engine.index_exists():
                log.info("[GLOSSARY_INDEX] creating glossary index")
                await engine.create_index()
            count = await engine.update(documents)

        log.info("[GLOSSARY_INDEX] index_entries: indexed=%d/%d", count, len(entries))
        return count

    async def delete_entry(self, entry_id: str) -> bool:
        """
        용어 삭제.

        Args:
            entry_id: 삭제할 용어 ID

        Returns:
            bool: 삭제 성공 여부
        """
        engine = self._get_engine()

        async with engine:
            if not await engine.index_exists():
                log.warning("Glossary index does not exist")
                return False

            count = await engine.delete([entry_id])
            if count > 0:
                log.info(f"Deleted glossary entry: {entry_id}")
                return True
            else:
                log.warning(f"Glossary entry not found: {entry_id}")
                return False

    async def delete_by_glossary(self, glossary_id: str) -> int:
        """
        특정 용어집의 모든 용어 삭제.

        Args:
            glossary_id: 용어집 ID

        Returns:
            int: 삭제된 용어 수
        """
        engine = self._get_engine()

        async with engine:
            if not await engine.index_exists():
                log.warning("Glossary index does not exist")
                return 0

            # collection 필터로 삭제
            count = await engine.delete_by_filter(f"collection eq '{glossary_id}'")
            log.info(f"Deleted {count} entries from glossary: {glossary_id}")
            return count

    async def search(
        self,
        query: str,
        glossary_id: Optional[str] = None,
        category: Optional[str] = None,
        top_k: int = 10,
    ) -> list[GlossarySearchResult]:
        """
        용어 검색.

        Args:
            query: 검색어
            glossary_id: 특정 용어집으로 제한 (선택)
            category: 특정 카테고리로 제한 (선택). 인덱스에 저장된 `category`
                필드와 정확히 일치하는 entries 만 반환한다. 검색 인덱스가
                category 를 metadata 필드로 이미 저장하고 있으므로 서버
                사이드 필터로 동작한다.
            top_k: 반환할 결과 수

        Returns:
            list[GlossarySearchResult]: 검색 결과 목록
        """
        engine = self._get_engine()

        # 검색어 임베딩
        query_vector = generate_embedding(self.app, query)

        # 필터 생성
        filters: list[str] = []
        if glossary_id:
            filters.append(f"collection eq '{glossary_id}'")
        if category:
            # OData 문자열 리터럴의 single quote 는 '' 로 escape
            escaped = category.replace("'", "''")
            filters.append(f"category eq '{escaped}'")
        filter_expr = " and ".join(filters) if filters else None

        async with engine:
            if not await engine.index_exists():
                log.warning("Glossary index does not exist")
                return []

            search_query = SearchQuery(
                query=query,
                filter=filter_expr,
                top_k=top_k,
            )

            results = await engine.search(search_query, query_vector=query_vector)

        # 결과 변환
        search_results = []
        for result in results:
            metadata = result.metadata or {}
            search_results.append(
                GlossarySearchResult(
                    id=result.id,
                    glossary_id=metadata.get("collection", ""),
                    term=metadata.get("term", ""),
                    synonyms=metadata.get("synonyms", []),
                    description=metadata.get("description", ""),
                    example=metadata.get("example", ""),
                    category=metadata.get("category"),
                    score=result.score,
                    created_at=metadata.get("created_at"),
                    updated_at=metadata.get("updated_at"),
                )
            )

        return search_results

    async def get_entry_count(self, glossary_id: Optional[str] = None) -> int:
        """
        색인된 용어 수 조회.

        Args:
            glossary_id: 특정 용어집으로 제한 (선택)

        Returns:
            int: 용어 수
        """
        engine = self._get_engine()

        async with engine:
            if not await engine.index_exists():
                return 0

            filter_expr = f"collection eq '{glossary_id}'" if glossary_id else None
            return await engine.count(filter_expr)
