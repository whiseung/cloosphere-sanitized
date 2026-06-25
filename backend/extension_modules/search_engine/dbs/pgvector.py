"""
Search Engine - PostgreSQL pgvector 구현

하이브리드 검색 (벡터 + 텍스트)을 Reciprocal Rank Fusion (RRF)으로 병합.
선택적 Reranker를 통해 최종 결과를 의미론적으로 재정렬.
OData 필터는 filter_translator를 통해 안전한 파라미터 바인딩 SQL로 변환.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..base import SearchEngineBase
from ..filter_translator import translate_odata_to_sql
from ..models import (
    DocumentItem,
    IndexConfig,
    PgVectorConfig,
    SearchQuery,
    SearchResult,
)

if TYPE_CHECKING:
    from ..embedding import EmbeddingConfig
    from ..reranker.base import RerankerBase

log = logging.getLogger(__name__)

# RRF 상수 (표준 값)
RRF_K = 60

# 텍스트 검색 기본 가중치 (weighted RRF에서)
TEXT_WEIGHT = 0.3


class PgVectorEngine(SearchEngineBase):
    """
    PostgreSQL pgvector 기반 검색 엔진 구현.

    Args:
        config: 인덱스 설정
        engine_config: PostgreSQL 연결 설정
        embedding_config: 임베딩 설정 (선택). 설정 시 검색 시 자동 임베딩 생성.
        reranker: 리랭커 인스턴스 (선택). 설정 시 RRF 병합 후 재정렬.
    """

    def __init__(
        self,
        config: IndexConfig,
        engine_config: PgVectorConfig,
        embedding_config: Optional["EmbeddingConfig"] = None,
        reranker: Optional["RerankerBase"] = None,
    ):
        super().__init__(config, embedding_config, reranker)

        self.host = engine_config.host
        self.port = engine_config.port
        self.database = engine_config.database
        self.user = engine_config.user
        self.password = engine_config.password

        self._pool = None
        # asyncio.gather 동시 진입 시 풀 lazy-init 직렬화 (TOCTOU 중복 생성 방지)
        self._pool_lock = asyncio.Lock()

        # HNSW 인덱스: vector 타입은 최대 2000차원, halfvec은 최대 4000차원
        self._use_halfvec = config.vector_dim > 2000

    async def _get_pool(self):
        """asyncpg 연결 풀 가져오기"""
        # double-checked locking: 풀이 이미 있으면 lock 없이 즉시 반환(빠른 경로),
        # 없을 때만 lock 안에서 재확인 후 단일 코루틴만 생성한다.
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    try:
                        import asyncpg
                    except ImportError as e:
                        raise RuntimeError(
                            "asyncpg package required. Install: pip install asyncpg"
                        ) from e

                    from open_webui.env import DATABASE_SCHEMA

                    server_settings = {}
                    if DATABASE_SCHEMA:
                        server_settings["search_path"] = f"{DATABASE_SCHEMA},ag_catalog"

                    self._pool = await asyncpg.create_pool(
                        host=self.host,
                        port=self.port,
                        database=self.database,
                        user=self.user,
                        password=self.password,
                        min_size=1,
                        max_size=10,
                        server_settings=server_settings or None,
                    )
        return self._pool

    async def close(self) -> None:
        """리소스 정리"""
        if self._reranker:
            await self._reranker.close()
        if self._pool:
            await self._pool.close()
            self._pool = None

    # === 필터 변환 헬퍼 ===

    def _translate_filter(self, filter_expr: Optional[str]) -> Tuple[str, List[Any]]:
        """OData 필터를 안전한 SQL WHERE 절로 변환"""
        if not filter_expr:
            return "", []
        return translate_odata_to_sql(filter_expr, self.config.column_info)

    # === Index 관리 ===

    async def create_index(self) -> bool:
        """인덱스(테이블) 생성"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # pgvector 확장 활성화
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception as ext_err:
                # Azure PG 등에서 CREATE EXTENSION 권한이 없는 경우
                # 확장이 이미 활성화되어 있는지 확인
                has_ext = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                )
                if not has_ext:
                    raise RuntimeError(
                        f"pgvector extension is not available and cannot be created: {ext_err}"
                    ) from ext_err
                log.warning(
                    f"CREATE EXTENSION failed but pgvector already exists: {ext_err}"
                )

            # 테이블 존재 여부 확인 (현재 search_path 에 보이는 테이블만)
            exists = await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL",
                self.index_name,
            )

            if exists:
                return False

            # 테이블 생성
            await conn.execute(
                f"""
                CREATE TABLE {self.index_name} (
                    id TEXT PRIMARY KEY,
                    content TEXT,
                    metadata JSONB,
                    collection TEXT,
                    vector vector({self.config.vector_dim})
                )
                """
            )

            # 벡터 인덱스 생성 (HNSW)
            if self._use_halfvec:
                # 2000차원 초과: expression index로 halfvec 캐스팅
                await conn.execute(
                    f"""
                    CREATE INDEX idx_{self.index_name}_vector ON {self.index_name}
                    USING hnsw ((vector::halfvec({self.config.vector_dim})) halfvec_cosine_ops)
                    """
                )
            else:
                await conn.execute(
                    f"""
                    CREATE INDEX idx_{self.index_name}_vector ON {self.index_name}
                    USING hnsw (vector vector_cosine_ops)
                    """
                )

            # 텍스트 검색용 GIN 인덱스 생성
            await conn.execute(
                f"""
                CREATE INDEX idx_{self.index_name}_text ON {self.index_name}
                USING gin (to_tsvector('simple', content))
                """
            )

            # collection 필터 인덱스
            await conn.execute(
                f"""
                CREATE INDEX idx_{self.index_name}_collection
                ON {self.index_name} (collection)
                """
            )

            # JSONB 메타데이터 GIN 인덱스
            await conn.execute(
                f"""
                CREATE INDEX idx_{self.index_name}_metadata
                ON {self.index_name} USING gin (metadata jsonb_path_ops)
                """
            )

            # secondary vector (config.secondary_vector_field 있을 때만)
            if self.config.secondary_vector_field:
                await conn.execute(
                    f"""
                    ALTER TABLE {self.index_name}
                    ADD COLUMN secondary_vector vector({self.config.vector_dim})
                    """
                )
                if self._use_halfvec:
                    await conn.execute(
                        f"""
                        CREATE INDEX idx_{self.index_name}_sec_vector
                        ON {self.index_name}
                        USING hnsw ((secondary_vector::halfvec({self.config.vector_dim})) halfvec_cosine_ops)
                        """
                    )
                else:
                    await conn.execute(
                        f"""
                        CREATE INDEX idx_{self.index_name}_sec_vector
                        ON {self.index_name}
                        USING hnsw (secondary_vector vector_cosine_ops)
                        """
                    )

            vec_mode = "halfvec (expression index)" if self._use_halfvec else "vector"
            log.info(
                f"Table '{self.index_name}' created successfully. "
                f"dim={self.config.vector_dim}, index_type={vec_mode}"
            )
            return True

    async def delete_index(self) -> bool:
        """인덱스(테이블) 삭제"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(f"DROP TABLE IF EXISTS {self.index_name}")
            return "DROP TABLE" in result

    async def index_exists(self) -> bool:
        """인덱스 존재 여부"""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = $1
                )
                """,
                self.index_name,
            )

    @staticmethod
    def _vec_to_str(vec: Optional[List[float]]) -> Optional[str]:
        """Python list를 pgvector 문자열 포맷으로 변환 (asyncpg 호환)"""
        if vec is None:
            return None
        return "[" + ",".join(str(v) for v in vec) + "]"

    @staticmethod
    def _parse_vec(raw) -> Optional[List[float]]:
        """pgvector 반환값을 Python list로 변환 (asyncpg 호환)"""
        if raw is None:
            return None
        if isinstance(raw, str):
            return [float(v) for v in raw.strip("[]").split(",") if v]
        return list(raw)

    @staticmethod
    def _parse_metadata(raw) -> Optional[dict]:
        """JSONB 반환값을 dict로 변환 (asyncpg 호환)"""
        if raw is None:
            return None
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    # === CRUD ===

    async def insert(self, documents: List[DocumentItem]) -> int:
        """문서 삽입"""
        if not documents:
            return 0

        pool = await self._get_pool()
        has_secondary = self.config.secondary_vector_field is not None

        async with pool.acquire() as conn:
            count = 0
            for doc in documents:
                if has_secondary and doc.secondary_vector:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.index_name}
                            (id, content, metadata, collection, vector, secondary_vector)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        doc.id,
                        doc.content,
                        json.dumps(doc.metadata) if doc.metadata else None,
                        doc.collection,
                        self._vec_to_str(doc.vector),
                        self._vec_to_str(doc.secondary_vector),
                    )
                else:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.index_name}
                            (id, content, metadata, collection, vector)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        doc.id,
                        doc.content,
                        json.dumps(doc.metadata) if doc.metadata else None,
                        doc.collection,
                        self._vec_to_str(doc.vector),
                    )
                count += 1
            return count

    async def get(self, ids: List[str]) -> List[DocumentItem]:
        """ID로 문서 조회"""
        if not ids:
            return []

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, content, metadata, collection, vector
                FROM {self.index_name}
                WHERE id = ANY($1)
                """,
                ids,
            )

            return [
                DocumentItem(
                    id=row["id"],
                    content=row["content"],
                    metadata=self._parse_metadata(row["metadata"]),
                    collection=row["collection"],
                    vector=self._parse_vec(row["vector"]),
                )
                for row in rows
            ]

    async def update(self, documents: List[DocumentItem]) -> int:
        """문서 업데이트 (upsert)"""
        if not documents:
            return 0

        pool = await self._get_pool()
        has_secondary = self.config.secondary_vector_field is not None

        async with pool.acquire() as conn:
            count = 0
            for doc in documents:
                if has_secondary and doc.secondary_vector:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.index_name}
                            (id, content, metadata, collection, vector, secondary_vector)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            collection = EXCLUDED.collection,
                            vector = EXCLUDED.vector,
                            secondary_vector = EXCLUDED.secondary_vector
                        """,
                        doc.id,
                        doc.content,
                        json.dumps(doc.metadata) if doc.metadata else None,
                        doc.collection,
                        self._vec_to_str(doc.vector),
                        self._vec_to_str(doc.secondary_vector),
                    )
                else:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.index_name}
                            (id, content, metadata, collection, vector)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            collection = EXCLUDED.collection,
                            vector = EXCLUDED.vector
                        """,
                        doc.id,
                        doc.content,
                        json.dumps(doc.metadata) if doc.metadata else None,
                        doc.collection,
                        self._vec_to_str(doc.vector),
                    )
                count += 1
            return count

    async def delete(self, ids: List[str]) -> int:
        """문서 삭제"""
        if not ids:
            return 0

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.index_name} WHERE id = ANY($1)",
                ids,
            )
            # "DELETE N" 형식에서 삭제된 수 추출
            return int(result.split()[-1])

    async def delete_by_filter(self, filter_expr: str) -> int:
        """필터로 문서 삭제 (안전한 파라미터 바인딩)"""
        pool = await self._get_pool()
        sql_filter, params = self._translate_filter(filter_expr)
        if not sql_filter:
            return 0

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.index_name} WHERE {sql_filter}",
                *params,
            )
            return int(result.split()[-1])

    # === 검색 ===

    async def search(
        self,
        query: SearchQuery,
        query_vector: Optional[List[float]] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        RRF 하이브리드 검색 (벡터 + 텍스트) + 선택적 Reranker

        파이프라인: 벡터검색 + 텍스트검색 → RRF 병합 → Reranker → 결과

        Args:
            query: 검색 쿼리 설정
            query_vector: 사전 계산된 임베딩 벡터 (선택).
                          embedding_config 설정 시 자동 생성.
            user_id: 임베딩 사용량 추적용 사용자 ID (선택)
            chat_id: 임베딩 사용량 추적용 채팅 ID (선택)
        """
        query_text = query.query if isinstance(query.query, str) else query.query[0]

        # 벡터 확보 (외부 제공 또는 자동 생성)
        effective_vector = query_vector

        if effective_vector is None and self.embedding_config is not None:
            try:
                effective_vector = await self.generate_embedding(
                    text=query_text,
                    user_id=user_id,
                    chat_id=chat_id,
                )
                log.debug(f"Generated embedding for query: {query_text[:50]}...")
            except Exception as e:
                log.warning(f"Failed to generate embedding: {e}")
                raise RuntimeError(
                    "Hybrid search requires embedding. "
                    "Provide query_vector or set embedding_config."
                ) from e

        if effective_vector is None:
            raise RuntimeError(
                "Hybrid search requires embedding. "
                "Provide query_vector or set embedding_config."
            )

        # 리랭커가 있으면 더 많은 후보를 가져옴
        rrf_limit = query.top_k * 3 if self._reranker else query.top_k
        fetch_limit = max(query.top_k * 2, rrf_limit)

        # 벡터 검색과 텍스트 검색을 동시 실행. 각 서브검색은 풀에서 독립
        # 커넥션을 확보하므로(max_size=10) 동시 실행이 안전하고, 순차 await 로
        # 누적되던 지연을 제거한다(둘 중 느린 쪽 = 전체 latency).
        vector_results, text_results = await asyncio.gather(
            self._vector_search(
                vector=effective_vector,
                top_k=fetch_limit,
                filter_expr=query.filter,
            ),
            self._text_search(
                query_text=query_text,
                top_k=fetch_limit,
                filter_expr=query.filter,
            ),
        )

        # RRF로 결과 병합
        merged = self._rrf_merge(
            vector_results=vector_results,
            text_results=text_results,
            top_k=rrf_limit,
        )

        # 리랭킹
        if self._reranker and merged:
            reranked_results = await self._reranker.rerank(
                query=query_text,
                results=merged,
                top_k=query.top_k,
                threshold=query.reranker_threshold,
            )
            for r in reranked_results:
                r.reranked = True
            return reranked_results

        return merged[: query.top_k]

    async def _vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """벡터 전용 검색 (안전한 필터 바인딩)"""
        pool = await self._get_pool()

        sql_filter, filter_params = self._translate_filter(filter_expr)
        where_clause = f"WHERE {sql_filter}" if sql_filter else ""

        # 파라미터: $1=vector, $2=top_k, $3~=filter_params
        # filter 파라미터 인덱스를 $3부터 시작하도록 조정
        if sql_filter:
            adjusted_filter = self._adjust_param_indices(sql_filter, offset=2)
            where_clause = f"WHERE {adjusted_filter}"

        # halfvec: expression index에 맞게 캐스팅
        if self._use_halfvec:
            dim = self.config.vector_dim
            dist_expr = f"vector::halfvec({dim}) <=> $1::halfvec"
        else:
            dist_expr = "vector <=> $1::vector"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, content, metadata,
                       1 - ({dist_expr}) as score
                FROM {self.index_name}
                {where_clause}
                ORDER BY {dist_expr}
                LIMIT $2
                """,
                self._vec_to_str(vector),
                top_k,
                *filter_params,
            )

            return [
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    score=float(row["score"]),
                    metadata=self._parse_metadata(row["metadata"]),
                )
                for row in rows
            ]

    async def _secondary_vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """보조 벡터 검색 (secondary_vector 컬럼 사용)"""
        pool = await self._get_pool()

        sql_filter, filter_params = self._translate_filter(filter_expr)
        where_clause = ""
        if sql_filter:
            adjusted_filter = self._adjust_param_indices(sql_filter, offset=2)
            where_clause = f"WHERE {adjusted_filter}"

        # halfvec: expression index에 맞게 캐스팅
        if self._use_halfvec:
            dim = self.config.vector_dim
            dist_expr = f"secondary_vector::halfvec({dim}) <=> $1::halfvec"
        else:
            dist_expr = "secondary_vector <=> $1::vector"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, content, metadata,
                       1 - ({dist_expr}) as score
                FROM {self.index_name}
                {where_clause}
                ORDER BY {dist_expr}
                LIMIT $2
                """,
                self._vec_to_str(vector),
                top_k,
                *filter_params,
            )

            return [
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    score=float(row["score"]),
                    metadata=self._parse_metadata(row["metadata"]),
                )
                for row in rows
            ]

    async def _text_search(
        self,
        query_text: str,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """텍스트 전용 검색 (안전한 필터 바인딩)"""
        pool = await self._get_pool()

        # 검색어 전처리: 빈 문자열이나 특수문자만 있으면 빈 결과 반환
        clean_query = query_text.strip()
        if not clean_query:
            return []

        # 필터 조건 구성
        sql_filter, filter_params = self._translate_filter(filter_expr)
        filter_clause = ""
        if sql_filter:
            adjusted_filter = self._adjust_param_indices(sql_filter, offset=2)
            filter_clause = f"AND {adjusted_filter}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, content, metadata,
                       ts_rank(to_tsvector('simple', content),
                               plainto_tsquery('simple', $1)) as score
                FROM {self.index_name}
                WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', $1)
                {filter_clause}
                ORDER BY score DESC
                LIMIT $2
                """,
                clean_query,
                top_k,
                *filter_params,
            )

            return [
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    score=float(row["score"]),
                    metadata=self._parse_metadata(row["metadata"]),
                )
                for row in rows
            ]

    @staticmethod
    def _adjust_param_indices(sql_filter: str, offset: int) -> str:
        """
        SQL 필터의 $N 파라미터 인덱스를 offset만큼 이동.

        translate_odata_to_sql()은 $1, $2, ... 순서로 생성하지만,
        이미 $1, $2가 vector/top_k 등으로 사용 중이면 $3, $4, ...로 조정 필요.
        """
        import re

        def replace_param(match):
            idx = int(match.group(1))
            return f"${idx + offset}"

        return re.sub(r"\$(\d+)", replace_param, sql_filter)

    def _rrf_merge(
        self,
        vector_results: List[SearchResult],
        text_results: List[SearchResult],
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        Reciprocal Rank Fusion으로 두 검색 결과 병합

        RRF 공식: score = 1/(k + rank_vector) + 1/(k + rank_text)
        k = 60 (표준 상수)
        """
        # ID별 문서 정보 및 순위 수집
        doc_info: Dict[str, SearchResult] = {}
        vector_ranks: Dict[str, int] = {}
        text_ranks: Dict[str, int] = {}

        # 벡터 검색 결과에서 순위 및 문서 정보 추출
        for rank, result in enumerate(vector_results, start=1):
            doc_info[result.id] = result
            vector_ranks[result.id] = rank

        # 텍스트 검색 결과에서 순위 및 문서 정보 추출
        for rank, result in enumerate(text_results, start=1):
            if result.id not in doc_info:
                doc_info[result.id] = result
            text_ranks[result.id] = rank

        # RRF 점수 계산
        rrf_scores: Dict[str, float] = {}
        for doc_id in doc_info:
            score = 0.0
            if doc_id in vector_ranks:
                score += 1.0 / (RRF_K + vector_ranks[doc_id])
            if doc_id in text_ranks:
                score += 1.0 / (RRF_K + text_ranks[doc_id])
            rrf_scores[doc_id] = score

        # RRF 점수를 [0, 1] 범위로 정규화
        # 최대 RRF 점수: 양쪽 모두 rank 1일 때 = 2/(RRF_K+1)
        max_rrf = 2.0 / (RRF_K + 1)

        # RRF 점수 기준 정렬 및 상위 top_k 반환
        sorted_ids = sorted(
            rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True
        )

        return [
            SearchResult(
                id=doc_id,
                content=doc_info[doc_id].content,
                score=min(rrf_scores[doc_id] / max_rrf, 1.0),
                metadata=doc_info[doc_id].metadata,
            )
            for doc_id in sorted_ids[:top_k]
        ]

    def _weighted_rrf_merge(
        self,
        primary_results: List[SearchResult],
        secondary_results: List[SearchResult],
        text_results: List[SearchResult],
        primary_weight: float,
        secondary_weight: float,
        top_k: int = 10,
    ) -> List[SearchResult]:
        """
        가중 Reciprocal Rank Fusion으로 세 검색 결과 병합.

        score = w_primary * 1/(k+rank_p) + w_secondary * 1/(k+rank_s) + w_text * 1/(k+rank_t)
        """
        doc_info: Dict[str, SearchResult] = {}
        primary_ranks: Dict[str, int] = {}
        secondary_ranks: Dict[str, int] = {}
        text_ranks: Dict[str, int] = {}

        for rank, result in enumerate(primary_results, start=1):
            doc_info[result.id] = result
            primary_ranks[result.id] = rank

        for rank, result in enumerate(secondary_results, start=1):
            if result.id not in doc_info:
                doc_info[result.id] = result
            secondary_ranks[result.id] = rank

        for rank, result in enumerate(text_results, start=1):
            if result.id not in doc_info:
                doc_info[result.id] = result
            text_ranks[result.id] = rank

        rrf_scores: Dict[str, float] = {}
        for doc_id in doc_info:
            score = 0.0
            if doc_id in primary_ranks:
                score += primary_weight * (1.0 / (RRF_K + primary_ranks[doc_id]))
            if doc_id in secondary_ranks:
                score += secondary_weight * (1.0 / (RRF_K + secondary_ranks[doc_id]))
            if doc_id in text_ranks:
                score += TEXT_WEIGHT * (1.0 / (RRF_K + text_ranks[doc_id]))
            rrf_scores[doc_id] = score

        # 가중 RRF 점수를 [0, 1] 범위로 정규화
        # 최대: 모든 소스 rank 1일 때 = (w_p + w_s + w_t) / (RRF_K+1)
        max_rrf = (primary_weight + secondary_weight + TEXT_WEIGHT) / (RRF_K + 1)

        sorted_ids = sorted(
            rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True
        )

        return [
            SearchResult(
                id=doc_id,
                content=doc_info[doc_id].content,
                score=min(rrf_scores[doc_id] / max_rrf, 1.0) if max_rrf > 0 else 0.0,
                metadata=doc_info[doc_id].metadata,
            )
            for doc_id in sorted_ids[:top_k]
        ]

    async def vector_search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """벡터 전용 검색 (공개 인터페이스)"""
        return await self._vector_search(vector, top_k, filter_expr)

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
        Multi-vector 검색 (기본 벡터 + 보조 벡터 + 텍스트 가중 앙상블).

        파이프라인:
        1. primary vector 검색
        2. secondary vector 검색 (secondary_vector 컬럼)
        3. 텍스트 검색
        4. Weighted RRF 병합
        5. 리랭킹 (선택)
        """
        # secondary_vector가 없거나 secondary_vector 컬럼이 없으면 기본 검색
        if not secondary_vector or not self.config.secondary_vector_field:
            return await self.hybrid_search(
                text=text,
                vector=vector,
                top_k=top_k,
                filter_expr=filter_expr,
                user_id=user_id,
                chat_id=chat_id,
            )

        # 벡터 확보
        if vector is None and self.embedding_config is not None:
            vector = await self.generate_embedding(
                text=text, user_id=user_id, chat_id=chat_id
            )

        if vector is None:
            raise RuntimeError(
                "Multi-vector search requires embedding. "
                "Provide vector or set embedding_config."
            )

        # 리랭커가 있으면 더 많은 후보를 가져옴
        rrf_limit = top_k * 3 if self._reranker else top_k
        fetch_limit = max(top_k * 2, rrf_limit)

        # 3-way 검색을 동시 실행 (각자 풀에서 독립 커넥션 확보 — max_size=10).
        primary_results, secondary_results, text_results = await asyncio.gather(
            self._vector_search(
                vector=vector, top_k=fetch_limit, filter_expr=filter_expr
            ),
            self._secondary_vector_search(
                vector=secondary_vector, top_k=fetch_limit, filter_expr=filter_expr
            ),
            self._text_search(
                query_text=text, top_k=fetch_limit, filter_expr=filter_expr
            ),
        )

        # Weighted RRF 병합
        merged = self._weighted_rrf_merge(
            primary_results=primary_results,
            secondary_results=secondary_results,
            text_results=text_results,
            primary_weight=primary_weight,
            secondary_weight=secondary_weight,
            top_k=rrf_limit,
        )

        # 리랭킹
        if self._reranker and merged:
            reranked_results = await self._reranker.rerank(
                query=text, results=merged, top_k=top_k, threshold=reranker_threshold
            )
            for r in reranked_results:
                r.reranked = True
            return reranked_results

        return merged[:top_k]

    # === 필터링 ===

    async def filter_by_metadata(
        self,
        filter_expr: str,
        limit: int = 100,
    ) -> List[DocumentItem]:
        """메타데이터 기반 필터링 (안전한 파라미터 바인딩)"""
        pool = await self._get_pool()

        sql_filter, filter_params = self._translate_filter(filter_expr)
        if not sql_filter:
            return []

        # $1=limit이므로 filter는 $2부터
        adjusted_filter = self._adjust_param_indices(sql_filter, offset=1)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, content, metadata, collection
                FROM {self.index_name}
                WHERE {adjusted_filter}
                LIMIT $1
                """,
                limit,
                *filter_params,
            )

            return [
                DocumentItem(
                    id=row["id"],
                    content=row["content"],
                    metadata=self._parse_metadata(row["metadata"]),
                    collection=row["collection"],
                )
                for row in rows
            ]

    async def count(self, filter_expr: Optional[str] = None) -> int:
        """문서 수 조회 (안전한 파라미터 바인딩)"""
        pool = await self._get_pool()

        sql_filter, filter_params = self._translate_filter(filter_expr)
        where_clause = f"WHERE {sql_filter}" if sql_filter else ""

        async with pool.acquire() as conn:
            return await conn.fetchval(
                f"SELECT COUNT(*) FROM {self.index_name} {where_clause}",
                *filter_params,
            )
