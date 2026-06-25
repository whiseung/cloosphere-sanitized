"""
Knowledge Service using search_engine module.

DbSphere Memory 패턴을 따르며, 문서 청크 저장 및 검색을 담당합니다.
VECTOR_DB_CLIENT 대신 extension_modules/search_engine/ 모듈을 사용합니다.

인덱스명: default_knowledge (고정)
collection 필드로 각 지식기반(knowledge_id) 또는 파일(file-{file_id}) 구분
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

# 인덱스별 필터 슬롯 보장 여부 추적 (프로세스당 1회)
_ensured_filter_slots: Set[str] = set()

from extension_modules.search_engine import (
    DocumentItem,
    SearchEngineBase,
    SearchResult,
    create_knowledge_config,
    get_configured_search_engine,
)

log = logging.getLogger(__name__)


class SearchEngineKnowledge:
    """
    Knowledge Service using search_engine interface.

    Features:
    - 문서 청크 저장 및 벡터 검색
    - 질의예시 벡터 지원 (multi-vector search)
    - collection 필드로 지식기반 구분
    """

    def __init__(
        self,
        app,
        collection_name: str,
        vector_dim: int = 3072,
        enable_question_vector: bool = False,
    ):
        """
        Initialize Knowledge Service.

        Args:
            app: FastAPI application instance
            collection_name: 지식기반 ID (collection 필드로 필터링)
            vector_dim: 벡터 차원
            enable_question_vector: 질의예시 벡터 검색 활성화
        """
        self.app = app
        self.collection_name = collection_name
        self.vector_dim = vector_dim
        self.enable_question_vector = enable_question_vector

        # Create index config (fixed index name: default_knowledge)
        self.index_config = create_knowledge_config(
            vector_dim=vector_dim,
            enable_question_vector=enable_question_vector,
        )
        self._engine: Optional[SearchEngineBase] = None

    def _get_engine(self) -> Optional[SearchEngineBase]:
        """Get search engine instance."""
        if self._engine is None:
            self._engine = get_configured_search_engine(self.app, self.index_config)
        return self._engine

    async def _ensure_index_exists(self, engine: SearchEngineBase) -> bool:
        """Ensure the index exists, create if needed. Also ensures filter slots are present."""
        try:
            if not await engine.index_exists():
                try:
                    await engine.create_index()
                    log.info(f"Created index: {self.index_config.index_name}")
                except Exception as create_err:
                    # Race condition: another thread may have created the index concurrently
                    if await engine.index_exists():
                        log.info(
                            f"Index '{self.index_config.index_name}' was created by another thread"
                        )
                    else:
                        raise create_err
                _ensured_filter_slots.add(self.index_config.index_name)
            elif self.index_config.index_name not in _ensured_filter_slots:
                # First access after startup: ensure filter slots are present
                if hasattr(engine, "ensure_filter_slots"):
                    engine.ensure_filter_slots()
                _ensured_filter_slots.add(self.index_config.index_name)
            return True
        except Exception as e:
            log.error(f"Failed to ensure index exists: {e}")
            return False

    async def save_chunks(
        self,
        chunks: List[Dict[str, Any]],
        vectors: List[List[float]],
        sample_questions_list: Optional[List[Optional[str]]] = None,
        question_vectors: Optional[List[Optional[List[float]]]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        문서 청크 저장.

        Args:
            chunks: 청크 데이터 리스트 [{text, metadata}, ...]
            vectors: 청크 임베딩 벡터 리스트
            sample_questions_list: 질의예시 텍스트 리스트 (선택)
            question_vectors: 질의예시 임베딩 벡터 리스트 (선택)

        Returns:
            저장된 청크 수
        """
        engine = self._get_engine()
        if not engine:
            log.warning("Search engine not configured")
            return 0

        documents = []
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            doc_id = str(uuid4())
            metadata = chunk.get("metadata", {}).copy()

            # Apply extra_metadata (file-level filter slot values)
            if extra_metadata:
                metadata.update(extra_metadata)

            # Add sample_questions to metadata
            if sample_questions_list and idx < len(sample_questions_list):
                sample_q = sample_questions_list[idx]
                if sample_q:
                    metadata["sample_questions"] = sample_q
            metadata["created_at"] = datetime.now(timezone.utc).isoformat()

            # Build document
            doc = DocumentItem(
                id=doc_id,
                content=chunk.get("text", ""),
                vector=vector,
                collection=self.collection_name,
                metadata=metadata,
            )

            # Add secondary vector if available
            if question_vectors and idx < len(question_vectors):
                q_vec = question_vectors[idx]
                if q_vec:
                    doc.secondary_vector = q_vec

            documents.append(doc)

        async with engine:
            if not await self._ensure_index_exists(engine):
                raise RuntimeError(
                    f"Failed to ensure index '{self.index_config.index_name}' exists"
                )
            return await engine.insert(documents)

    async def search(
        self,
        query: str,
        query_vector: List[float],
        top_k: int = 10,
        use_question_vector: bool = False,
        question_vector_weight: float = 0.5,
    ) -> List[SearchResult]:
        """
        문서 검색.

        Args:
            query: 검색 쿼리
            query_vector: 쿼리 임베딩 벡터
            top_k: 반환할 최대 결과 수
            use_question_vector: 질의예시 벡터 검색 사용 여부
            question_vector_weight: 질의예시 벡터 가중치 (0-1)
        """
        engine = self._get_engine()
        if not engine:
            return []

        filter_expr = f"collection eq '{self.collection_name}'"

        async with engine:
            if not await engine.index_exists():
                return []

            if use_question_vector and self.enable_question_vector:
                return await engine.multi_vector_search(
                    text=query,
                    vector=query_vector,
                    secondary_vector=query_vector,  # 같은 벡터 사용
                    top_k=top_k,
                    filter_expr=filter_expr,
                    primary_weight=1 - question_vector_weight,
                    secondary_weight=question_vector_weight,
                )
            else:
                return await engine.hybrid_search(
                    text=query,
                    vector=query_vector,
                    top_k=top_k,
                    filter_expr=filter_expr,
                )

    async def get_by_ids(self, ids: List[str]) -> List[DocumentItem]:
        """ID로 문서 조회"""
        engine = self._get_engine()
        if not engine:
            return []

        async with engine:
            if not await engine.index_exists():
                return []
            return await engine.get(ids)

    async def delete_by_collection(self) -> int:
        """컬렉션의 모든 문서 삭제"""
        engine = self._get_engine()
        if not engine:
            return 0

        filter_expr = f"collection eq '{self.collection_name}'"

        async with engine:
            if not await engine.index_exists():
                return 0
            return await engine.delete_by_filter(filter_expr)

    async def delete_by_file_id(self, file_id: str) -> int:
        """
        컬렉션 내 특정 file_id의 모든 청크 삭제.

        knowledge 스키마는 `file_id`를 top-level filterable 컬럼으로 선언하고
        있으므로(`schemas.py`) Azure Search/Elasticsearch/Vertex 모두 네이티브
        필터로 처리할 수 있다. pgvector만 JSONB 직접 쿼리로 최적화.
        """
        from extension_modules.search_engine.dbs.pgvector import PgVectorEngine

        engine = self._get_engine()
        if not engine:
            return 0

        async with engine:
            if not await engine.index_exists():
                return 0

            if isinstance(engine, PgVectorEngine):
                # pgvector: JSONB 직접 필터링 (가장 빠른 경로)
                pool = await engine._get_pool()
                async with pool.acquire() as conn:
                    result = await conn.execute(
                        f"""
                        DELETE FROM {engine.index_name}
                        WHERE collection = $1
                          AND metadata->>'file_id' = $2
                        """,
                        self.collection_name,
                        file_id,
                    )
                    return int(result.split()[-1])

            # 기타 엔진: 서버사이드 OData 필터로 직접 삭제
            # file_id 가 top-level 필드라 (collection, file_id) 복합 조건으로
            # 필요한 청크만 정확히 타겟팅 → 400개 동시 삭제에서도 안전
            safe_file_id = file_id.replace("'", "''")
            safe_collection = self.collection_name.replace("'", "''")
            filter_expr = (
                f"collection eq '{safe_collection}' and file_id eq '{safe_file_id}'"
            )
            return await engine.delete_by_filter(filter_expr)

    async def count(self) -> int:
        """컬렉션 내 문서 수 조회"""
        engine = self._get_engine()
        if not engine:
            return 0

        filter_expr = f"collection eq '{self.collection_name}'"

        async with engine:
            if not await engine.index_exists():
                return 0
            result = await engine.count(filter_expr)
            return result or 0

    async def has_documents(self) -> bool:
        """컬렉션에 문서가 있는지 확인 (has_collection 대체)"""
        count = await self.count()
        return count > 0

    async def query_by_metadata(
        self,
        filter_dict: Dict[str, Any],
        limit: int = 10000,
    ) -> List[DocumentItem]:
        """
        메타데이터 필터로 문서 조회 (dict 필터 지원).

        Note: Azure Search는 metadata가 JSON 문자열로 저장되어
        네이티브 필터링 불가. Python에서 post-filtering 수행.

        Args:
            filter_dict: 메타데이터 필터 (예: {"hash": "abc123"})
            limit: 최대 결과 수

        Returns:
            필터 조건에 맞는 문서 리스트
        """
        engine = self._get_engine()
        if not engine:
            return []

        filter_expr = f"collection eq '{self.collection_name}'"

        async with engine:
            if not await engine.index_exists():
                return []

            # 컬렉션 전체 조회 후 post-filtering
            docs = await engine.filter_by_metadata(filter_expr, limit)

            # Post-filter by metadata dict
            if filter_dict:
                filtered = []
                for doc in docs:
                    if doc.metadata and all(
                        doc.metadata.get(k) == v for k, v in filter_dict.items()
                    ):
                        filtered.append(doc)
                return filtered
            return docs

    async def delete_by_metadata(
        self,
        filter_dict: Dict[str, Any],
    ) -> int:
        """
        메타데이터 필터로 문서 삭제.

        Args:
            filter_dict: 삭제할 문서의 메타데이터 필터 (예: {"hash": "abc123"})

        Returns:
            삭제된 문서 수
        """
        docs = await self.query_by_metadata(filter_dict)
        if not docs:
            return 0

        engine = self._get_engine()
        if not engine:
            return 0

        ids = [doc.id for doc in docs]
        async with engine:
            return await engine.delete(ids)

    async def copy_chunks_to(
        self,
        dst_collection: str,
        src_file_id: str,
        dst_file_id: str,
    ) -> int:
        """source collection (self) 의 ``src_file_id`` chunk 를 ``dst_collection``
        에 ``dst_file_id`` 로 snapshot 복제.

        벡터/secondary_vector/content/metadata 모두 보존하고 식별자 (id,
        collection, metadata.file_id) 만 새 값으로 갱신. 임베딩 재계산
        없음 — 같은 임베딩 모델/차원 가정 (caller 가 indexed_with 마커로
        사전 검증).

        provider 분기 0 — ``SearchEngineBase.insert()`` 추상 활용.

        Args:
            dst_collection: 대상 KB id (cloned KB id)
            src_file_id: 원본 파일 id
            dst_file_id: 새로 발급된 파일 id (cloned KB 의 file row)

        Returns:
            복제된 chunk 수. source 에 chunk 가 없으면 0.
        """
        # query_by_metadata default limit 10000 은 일반 검색 용도. snapshot
        # copy 에서는 단일 진실 read 이므로 큰 KB 의 chunk 가 silent 누락되지
        # 않도록 limit 을 충분히 크게. 200K chunk = 평균 chunk_size 1500 기준
        # 약 300MB 텍스트 (단일 파일에서는 거의 도달 불가).
        docs = await self.query_by_metadata({"file_id": src_file_id}, limit=200_000)
        if not docs:
            return 0

        new_docs: List[DocumentItem] = []
        for doc in docs:
            new_meta = dict(doc.metadata or {})
            new_meta["file_id"] = dst_file_id
            new_docs.append(
                DocumentItem(
                    id=str(uuid4()),
                    content=doc.content,
                    vector=doc.vector,
                    collection=dst_collection,
                    metadata=new_meta,
                    secondary_vector=getattr(doc, "secondary_vector", None),
                )
            )

        engine = self._get_engine()
        if not engine:
            return 0
        async with engine:
            if not await self._ensure_index_exists(engine):
                raise RuntimeError(
                    f"Failed to ensure index '{self.index_config.index_name}' exists"
                )
            return await engine.insert(new_docs)

    async def update_file_filter_slots(
        self,
        file_id: str,
        slot_values: Dict[str, Any],
    ) -> int:
        """
        파일의 모든 청크에 필터 슬롯 값을 in-place 업데이트 (벡터 보존).

        Azure Search의 merge_or_upload_documents를 활용:
        벡터를 포함하지 않으면 기존 벡터가 그대로 유지됨.
        재임베딩/재인덱싱 없이 필터 슬롯 값만 업데이트.

        Args:
            file_id: 업데이트할 파일 ID
            slot_values: 업데이트할 슬롯 값 (예: {"f_str_1": "재무팀", "f_int_1": 2024})

        Returns:
            업데이트된 청크 수
        """
        docs = await self.query_by_metadata({"file_id": file_id})
        if not docs:
            return 0

        engine = self._get_engine()
        if not engine:
            return 0

        # 필터 슬롯 필드가 인덱스에 존재하는지 보장
        await self._ensure_index_exists(engine)

        normalized_slots = normalize_filter_slot_values(slot_values)

        # metadata JSON에도 slot 값을 머지하여 저장
        updated = []
        for doc in docs:
            meta = dict(doc.metadata or {})
            meta.update(normalized_slots)
            updated.append(
                DocumentItem(
                    id=doc.id,
                    content=doc.content,
                    metadata=meta,
                    vector=None,  # vector 미포함 → merge_or_upload가 기존 벡터 유지
                    collection=doc.collection,
                )
            )

        async with engine:
            return await engine.update(updated)

    async def get_all(self) -> List[DocumentItem]:
        """컬렉션의 모든 문서 조회 (get 대체)"""
        return await self.query_by_metadata({})


# =============================================================================
# Helper Functions
# =============================================================================


def normalize_filter_slot_values(slot_values: Dict[str, Any]) -> Dict[str, Any]:
    """
    필터 슬롯 값을 Azure Search 스키마에 맞게 정규화.

    - f_str_*: str (None이면 유지)
    - f_int_*: int (문자열이면 int 변환, 실패 시 None)
    - f_date_*: str (ISO 날짜)
    - f_col_*: list[str] (Collection(Edm.String) — 단일 값이면 리스트로 래핑)
    """
    normalized = {}
    for k, v in slot_values.items():
        if v is None:
            normalized[k] = v
        elif k.startswith("f_col_"):
            # Collection 필드: 반드시 리스트
            if isinstance(v, list):
                normalized[k] = [str(item) for item in v]
            else:
                normalized[k] = [str(v)]
        elif k.startswith("f_int_"):
            # 정수 필드
            try:
                normalized[k] = int(v)
            except (ValueError, TypeError):
                normalized[k] = None
        else:
            # f_str_*, f_date_* 등: 문자열
            normalized[k] = str(v) if v is not None else None
    return normalized


def convert_to_get_result(docs: List[DocumentItem]):
    """
    DocumentItem 리스트를 GetResult 형식으로 변환.

    기존 VECTOR_DB_CLIENT.get() 반환 형식과 호환성 유지를 위함.
    """
    from open_webui.retrieval.vector.main import GetResult

    if not docs:
        return GetResult(ids=[[]], documents=[[]], metadatas=[[]])

    return GetResult(
        ids=[[doc.id for doc in docs]],
        documents=[[doc.content for doc in docs]],
        metadatas=[[doc.metadata or {} for doc in docs]],
    )


async def reset_knowledge_index(app) -> bool:
    """
    Knowledge 인덱스 전체 삭제 (admin reset용).

    주의: 이 함수는 `default_knowledge` 인덱스의 모든 데이터를 삭제합니다.
    """
    config = create_knowledge_config()
    engine = get_configured_search_engine(app, config)

    if not engine:
        return False

    async with engine:
        if await engine.index_exists():
            # 인덱스 삭제 (모든 문서 삭제됨)
            await engine.delete_index()
            log.info(f"Deleted index: {config.index_name}")
    return True


async def check_duplicate_hash(
    app,
    collection_name: str,
    content_hash: str,
    exclude_file_id: Optional[str] = None,
) -> bool:
    """
    해시로 중복 체크.

    Args:
        app: FastAPI app instance
        collection_name: 컬렉션명
        content_hash: 콘텐츠 해시
        exclude_file_id: 이 file_id의 chunk는 중복 판정에서 제외
            (같은 파일의 재처리/재업로드 시 자기 자신을 중복으로 판정하지 않기 위함)

    Returns:
        True if duplicate exists, False otherwise
    """
    knowledge = SearchEngineKnowledge(app=app, collection_name=collection_name)
    docs = await knowledge.query_by_metadata({"hash": content_hash})
    if exclude_file_id and docs:
        docs = [d for d in docs if d.metadata.get("file_id") != exclude_file_id]
    return len(docs) > 0


def query_by_metadata_sync(
    app,
    collection_name: str,
    filter_dict: Dict[str, Any],
    limit: int = 10000,
) -> List[DocumentItem]:
    """
    동기 컨텍스트에서 메타데이터 필터로 문서 조회.

    ThreadPoolExecutor에서 실행되는 동기 함수용.
    """
    import asyncio

    knowledge = SearchEngineKnowledge(app=app, collection_name=collection_name)

    # asyncio.run() handles proper cleanup of async resources
    return asyncio.run(knowledge.query_by_metadata(filter_dict, limit))
