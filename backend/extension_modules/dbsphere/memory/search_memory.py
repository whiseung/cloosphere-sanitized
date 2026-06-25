"""
DbSphere V2 Memory using search_engine module.

This implementation uses the unified search_engine interface for storing
and retrieving various types of context for Vanna-style SQL generation learning:
- SQL Memory: Question-SQL pairs for few-shot learning
- DDL Schema: Table/column definitions with LLM-generated descriptions
- Documentation: Business rules, terms, and context
- SQL Example: Annotated SQL examples with use cases
"""

import asyncio
import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from extension_modules.search_engine import (
    ColumnInfo,
    DocumentItem,
    IndexConfig,
    SearchEngineBase,
    SearchResult,
    create_dbsphere_memory_config,
    get_configured_search_engine,
)
from open_webui.env import SRC_LOG_LEVELS

from .models import (
    ColumnDetail,
    DDLMemory,
    DDLMemorySearchResult,
    DocumentationMemory,
    DocumentationSearchResult,
    MemoryType,
    SqlExampleMemory,
    SqlExampleSearchResult,
    SqlMemory,
    SqlMemorySearchResult,
    UnifiedSearchResult,
)

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MODELS"])

# DDL_SCHEMA full-reload fetch cap. The join_graph full-S recompute reloads the
# entire DDL_SCHEMA set in one shot; the previous cap of 100 silently truncated
# large schemas. 1000 is honored by the backends (other read paths already use
# 1000). >1000 tables need pagination — tracked as a follow-up (TODO).
DDL_SCHEMA_FETCH_LIMIT = 1000

# Legacy (pre-Option-C) relationship DOCUMENTATION doc signature. Relationships
# now live in dbsphere.data["join_graph"]; these identify the old doc for the E1
# purge + E2 retrieve-stage exclusion. Neither 'source' (dropped on save) nor the
# title is an OData-filterable column, so matching is post-fetch.
RELATIONSHIP_DOC_ID_SUFFIX = "__relationship_graph"
RELATIONSHIP_DOC_TITLE = "Database Table Relationships and JOIN Guide"

# Azure/OpenAI embedding models cap input at 8192 tokens. We cannot count
# tokens precisely without the model tokenizer, and Korean text is token-dense
# (a single Hangul syllable can be 1-3 tokens), so we truncate by characters
# with a generous cap and fall back to an aggressive retry if the provider
# still rejects the input for length.
_EMBEDDING_MAX_CHARS = 8000
_EMBEDDING_FALLBACK_CHARS = 3500


def _odata_quote(value: str) -> str:
    """OData 문자열 리터럴 값 이스케이프.

    작은따옴표를 두 개로 치환(''-escape)하여 LLM/사용자가 제어하는 값(table_name,
    doc_type, use_case 등)이 필터 구조를 탈출해 collection 격리를 우회하는 것을
    차단한다. OData 토크나이저는 '' 를 리터럴 따옴표로 해석하므로, doubling 으로
    paren-breakout / top-level OR 주입(cross-collection 누출)이 무력화된다.
    """
    return value.replace("'", "''")


def create_dbsphere_memory_index_config(
    vector_dim: int = 3072,
) -> IndexConfig:
    """
    Create index configuration for DbSphere memory.

    Uses fixed index name 'dbsphere_memory'.
    Filter by collection field (= dbsphere_id) to separate data per database.

    Args:
        vector_dim: Vector dimension for embeddings

    Returns:
        IndexConfig for DbSphere memory
    """
    return create_dbsphere_memory_config(
        vector_dim=vector_dim,
    )


# Backward compatibility aliases
SQL_MEMORY_COLUMNS: List[ColumnInfo] = [
    ColumnInfo(name="sql_query", type="string"),
    ColumnInfo(name="success", type="boolean"),
    ColumnInfo(name="user_id", type="string"),
    ColumnInfo(name="chat_id", type="string"),
]


def create_sql_memory_config(
    vector_dim: int = 3072,
) -> IndexConfig:
    """
    Create index configuration for SQL memory (backward compatible).

    Args:
        vector_dim: Vector dimension for embeddings

    Returns:
        IndexConfig for SQL memory
    """
    return create_dbsphere_memory_index_config(vector_dim)


# ---------------------------------------------------------------------------
# SQL memory dedup / tenant-isolation helpers (pure functions — unit-testable)
# ---------------------------------------------------------------------------
# 멀티테넌시: schema-extraction 으로 생성된 row 는 공유 스키마 지식이므로 격리에서
# 제외하고 전역 가시로 둔다. save 메타의 source 필드로 식별한다.
SCHEMA_EXTRACTION_SOURCE = "schema_extraction"


def _normalize_question(question: str) -> str:
    """dedup 키용 경량 정규화 — lowercase + 공백 collapse.

    의도적으로 보수적: casing/공백만 통합하고 의미는 바꾸지 않는다(paraphrase 는
    별개 질문으로 보존). 격리(#1)와 무관, dedup(#2) 전용.
    """
    return " ".join((question or "").lower().split())


def compute_sql_memory_dedup_key(question: str, sql: str) -> str:
    """SQL memory dedup identity = (정규화 질문, 정확한 SQL) 의 sha256.

    같은 질문(casing/공백 무시) + 같은 SQL 이면 동일 row 로 collapse(저장 upsert /
    조회 collapse). SQL 이 다르면 별개 variant 로 보존(결정 D4: question+sql).
    """
    basis = f"{_normalize_question(question)}\n{(sql or '').strip()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# 결정적 문서 id 용 고정 네임스페이스. dedup_key 와 결합해 같은 (dbsphere, 질문, SQL)
# 저장이 동일 id 로 upsert 되게 한다(#2 dedup, save-time).
_SQL_MEMORY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "dbsphere-sql-memory.cloosphere")


def _sql_memory_doc_id(dbsphere_id: str, dedup_key: str) -> str:
    """결정적 문서 id = uuid5(namespace, dbsphere_id:dedup_key).

    같은 (dbsphere, 정규화 질문, SQL) 저장은 같은 id → engine.update 로 upsert 되어
    중복 row 가 쌓이지 않는다(#231 schema-extract 멱등 패턴과 동일).
    """
    return str(uuid.uuid5(_SQL_MEMORY_NAMESPACE, f"{dbsphere_id}:{dedup_key}"))


# =========================================================================
# DDL schema memory rendering (shared by save + edit re-embed)
# =========================================================================
# DDL `content` (rerank text) and `embedding_text` (meaning-focused vector
# input) are built from the same fields. Extracting one builder keeps create
# (save_ddl_memory) and edit (update_memory) from drifting — an edit must
# reconstruct exactly what create would have produced, else the stored vector
# stops matching the metadata.


def _col_attr(col: Any, field: str) -> Any:
    """Read a column attribute from either a ColumnDetail or a plain dict."""
    if isinstance(col, ColumnDetail):
        return getattr(col, field, None)
    if isinstance(col, dict):
        return col.get(field)
    return None


def render_ddl_memory(
    table_name: str,
    table_description: Optional[str],
    columns: Optional[List[Union[ColumnDetail, Dict[str, Any]]]],
    relationships: Optional[List[str]],
) -> tuple[str, str]:
    """Build ``(content, embedding_text)`` for a DDL_SCHEMA memory.

    ``columns`` accepts ColumnDetail objects or dicts (only name/description are
    read). ``content`` omits description-less columns; ``embedding_text``
    includes them as a bare name. Output is byte-identical to the legacy inline
    builder so re-embedding an edit matches the original creation.
    """
    cols = columns or []

    content_parts = [f"Table: {table_name}"]
    if table_description:
        content_parts.append(f"Description: {table_description}")
    col_descriptions = []
    for c in cols:
        desc = _col_attr(c, "description")
        if desc:
            col_descriptions.append(f"{_col_attr(c, 'name')}: {desc}")
    if col_descriptions:
        content_parts.append("Columns: " + "; ".join(col_descriptions))
    if relationships:
        content_parts.append(f"Related tables: {', '.join(relationships)}")
    content = "\n".join(content_parts)

    embedding_parts = [table_name]
    if table_description:
        embedding_parts.append(table_description)
    for c in cols:
        desc = _col_attr(c, "description")
        name = _col_attr(c, "name")
        embedding_parts.append(f"{name}: {desc}" if desc else name)
    if relationships:
        embedding_parts.append(f"Related: {' '.join(relationships)}")
    embedding_text = "\n".join(embedding_parts)

    return content, embedding_text


def render_documentation_memory(
    title: Optional[str],
    content: str,
    related_tables: Optional[List[str]],
    related_columns: Optional[List[str]],
) -> tuple[str, str]:
    """Build ``(rich_content, embedding_text)`` for a DOCUMENTATION memory.

    ``rich_content`` 는 인덱스 ``content`` 필드(rerank/검색 표층)이고 ``embedding_text``
    는 벡터 입력이다. save 와 edit(update_memory)이 같은 빌더를 쓰게 해, 편집 시
    content 가 clean 본문으로 덮여 rich_content 와 임베딩이 드리프트하는 것을 막는다.
    표시용 clean 본문은 metadata['doc_content'] 에 별도 보관한다(여기 출력 아님).
    """
    content_parts: List[str] = []
    if title:
        content_parts.append(f"Title: {title}")
    content_parts.append(content)
    if related_tables:
        content_parts.append(f"Related tables: {', '.join(related_tables)}")
    if related_columns:
        content_parts.append(f"Related columns: {', '.join(related_columns)}")
    rich_content = "\n".join(content_parts)

    embedding_parts: List[str] = []
    if title:
        embedding_parts.append(title)
    embedding_parts.append(content)
    if related_tables:
        embedding_parts.append(f"Tables: {' '.join(related_tables)}")
    embedding_text = "\n".join(embedding_parts)

    return rich_content, embedding_text


def _safe_json(raw: Any) -> Any:
    """json.loads that never raises: None/empty/malformed -> None.

    Already-parsed list/dict passes through (callers store JSON strings, but a
    future caller may hand a parsed value). Guards relationships_json=None —
    json.loads(None) would otherwise raise and 404 every relationship-less edit.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def merge_columns_by_name(
    stored: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Field-level merge of column dicts keyed by ``name``.

    The FE edit payload re-sends ``column_info_json`` for every edit but drops
    ``foreign_column``/``is_nullable``/``default_value`` — fields the join-graph
    consumes (get_table_schemas -> ColumnDetail). Merging ``incoming`` onto the
    full-fidelity ``stored`` doc preserves those while applying edited fields.
    New columns are appended; stored columns absent from ``incoming`` are kept.
    Empty ``incoming`` (e.g. FE JSON.parse failure -> []) returns ``stored``
    unchanged to prevent a wipe.
    """
    if not incoming:
        return [dict(c) for c in stored]

    stored_by_name = {
        c["name"]: c
        for c in stored
        if isinstance(c, dict) and c.get("name") is not None
    }

    merged = []
    seen = set()
    for c in incoming:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        base = dict(stored_by_name.get(name, {}))
        base.update(c)  # incoming's provided fields win; stored-only fields kept
        merged.append(base)
        if name is not None:
            seen.add(name)

    for name, c in stored_by_name.items():
        if name not in seen:
            merged.append(dict(c))

    return merged


# 멀티테넌시(#1): 공유 dbsphere 에서 SQL memory 는 작성자(user_id)에게만 보인다.
# 조회 필터는 OData 가 아니라 post-fetch(이 모듈) — search engine filter 층에 IN/ne
# 연산자가 없고, #231 이 같은 인덱스에서 source 류 필드는 post-fetch 로 처리하기로
# 확립했기 때문. over-fetch 후 격리/collapse 한다.
_SQL_MEMORY_OVERFETCH_FACTOR = 20
_SQL_MEMORY_MAX_FETCH = 100  # SearchQuery.top_k 상한(le=100)
_SQL_MEMORY_COUNT_CAP = 1000  # 격리된 count 의 정확 상한(초과 시 근사)


def _sql_memory_row_visible(
    metadata: Dict[str, Any], *, requester_user_id: str, is_admin: bool
) -> bool:
    """단일 sql_memory row 가 requester 에게 보이는가.

    admin 은 전체. 그 외에는 본인 작성(user_id 일치) 또는 schema-extraction 으로
    생성된 공유 스키마 지식(source)만. legacy(user_id 없음) 개인 row 는 비-admin 에
    숨김(fail-closed).
    """
    if is_admin:
        return True
    return (
        metadata.get("user_id") == requester_user_id
        or metadata.get("source") == SCHEMA_EXTRACTION_SOURCE
    )


def _apply_sql_memory_policy(
    results: List["SearchResult"],
    *,
    requester_user_id: str,
    is_admin: bool,
    similarity_threshold: float,
    limit: int,
) -> List["SqlMemorySearchResult"]:
    """엔진이 반환한 raw SQL_MEMORY 결과에 post-fetch 정책을 적용한다.

    순서: tenant 격리(#1) → success 필터(few-shot 오염 방지) → similarity 컷 →
    dedup collapse(#2, dedup_key·최고 score 유지) → limit. 순수 함수(단위테스트 대상).
    """
    seen_keys: set = set()
    output: List["SqlMemorySearchResult"] = []
    for result in results:
        metadata = result.metadata or {}

        if not _sql_memory_row_visible(
            metadata, requester_user_id=requester_user_id, is_admin=is_admin
        ):
            continue

        # 실패 SQL 은 few-shot 예시에서 제외 (None/legacy = 성공 취급).
        if metadata.get("success", True) is False:
            continue

        if result.score < similarity_threshold:
            continue

        # dedup collapse (#2): dedup_key 동일 → 1개만 유지 (최초=최고 score).
        # legacy row(dedup_key 없음)는 question+sql 로 재계산.
        key = metadata.get("dedup_key") or compute_sql_memory_dedup_key(
            result.content, metadata.get("sql_query", "")
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)

        memory = SqlMemory(
            memory_id=result.id,
            question=result.content,
            sql=metadata.get("sql_query", ""),
            timestamp=metadata.get("created_at"),
            success=metadata.get("success", True),
            metadata=metadata,
        )
        output.append(
            SqlMemorySearchResult(
                memory=memory,
                similarity_score=result.score,
                rank=len(output) + 1,
            )
        )
        if len(output) >= limit:
            break
    return output


class SearchEngineDbSphereMemory:
    """
    DbSphere Memory Service using search_engine interface.

    Supports multiple memory types for Vanna-style learning:
    - SQL Memory: Question-SQL pairs
    - DDL Schema: Table/column definitions
    - Documentation: Business rules and context
    - SQL Example: Annotated SQL examples
    """

    def __init__(
        self,
        app,
        dbsphere_id: str,
        user_id: str = "",
        embedding_func: Optional[Callable[[str], List[float]]] = None,
        vector_dim: int = 3072,
    ):
        """
        Initialize DbSphere Memory.

        Args:
            app: FastAPI application instance
            dbsphere_id: DbSphere resource ID (stored in collection field for filtering)
            user_id: User ID (optional, for metadata)
            embedding_func: Async function to generate embeddings.
                           Should handle usage tracking and tracing internally.
            vector_dim: Vector dimension
        """
        self.app = app
        self.dbsphere_id = dbsphere_id
        self.user_id = user_id
        self.embedding_func = embedding_func
        self.vector_dim = vector_dim
        # admin 여부는 1회 resolve 후 캐시 (SQL memory tenant 격리 bypass 용).
        self._is_admin_cache: Optional[bool] = None

        # Create index config (fixed index name: dbsphere_memory)
        self.index_config = create_dbsphere_memory_index_config(
            vector_dim=vector_dim,
        )

        self._engine: Optional[SearchEngineBase] = None
        self._session_active: bool = False

    def _get_engine(self) -> Optional[SearchEngineBase]:
        """Get search engine instance."""
        if self._engine is None:
            self._engine = get_configured_search_engine(self.app, self.index_config)
        return self._engine

    @asynccontextmanager
    async def session(self):
        """Hold the engine open across many save/search calls.

        Without this, every save_*/search_* call wraps `async with engine:` which
        on exit calls `engine.close()` and tears down the underlying client/pool.
        Because `_get_engine()` caches a single engine on the instance, parallel
        callers (e.g. schema extraction processing N tables concurrently) all
        share that engine — and the first one to finish closes the client out
        from under the others, causing silent failures.

        Reentrant: nested `session()` blocks reuse the outer session.
        """
        engine = self._get_engine()
        if engine is None or self._session_active:
            yield
            return
        self._session_active = True
        try:
            async with engine:
                yield
        finally:
            self._session_active = False

    @asynccontextmanager
    async def _engine_ctx(self, engine: SearchEngineBase):
        """Per-call engine context — no-op when inside an active session."""
        if self._session_active:
            yield
        else:
            async with engine:
                yield

    async def _create_embedding(self, text: str) -> Optional[List[float]]:
        """Create embedding for text.

        Note: Usage tracking and tracing are handled by the embedding_func
        (e.g., generate_embedding_async) to avoid duplication.
        """
        if not self.embedding_func:
            return None

        truncated = text[:_EMBEDDING_MAX_CHARS]
        try:
            return await self.embedding_func(truncated)
        except Exception as e:
            msg = str(e).lower()
            is_length_error = (
                "8192" in msg
                or "maximum" in msg
                or "too long" in msg
                or "context length" in msg
            )
            if is_length_error and len(truncated) > _EMBEDDING_FALLBACK_CHARS:
                logger.warning(
                    "Embedding input too long (%d chars), retrying truncated to %d",
                    len(text),
                    _EMBEDDING_FALLBACK_CHARS,
                )
                try:
                    return await self.embedding_func(text[:_EMBEDDING_FALLBACK_CHARS])
                except Exception as e2:
                    logger.warning(f"Failed to create embedding after truncation: {e2}")
                    return None
            logger.warning(f"Failed to create embedding: {e}")
            return None

    async def _ensure_index_exists(self, engine: SearchEngineBase) -> bool:
        """Ensure the index exists, create if needed."""
        try:
            if not await engine.index_exists():
                await engine.create_index()
            return True
        except Exception as e:
            logger.error(f"Failed to ensure index exists: {e}")
            return False

    # =========================================================================
    # SQL Memory (existing functionality, maintained for backward compatibility)
    # =========================================================================

    async def save_sql_memory(
        self,
        question: str,
        sql: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SqlMemory]:
        """
        Save a successful SQL query for future retrieval.

        Args:
            question: The natural language question
            sql: The SQL query that was generated
            success: Whether the query executed successfully
            metadata: Additional metadata

        Returns:
            The created SqlMemory object or None if save failed
        """
        engine = self._get_engine()
        if not engine:
            logger.warning("Search engine not configured, skipping memory save")
            return None

        max_retries = 3
        # #2 dedup: (정규화 질문, SQL) 기반 결정적 id 로 upsert — 중복 row 누적 방지.
        dedup_key = compute_sql_memory_dedup_key(question, sql)
        memory_id = _sql_memory_doc_id(self.dbsphere_id, dedup_key)
        for attempt in range(max_retries):
            try:
                async with self._engine_ctx(engine):
                    await self._ensure_index_exists(engine)

                    # embed short-circuit: 동일 (question, sql) 가 이미 있으면 재임베딩·
                    # 재저장 스킵 (5개 producer 가 같은 성공쿼리를 반복 저장하는 흔한 경우).
                    # best-effort 최적화 — 동시 저장 race 시 양쪽 다 miss 해 중복 embed 가
                    # 일어날 수 있으나, 결정적 id + engine.update(upsert)라 결과는 단일 row
                    # 멱등(데이터 정합성은 보장). 정합성 보증이 아니라 비용 절감용.
                    existing = await engine.get([memory_id])
                    if existing:
                        ex_md = existing[0].metadata or {}
                        if (
                            existing[0].content == question
                            and ex_md.get("sql_query") == sql
                        ):
                            return SqlMemory(
                                memory_id=memory_id,
                                question=question,
                                sql=sql,
                                timestamp=ex_md.get("created_at"),
                                success=success,
                                metadata=metadata or {},
                            )

                    timestamp = datetime.now(timezone.utc).isoformat()

                    # Create embedding for the combined question + SQL
                    embedding_text = f"{question}\n{sql}"
                    vector = await self._create_embedding(embedding_text)

                    document = DocumentItem(
                        id=memory_id,
                        content=question,
                        vector=vector,
                        collection=self.dbsphere_id,
                        metadata={
                            "entity_type": MemoryType.SQL_MEMORY.value,
                            "sql_query": sql,
                            "table_name": metadata.get("table_name")
                            if metadata
                            else None,
                            "user_id": metadata.get("user_id") if metadata else None,
                            "chat_id": metadata.get("chat_id") if metadata else None,
                            # C1 meta seam: post-fetch 격리(#1)·dedup(#2)·readback 회귀 수정.
                            "source": metadata.get("source") if metadata else None,
                            # 생성자 구분 배지용 (source 와 별개 additive 필드).
                            "origin": metadata.get("origin") if metadata else None,
                            "success": success,
                            "dedup_key": dedup_key,
                            "created_at": timestamp,
                        },
                    )
                    # 결정적 id → upsert(merge_or_upload[azure] / ON CONFLICT[pg]).
                    await engine.update([document])

                return SqlMemory(
                    memory_id=memory_id,
                    question=question,
                    sql=sql,
                    timestamp=timestamp,
                    success=success,
                    metadata=metadata or {},
                )

            except Exception as e:
                if attempt < max_retries - 1 and (
                    "disconnected" in str(e).lower()
                    or "closed" in str(e).lower()
                    or "connection" in str(e).lower()
                ):
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(
                        f"save_sql_memory connection error, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Failed to save SQL memory: {e}")
                return None
        return None

    def _requester_is_admin(self) -> bool:
        """self.user_id 가 admin 인지 1회 resolve 후 캐시.

        admin 은 SQL memory tenant 격리를 bypass(전체 조회)한다. 조회 실패 시
        fail-closed(격리 적용)로 보수적 처리. unified_agent 의 glossary 재필터 패턴과
        동일하게 Users 테이블에서 role 을 확인한다.
        """
        if self._is_admin_cache is None:
            if not self.user_id:
                self._is_admin_cache = False
            else:
                try:
                    from open_webui.models.users import Users

                    user = Users.get_user_by_id(self.user_id)
                    self._is_admin_cache = bool(user and user.role == "admin")
                except Exception as e:
                    logger.warning("admin 확인 실패, 격리 적용(fail-closed): %s", e)
                    self._is_admin_cache = False
        return self._is_admin_cache

    async def search_similar_queries(
        self,
        question: str,
        limit: int = 5,
        similarity_threshold: float = 0.5,
        question_vector: Optional[List[float]] = None,
    ) -> List[SqlMemorySearchResult]:
        """
        Search for similar past queries.

        Args:
            question: The current question to find similar queries for
            limit: Maximum number of results to return
            similarity_threshold: Minimum similarity score (0-1, normalized)
            question_vector: Pre-computed embedding vector (avoids redundant embedding)

        Returns:
            List of similar SQL memories with scores
        """
        engine = self._get_engine()
        if not engine:
            logger.warning("Search engine not configured, skipping memory search")
            return []

        try:
            # Use pre-computed vector or create new one
            vector = question_vector or await self._create_embedding(question)
            if not vector:
                logger.warning("Failed to create embedding for search")
                return []

            # OData 필터는 collection + entity_type 까지만.
            # tenant 격리(#1)·success·dedup(#2)은 _apply_sql_memory_policy 에서 post-fetch.
            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{MemoryType.SQL_MEMORY.value}'"
            )

            # 격리/dedup 으로 후보가 탈락하므로 over-fetch 후 limit 으로 자른다.
            fetch_k = min(
                max(limit, 1) * _SQL_MEMORY_OVERFETCH_FACTOR, _SQL_MEMORY_MAX_FETCH
            )

            async with self._engine_ctx(engine):
                # Return empty if index doesn't exist
                if not await engine.index_exists():
                    return []
                # Use hybrid search (vector + keyword) for better recall
                results = await engine.hybrid_search(
                    text=question,
                    vector=vector,
                    top_k=fetch_k,
                    filter_expr=filter_expr,
                )

            return _apply_sql_memory_policy(
                results,
                requester_user_id=self.user_id,
                is_admin=self._requester_is_admin(),
                similarity_threshold=similarity_threshold,
                limit=limit,
            )

        except Exception as e:
            logger.error(f"Failed to search SQL memory: {e}")
            return []

    async def get_recent_memories(self, limit: int = 10) -> List[SqlMemory]:
        """Get recently saved SQL memories."""
        engine = self._get_engine()
        if not engine:
            return []

        try:
            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{MemoryType.SQL_MEMORY.value}'"
            )

            # 격리로 일부 탈락 → over-fetch 후 limit.
            fetch_k = min(
                max(limit, 1) * _SQL_MEMORY_OVERFETCH_FACTOR, _SQL_MEMORY_MAX_FETCH
            )

            async with self._engine_ctx(engine):
                # Return empty if index doesn't exist
                if not await engine.index_exists():
                    return []
                results = await engine.filter_by_metadata(
                    filter_expr=filter_expr,
                    limit=fetch_k,
                )

            is_admin = self._requester_is_admin()
            memories = []
            for doc in results:
                metadata = doc.metadata or {}
                if not _sql_memory_row_visible(
                    metadata, requester_user_id=self.user_id, is_admin=is_admin
                ):
                    continue
                memories.append(
                    SqlMemory(
                        memory_id=doc.id,
                        question=doc.content,
                        sql=metadata.get("sql_query", ""),
                        timestamp=metadata.get("created_at"),
                        success=metadata.get("success", True),
                        metadata=metadata,
                    )
                )
                if len(memories) >= limit:
                    break

            return memories

        except Exception as e:
            logger.error(f"Failed to get recent memories: {e}")
            return []

    # =========================================================================
    # DDL Schema Memory (new)
    # =========================================================================

    async def save_ddl_memory(
        self,
        ddl_statement: str,
        table_name: str,
        columns: Optional[List[Union[ColumnDetail, Dict]]] = None,
        schema_name: Optional[str] = None,
        table_description: Optional[str] = None,
        relationships: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[DDLMemory]:
        """
        Save DDL/Schema information for a table.

        Args:
            ddl_statement: The DDL CREATE TABLE statement
            table_name: Name of the table
            columns: List of column details
            schema_name: Database schema name
            table_description: LLM-generated description of the table
            relationships: List of related table names
            metadata: Additional metadata

        Returns:
            The created DDLMemory object or None if save failed
        """
        engine = self._get_engine()
        if not engine:
            logger.warning("Search engine not configured, skipping DDL memory save")
            return None

        max_retries = 3
        for attempt in range(max_retries):
            try:
                memory_id = str(uuid.uuid4())
                timestamp = datetime.now(timezone.utc).isoformat()

                # Convert ColumnDetail objects to dicts
                column_dicts = []
                column_details = []
                if columns:
                    for col in columns:
                        if isinstance(col, ColumnDetail):
                            column_dicts.append(asdict(col))
                            column_details.append(col)
                        else:
                            column_dicts.append(col)
                            column_details.append(ColumnDetail(**col))

                # Shared builder: content (rerank text) + embedding_text
                # (vector input). Extracted so update_memory's edit path
                # reconstructs an identical content/embedding (no drift).
                content, embedding_text = render_ddl_memory(
                    table_name, table_description, column_details, relationships
                )

                vector = await self._create_embedding(embedding_text)

                document = DocumentItem(
                    id=memory_id,
                    content=content,
                    vector=vector,
                    collection=self.dbsphere_id,
                    metadata={
                        "entity_type": MemoryType.DDL_SCHEMA.value,
                        "table_name": table_name,
                        "schema_name": schema_name,
                        "ddl_statement": ddl_statement,
                        "column_info_json": json.dumps(column_dicts)
                        if column_dicts
                        else None,
                        "table_description": table_description,
                        "relationships_json": json.dumps(relationships)
                        if relationships
                        else None,
                        "created_at": timestamp,
                    },
                )

                async with self._engine_ctx(engine):
                    await self._ensure_index_exists(engine)
                    await engine.insert([document])

                return DDLMemory(
                    memory_id=memory_id,
                    ddl_statement=ddl_statement,
                    table_name=table_name,
                    schema_name=schema_name,
                    columns=column_details,
                    table_description=table_description,
                    relationships=relationships or [],
                    timestamp=timestamp,
                    metadata=metadata or {},
                )

            except Exception as e:
                if attempt < max_retries - 1 and (
                    "disconnected" in str(e).lower()
                    or "closed" in str(e).lower()
                    or "connection" in str(e).lower()
                ):
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(
                        f"save_ddl_memory connection error, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Failed to save DDL memory: {e}")
                return None
        return None

    async def search_schema_context(
        self,
        question: str,
        limit: int = 3,
        similarity_threshold: float = 0.4,
        question_vector: Optional[List[float]] = None,
    ) -> List[DDLMemorySearchResult]:
        """
        Search for relevant schema context.

        Args:
            question: The question to find relevant schemas for
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score
            question_vector: Pre-computed embedding vector (avoids redundant embedding)

        Returns:
            List of relevant DDL memories with scores
        """
        engine = self._get_engine()
        if not engine:
            return []

        try:
            vector = question_vector or await self._create_embedding(question)
            if not vector:
                return []

            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{MemoryType.DDL_SCHEMA.value}'"
            )

            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return []
                # Use hybrid search (vector + keyword) for better recall
                results = await engine.hybrid_search(
                    text=question,
                    vector=vector,
                    top_k=limit,
                    filter_expr=filter_expr,
                )

            output_results = []
            for rank, result in enumerate(results, start=1):
                score = result.score
                if score < similarity_threshold:
                    continue

                metadata = result.metadata or {}

                # Parse column info from JSON
                columns = []
                column_json = metadata.get("column_info_json")
                if column_json:
                    try:
                        column_dicts = json.loads(column_json)
                        columns = [ColumnDetail(**c) for c in column_dicts]
                    except Exception:
                        pass

                # Parse relationships from JSON
                relationships = []
                rel_json = metadata.get("relationships_json")
                if rel_json:
                    try:
                        relationships = json.loads(rel_json)
                    except Exception:
                        pass

                memory = DDLMemory(
                    memory_id=result.id,
                    ddl_statement=metadata.get("ddl_statement", ""),
                    table_name=metadata.get("table_name", ""),
                    schema_name=metadata.get("schema_name"),
                    columns=columns,
                    table_description=metadata.get("table_description"),
                    relationships=relationships,
                    timestamp=metadata.get("created_at"),
                    metadata=metadata,
                )

                output_results.append(
                    DDLMemorySearchResult(
                        memory=memory,
                        similarity_score=score,
                        rank=rank,
                    )
                )

            return output_results

        except Exception as e:
            logger.error(f"Failed to search schema context: {e}")
            return []

    async def get_table_schemas(
        self,
        table_names: Optional[List[str]] = None,
    ) -> List[DDLMemory]:
        """
        Get DDL memories for specific tables.

        Args:
            table_names: List of table names to retrieve. If None, returns all.

        Returns:
            List of DDL memories for the requested tables
        """
        engine = self._get_engine()
        if not engine:
            return []

        try:
            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{MemoryType.DDL_SCHEMA.value}'"
            )

            # Server-side OData filtering when specific table names are given
            if table_names:
                table_conditions = " or ".join(
                    f"table_name eq '{_odata_quote(name)}'" for name in table_names
                )
                filter_expr += f" and ({table_conditions})"

            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return []
                results = await engine.filter_by_metadata(
                    filter_expr=filter_expr,
                    limit=DDL_SCHEMA_FETCH_LIMIT,
                )

            # Surface silent truncation: a full reload that exactly fills the cap
            # is almost certainly clipped, which would make the join_graph full-S
            # recompute operate on a partial set. Callers (the recompute
            # orchestrator) detect this via len(memories) >= DDL_SCHEMA_FETCH_LIMIT
            # and flag dbsphere.data["join_graph_truncated"].
            if len(results) >= DDL_SCHEMA_FETCH_LIMIT:
                logger.warning(
                    "get_table_schemas hit fetch cap (%d) for dbsphere %s — "
                    "DDL set may be truncated; join_graph full-S recompute would "
                    "be incomplete (>%d tables need pagination, TODO).",
                    DDL_SCHEMA_FETCH_LIMIT,
                    self.dbsphere_id,
                    DDL_SCHEMA_FETCH_LIMIT,
                )

            memories = []
            for doc in results:
                metadata = doc.metadata or {}
                doc_table_name = metadata.get("table_name", "")

                # Parse column info
                columns = []
                column_json = metadata.get("column_info_json")
                if column_json:
                    try:
                        column_dicts = json.loads(column_json)
                        columns = [ColumnDetail(**c) for c in column_dicts]
                    except Exception:
                        pass

                # Parse relationships
                relationships = []
                rel_json = metadata.get("relationships_json")
                if rel_json:
                    try:
                        relationships = json.loads(rel_json)
                    except Exception:
                        pass

                memory = DDLMemory(
                    memory_id=doc.id,
                    ddl_statement=metadata.get("ddl_statement", ""),
                    table_name=doc_table_name,
                    schema_name=metadata.get("schema_name"),
                    columns=columns,
                    table_description=metadata.get("table_description"),
                    relationships=relationships,
                    timestamp=metadata.get("created_at"),
                    metadata=metadata,
                )
                memories.append(memory)

            return memories

        except Exception as e:
            logger.error(f"Failed to get table schemas: {e}")
            return []

    # =========================================================================
    # Documentation Memory (new)
    # =========================================================================

    async def save_documentation(
        self,
        content: str,
        doc_type: str = "context",
        title: Optional[str] = None,
        related_tables: Optional[List[str]] = None,
        related_columns: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        memory_id: Optional[str] = None,
    ) -> Optional[DocumentationMemory]:
        """
        Save documentation/business context.

        Args:
            content: The documentation content
            doc_type: Type of documentation (term, rule, context)
            title: Optional title for the documentation
            related_tables: List of related table names
            related_columns: List of related column names (format: table.column)
            metadata: Additional metadata
            memory_id: Deterministic document id. 주어지면 그 id 로 upsert
                (merge_or_upload — 고정 id 덮어쓰기/생성)하여 재추출 멱등을 보장한다.
                미지정 시 기존 동작(uuid4 신규 발급 + insert) 유지(하위호환).

        Returns:
            The created DocumentationMemory or None if save failed
        """
        engine = self._get_engine()
        if not engine:
            logger.warning("Search engine not configured, skipping documentation save")
            return None

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # deterministic id 가 주어지면 upsert(고정 id 덮어쓰기), 아니면
                # 기존 uuid4+insert 하위호환.
                upsert = memory_id is not None
                if memory_id is None:
                    memory_id = str(uuid.uuid4())
                timestamp = datetime.now(timezone.utc).isoformat()

                # rich_content(rerank 표층) + embedding_text(벡터 입력) — edit 경로와
                # 동일 빌더로 통일(드리프트 방지).
                rich_content, embedding_text = render_documentation_memory(
                    title, content, related_tables, related_columns
                )

                vector = await self._create_embedding(embedding_text)

                document = DocumentItem(
                    id=memory_id,
                    content=rich_content,
                    vector=vector,
                    collection=self.dbsphere_id,
                    metadata={
                        "entity_type": MemoryType.DOCUMENTATION.value,
                        "doc_type": doc_type,
                        "title": title,
                        "related_tables_json": json.dumps(related_tables)
                        if related_tables
                        else None,
                        "related_columns_json": json.dumps(related_columns)
                        if related_columns
                        else None,
                        "user_id": metadata.get("user_id") if metadata else None,
                        # 생성자 구분 배지(자동/수동)용.
                        "origin": metadata.get("origin") if metadata else None,
                        # clean 본문 — content 는 rich_content(Title:/Related tables: 접두사
                        # 포함)라 표시/편집용 원본을 별도 보관(읽기 시 접두사 없이 보여주려고).
                        "doc_content": content,
                        "created_at": timestamp,
                    },
                )

                async with self._engine_ctx(engine):
                    await self._ensure_index_exists(engine)
                    if upsert:
                        # merge_or_upload(azure) / ON CONFLICT(pg) / index-by-id(es)
                        # — 고정 id 라 재추출해도 단 1개 유지.
                        await engine.update([document])
                    else:
                        await engine.insert([document])

                return DocumentationMemory(
                    memory_id=memory_id,
                    content=content,
                    doc_type=doc_type,
                    title=title,
                    related_tables=related_tables or [],
                    related_columns=related_columns or [],
                    timestamp=timestamp,
                    metadata=metadata or {},
                )

            except Exception as e:
                if attempt < max_retries - 1 and (
                    "disconnected" in str(e).lower()
                    or "closed" in str(e).lower()
                    or "connection" in str(e).lower()
                ):
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(
                        f"save_documentation connection error, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Failed to save documentation: {e}")
                return None
        return None

    async def search_documentation(
        self,
        question: str,
        limit: int = 3,
        doc_type: Optional[str] = None,
        similarity_threshold: float = 0.4,
        question_vector: Optional[List[float]] = None,
    ) -> List[DocumentationSearchResult]:
        """
        Search for relevant documentation.

        Args:
            question: The question to find relevant documentation for
            limit: Maximum number of results
            doc_type: Optional filter by documentation type
            similarity_threshold: Minimum similarity score
            question_vector: Pre-computed embedding vector (avoids redundant embedding)

        Returns:
            List of relevant documentation with scores
        """
        engine = self._get_engine()
        if not engine:
            return []

        try:
            vector = question_vector or await self._create_embedding(question)
            if not vector:
                return []

            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{MemoryType.DOCUMENTATION.value}'"
            )
            if doc_type:
                filter_expr += f" and doc_type eq '{_odata_quote(doc_type)}'"

            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return []
                # Use hybrid search (vector + keyword) for better recall
                results = await engine.hybrid_search(
                    text=question,
                    vector=vector,
                    top_k=limit,
                    filter_expr=filter_expr,
                )

            output_results = []
            for rank, result in enumerate(results, start=1):
                score = result.score
                if score < similarity_threshold:
                    continue

                metadata = result.metadata or {}

                # E2 (Option C transition): skip the legacy relationship-graph doc.
                # Relationships now live in dbsphere.data["join_graph"]; a
                # pre-Option-C dbsphere may still hold the old DOCUMENTATION doc
                # until re-extract — exclude it so it is never double-surfaced
                # alongside the always-inject join_graph. Match the deterministic id
                # suffix OR the title (catches PR#219-era random-id orphans); this
                # cannot be an OData clause (title/source are not filterable columns).
                if (
                    str(result.id or "").endswith(RELATIONSHIP_DOC_ID_SUFFIX)
                    or metadata.get("title") == RELATIONSHIP_DOC_TITLE
                ):
                    continue

                # Parse related tables
                related_tables = []
                tables_json = metadata.get("related_tables_json")
                if tables_json:
                    try:
                        related_tables = json.loads(tables_json)
                    except Exception:
                        pass

                # Parse related columns
                related_columns = []
                columns_json = metadata.get("related_columns_json")
                if columns_json:
                    try:
                        related_columns = json.loads(columns_json)
                    except Exception:
                        pass

                memory = DocumentationMemory(
                    memory_id=result.id,
                    content=result.content,
                    doc_type=metadata.get("doc_type", "context"),
                    title=metadata.get("title"),
                    related_tables=related_tables,
                    related_columns=related_columns,
                    timestamp=metadata.get("created_at"),
                    metadata=metadata,
                )

                output_results.append(
                    DocumentationSearchResult(
                        memory=memory,
                        similarity_score=score,
                        rank=rank,
                    )
                )

            return output_results

        except Exception as e:
            logger.error(f"Failed to search documentation: {e}")
            return []

    # =========================================================================
    # SQL Example Memory (new)
    # =========================================================================

    async def save_sql_example(
        self,
        sql: str,
        description: str,
        use_case: Optional[str] = None,
        related_tables: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SqlExampleMemory]:
        """
        Save an annotated SQL example.

        Args:
            sql: The SQL query
            description: Description of what the query does
            use_case: Use case category
            related_tables: List of tables used in the query
            tags: Tags for categorization
            metadata: Additional metadata

        Returns:
            The created SqlExampleMemory or None if save failed
        """
        engine = self._get_engine()
        if not engine:
            logger.warning("Search engine not configured, skipping SQL example save")
            return None

        try:
            memory_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()

            # === IMPROVED: Rich content for semantic reranking ===
            content_parts = [f"Description: {description}"]
            if use_case:
                content_parts.append(f"Use case: {use_case}")
            content_parts.append(f"SQL: {sql}")
            if related_tables:
                content_parts.append(f"Tables: {', '.join(related_tables)}")
            if tags:
                content_parts.append(f"Tags: {', '.join(tags)}")
            content = "\n".join(content_parts)

            # === IMPROVED: Meaning-focused embedding ===
            embedding_parts = [description]
            if use_case:
                embedding_parts.append(use_case)
            # Include SQL for pattern matching but description is primary
            embedding_parts.append(sql)
            if tags:
                embedding_parts.append(" ".join(tags))
            embedding_text = "\n".join(embedding_parts)

            vector = await self._create_embedding(embedding_text)

            document = DocumentItem(
                id=memory_id,
                content=content,
                vector=vector,
                collection=self.dbsphere_id,
                metadata={
                    "entity_type": MemoryType.SQL_EXAMPLE.value,
                    "sql_query": sql,
                    "description": description,
                    "use_case": use_case,
                    "related_tables_json": json.dumps(related_tables)
                    if related_tables
                    else None,
                    "tags_json": json.dumps(tags) if tags else None,
                    # 생성자 이메일 해석용 (create_memory 가 user_id 를 넘긴다).
                    "user_id": metadata.get("user_id") if metadata else None,
                    "created_at": timestamp,
                },
            )

            async with self._engine_ctx(engine):
                await self._ensure_index_exists(engine)
                await engine.insert([document])

            return SqlExampleMemory(
                memory_id=memory_id,
                sql=sql,
                description=description,
                use_case=use_case,
                related_tables=related_tables or [],
                tags=tags or [],
                timestamp=timestamp,
                metadata=metadata or {},
            )

        except Exception as e:
            logger.error(f"Failed to save SQL example: {e}")
            return None

    async def search_sql_examples(
        self,
        description: str,
        limit: int = 3,
        use_case: Optional[str] = None,
        similarity_threshold: float = 0.4,
        question_vector: Optional[List[float]] = None,
    ) -> List[SqlExampleSearchResult]:
        """
        Search for relevant SQL examples.

        Args:
            description: Description to search for
            limit: Maximum number of results
            use_case: Optional filter by use case
            similarity_threshold: Minimum similarity score
            question_vector: Pre-computed embedding vector (avoids redundant embedding)

        Returns:
            List of relevant SQL examples with scores
        """
        engine = self._get_engine()
        if not engine:
            return []

        try:
            vector = question_vector or await self._create_embedding(description)
            if not vector:
                return []

            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{MemoryType.SQL_EXAMPLE.value}'"
            )
            if use_case:
                filter_expr += f" and use_case eq '{_odata_quote(use_case)}'"

            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return []
                # Use hybrid search (vector + keyword) for better recall
                results = await engine.hybrid_search(
                    text=description,
                    vector=vector,
                    top_k=limit,
                    filter_expr=filter_expr,
                )

            output_results = []
            for rank, result in enumerate(results, start=1):
                score = result.score
                if score < similarity_threshold:
                    continue

                metadata = result.metadata or {}

                # Parse related tables
                related_tables = []
                tables_json = metadata.get("related_tables_json")
                if tables_json:
                    try:
                        related_tables = json.loads(tables_json)
                    except Exception:
                        pass

                # Parse tags
                tags = []
                tags_json = metadata.get("tags_json")
                if tags_json:
                    try:
                        tags = json.loads(tags_json)
                    except Exception:
                        pass

                memory = SqlExampleMemory(
                    memory_id=result.id,
                    sql=metadata.get("sql_query", ""),
                    description=result.content,
                    use_case=metadata.get("use_case"),
                    related_tables=related_tables,
                    tags=tags,
                    timestamp=metadata.get("created_at"),
                    metadata=metadata,
                )

                output_results.append(
                    SqlExampleSearchResult(
                        memory=memory,
                        similarity_score=score,
                        rank=rank,
                    )
                )

            return output_results

        except Exception as e:
            logger.error(f"Failed to search SQL examples: {e}")
            return []

    # =========================================================================
    # Unified Search (new)
    # =========================================================================

    async def search_all_context(
        self,
        question: str,
        include_types: Optional[List[MemoryType]] = None,
        limit_per_type: int = 3,
        similarity_threshold: float = 0.4,
    ) -> UnifiedSearchResult:
        """
        Search across all memory types for relevant context.

        Generates the embedding once and reuses it across all memory type searches.

        Args:
            question: The question to search for
            include_types: List of memory types to include (default: all)
            limit_per_type: Maximum results per memory type
            similarity_threshold: Minimum similarity score

        Returns:
            UnifiedSearchResult containing results from all requested types
        """
        if include_types is None:
            include_types = list(MemoryType)

        result = UnifiedSearchResult()

        # Generate embedding once for all searches
        question_vector = await self._create_embedding(question)
        if not question_vector:
            logger.warning("Failed to create embedding for search_all_context")
            return result

        # Search each memory type with pre-computed vector
        if MemoryType.SQL_MEMORY in include_types:
            result.sql_memories = await self.search_similar_queries(
                question=question,
                limit=limit_per_type,
                similarity_threshold=similarity_threshold,
                question_vector=question_vector,
            )

        if MemoryType.DDL_SCHEMA in include_types:
            result.ddl_memories = await self.search_schema_context(
                question=question,
                limit=limit_per_type,
                similarity_threshold=similarity_threshold,
                question_vector=question_vector,
            )

        if MemoryType.DOCUMENTATION in include_types:
            result.documentation = await self.search_documentation(
                question=question,
                limit=limit_per_type,
                similarity_threshold=similarity_threshold,
                question_vector=question_vector,
            )

        if MemoryType.SQL_EXAMPLE in include_types:
            result.sql_examples = await self.search_sql_examples(
                description=question,
                limit=limit_per_type,
                similarity_threshold=similarity_threshold,
                question_vector=question_vector,
            )

        return result

    # =========================================================================
    # Formatting for Prompts
    # =========================================================================

    def format_similar_queries_for_prompt(
        self, results: List[SqlMemorySearchResult]
    ) -> str:
        """
        Format SQL memory search results for inclusion in the system prompt.

        Args:
            results: List of similar query search results

        Returns:
            Formatted string for the prompt
        """
        if not results:
            return "No similar queries found in memory."

        lines = ["Here are similar successful queries from the past:"]
        for result in results:
            lines.append(
                f"\n--- Example {result.rank} (Score: {result.similarity_score:.2f}) ---"
            )
            lines.append(f"Question: {result.memory.question}")
            lines.append(f"SQL: {result.memory.sql}")

        return "\n".join(lines)

    def format_ddl_context_for_prompt(
        self, results: List[DDLMemorySearchResult]
    ) -> str:
        """
        Format DDL memory search results for the prompt.

        Args:
            results: List of DDL memory search results

        Returns:
            Formatted string with schema context
        """
        if not results:
            return ""

        lines = ["Relevant table schemas with descriptions:"]
        for result in results:
            memory = result.memory
            lines.append(f"\n### Table: {memory.table_name}")
            if memory.table_description:
                lines.append(f"Description: {memory.table_description}")
            lines.append(f"```sql\n{memory.ddl_statement}\n```")
            if memory.columns:
                lines.append("Column details:")
                for col in memory.columns:
                    col_desc = f"  - {col.name} ({col.data_type})"
                    if col.description:
                        col_desc += f": {col.description}"
                    if col.is_primary_key:
                        col_desc += " [PK]"
                    if col.is_foreign_key and col.foreign_table:
                        col_desc += f" [FK -> {col.foreign_table}]"
                    lines.append(col_desc)

        return "\n".join(lines)

    def format_documentation_for_prompt(
        self, results: List[DocumentationSearchResult]
    ) -> str:
        """
        Format documentation search results for the prompt.

        Args:
            results: List of documentation search results

        Returns:
            Formatted string with business context
        """
        if not results:
            return ""

        lines = ["Business context and rules:"]
        for result in results:
            memory = result.memory
            if memory.title:
                lines.append(f"\n### {memory.title}")
            else:
                lines.append(f"\n### {memory.doc_type.title()}")
            lines.append(memory.content)
            if memory.related_tables:
                lines.append(f"Related tables: {', '.join(memory.related_tables)}")

        return "\n".join(lines)

    def format_sql_examples_for_prompt(
        self, results: List[SqlExampleSearchResult]
    ) -> str:
        """
        Format SQL example search results for the prompt.

        Args:
            results: List of SQL example search results

        Returns:
            Formatted string with SQL examples
        """
        if not results:
            return ""

        lines = ["Reference SQL examples:"]
        for result in results:
            memory = result.memory
            lines.append(f"\n--- Example: {memory.description} ---")
            if memory.use_case:
                lines.append(f"Use case: {memory.use_case}")
            lines.append(f"```sql\n{memory.sql}\n```")

        return "\n".join(lines)

    def format_context_for_prompt(
        self,
        unified_result: UnifiedSearchResult,
    ) -> str:
        """
        Format all search results into a comprehensive context string for the prompt.

        Args:
            unified_result: UnifiedSearchResult from search_all_context

        Returns:
            Formatted string containing all relevant context
        """
        sections = []

        # DDL/Schema context
        ddl_section = self.format_ddl_context_for_prompt(unified_result.ddl_memories)
        if ddl_section:
            sections.append(ddl_section)

        # Documentation/Business context
        doc_section = self.format_documentation_for_prompt(unified_result.documentation)
        if doc_section:
            sections.append(doc_section)

        # SQL examples
        example_section = self.format_sql_examples_for_prompt(
            unified_result.sql_examples
        )
        if example_section:
            sections.append(example_section)

        # Similar queries (SQL memory)
        query_section = self.format_similar_queries_for_prompt(
            unified_result.sql_memories
        )
        if query_section and query_section != "No similar queries found in memory.":
            sections.append(query_section)

        return "\n\n".join(sections) if sections else ""

    # =========================================================================
    # Memory Management
    # =========================================================================

    async def list_memories_by_type(
        self,
        memory_type: Optional[MemoryType] = None,
        limit: int = 200,
    ) -> List[DocumentItem]:
        """
        List memories by type for management UI.

        Args:
            memory_type: The type of memories to list. If None, returns all types.
            limit: Maximum number of results

        Returns:
            List of DocumentItem objects
        """
        engine = self._get_engine()
        if not engine:
            return []

        try:
            filter_expr = f"collection eq '{self.dbsphere_id}'"
            if memory_type:
                filter_expr += f" and entity_type eq '{memory_type.value}'"

            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return []
                results = await engine.filter_by_metadata(
                    filter_expr=filter_expr,
                    limit=limit,
                )

            # 관리 UI 누수 차단: sql_memory row 는 작성자(또는 admin)만, DDL/doc/
            # example 은 공유 지식이라 그대로 노출. (C-5)
            is_admin = self._requester_is_admin()
            visible: List[DocumentItem] = []
            for doc in results:
                md = doc.metadata or {}
                if md.get(
                    "entity_type"
                ) == MemoryType.SQL_MEMORY.value and not _sql_memory_row_visible(
                    md, requester_user_id=self.user_id, is_admin=is_admin
                ):
                    continue
                visible.append(doc)

            # 최신순(created_at desc) 정렬 — created_at 은 ISO8601 문자열이라
            # 사전식 정렬이 곧 시간순. 누락된 row 는 맨 뒤로.
            visible.sort(
                key=lambda d: (d.metadata or {}).get("created_at") or "",
                reverse=True,
            )
            return visible

        except Exception as e:
            logger.error(f"Failed to list memories: {e}")
            return []

    async def get_memory_by_id(self, memory_id: str) -> Optional[DocumentItem]:
        """
        Get a single memory by ID.

        Args:
            memory_id: The memory ID

        Returns:
            DocumentItem or None if not found
        """
        engine = self._get_engine()
        if not engine:
            return None

        try:
            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return None
                results = await engine.get([memory_id])
                if results:
                    return results[0]
            return None

        except Exception as e:
            logger.error(f"Failed to get memory by id: {e}")
            return None

    async def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update a memory's content and/or metadata.

        If content is changed, the embedding vector is also regenerated.

        Args:
            memory_id: The memory ID to update
            content: New content (if None, keeps existing)
            metadata_updates: Dict of metadata fields to update

        Returns:
            True if update succeeded
        """
        engine = self._get_engine()
        if not engine:
            return False

        try:
            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return False

                # Get existing document
                existing = await engine.get([memory_id])
                if not existing:
                    return False

                doc = existing[0]
                doc_meta = doc.metadata or {}
                new_metadata = {**doc_meta}
                if metadata_updates:
                    new_metadata.update(metadata_updates)

                embed_attempted = False

                if new_metadata.get("entity_type") == MemoryType.DDL_SCHEMA.value:
                    # DDL edit: the FE sends only metadata (table_description +
                    # a lossy column_info_json) and never `content`, so the old
                    # "re-embed only when content changed" path left content and
                    # vector stale on every edit. Rebuild both from the edited
                    # metadata with the same builder create uses. Merge columns
                    # field-wise so the FE-dropped structural fields
                    # (foreign_column / is_nullable / default_value) survive —
                    # the join-graph (get_table_schemas) consumes them.
                    # _safe_json guards relationships_json=None (json.loads(None)
                    # would otherwise 404 every relationship-less edit).
                    stored_cols = _safe_json(doc_meta.get("column_info_json")) or []
                    incoming_cols = (
                        _safe_json(new_metadata.get("column_info_json")) or []
                    )
                    merged_cols = merge_columns_by_name(stored_cols, incoming_cols)
                    relationships = (
                        _safe_json(new_metadata.get("relationships_json")) or []
                    )
                    new_metadata["column_info_json"] = (
                        json.dumps(merged_cols) if merged_cols else None
                    )
                    new_content, embedding_text = render_ddl_memory(
                        new_metadata.get("table_name", ""),
                        new_metadata.get("table_description"),
                        merged_cols,
                        relationships,
                    )
                    new_vector = await self._create_embedding(embedding_text)
                    embed_attempted = True
                elif (
                    new_metadata.get("entity_type") == MemoryType.DOCUMENTATION.value
                    and content is not None
                ):
                    # 문서 본문 편집: content 는 clean 본문으로 들어온다. save 와 같은 빌더로
                    # rich_content(검색 표층) + embedding_text(벡터)를 재구성해 편집 후에도
                    # title/related_tables 가 벡터에 유지되게 한다. 표시용 clean 본문은
                    # doc_content 메타로 동기 보관. related_columns 는 FE 미전송 시 기존값
                    # (merge 로 보존)을 사용. fail-closed 는 비-DDL 결 그대로 미적용(resilient).
                    rel_tables = (
                        _safe_json(new_metadata.get("related_tables_json")) or []
                    )
                    rel_columns = (
                        _safe_json(new_metadata.get("related_columns_json")) or []
                    )
                    new_content, embedding_text = render_documentation_memory(
                        new_metadata.get("title"), content, rel_tables, rel_columns
                    )
                    new_metadata["doc_content"] = content
                    new_vector = await self._create_embedding(embedding_text)
                else:
                    # Non-DDL: unchanged legacy behavior — re-embed only on a
                    # content change. Fail-closed below is scoped to DDL/doc, so
                    # these paths keep their prior semantics exactly.
                    new_content = content if content is not None else doc.content
                    new_vector = doc.vector
                    if content is not None and content != doc.content:
                        new_vector = await self._create_embedding(new_content)

                # Fail-closed (DDL only): a re-embed that returned None must not
                # overwrite the row with a null vector — that silently breaks
                # semantic search. Refuse the partial save. Scoped to attempted
                # embeddings so a metadata-only edit of a legacy null-vector doc
                # still succeeds.
                if embed_attempted and new_vector is None:
                    logger.warning(
                        "update_memory: embedding failed for %s, refusing partial "
                        "save (vector would be null)",
                        memory_id,
                    )
                    return False

                updated_doc = DocumentItem(
                    id=memory_id,
                    content=new_content,
                    vector=new_vector,
                    collection=self.dbsphere_id,
                    metadata=new_metadata,
                )

                updated = await engine.update([updated_doc])
                if embed_attempted and updated > 0:
                    # Observability: confirms the DDL edit actually re-embedded.
                    # vhash differs before/after iff the vector changed; text
                    # shows what drove it (the edited description/columns).
                    logger.info(
                        "DDL re-embedded: memory=%s table=%s dim=%s vhash=%s text=%r",
                        memory_id,
                        new_metadata.get("table_name"),
                        len(new_vector or []),
                        hashlib.sha1(str(new_vector).encode("utf-8")).hexdigest()[:10],
                        embedding_text[:120].replace("\n", " | "),
                    )
                return updated > 0

        except Exception as e:
            logger.error(f"Failed to update memory: {e}")
            return False

    async def count_memories_by_type(self) -> Dict[str, int]:
        """
        Count memories by type for stats.

        Returns:
            Dict mapping memory type value to count
        """
        engine = self._get_engine()
        if not engine:
            return {}

        counts = {}
        try:
            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return {}

                is_admin = self._requester_is_admin()
                for memory_type in MemoryType:
                    filter_expr = (
                        f"collection eq '{self.dbsphere_id}' and "
                        f"entity_type eq '{memory_type.value}'"
                    )
                    # sql_memory 만 tenant 격리된 가시 수를 센다(C-5 volume leak).
                    # DDL/doc/example 은 공유라 전체 count. cap 내 정확, 초과 시 근사.
                    if memory_type == MemoryType.SQL_MEMORY and not is_admin:
                        docs = await engine.filter_by_metadata(
                            filter_expr=filter_expr,
                            limit=_SQL_MEMORY_COUNT_CAP,
                        )
                        counts[memory_type.value] = sum(
                            1
                            for d in docs
                            if _sql_memory_row_visible(
                                d.metadata or {},
                                requester_user_id=self.user_id,
                                is_admin=False,
                            )
                        )
                    else:
                        counts[memory_type.value] = await engine.count(
                            filter_expr=filter_expr
                        )

            return counts

        except Exception as e:
            logger.error(f"Failed to count memories: {e}")
            return {}

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        engine = self._get_engine()
        if not engine:
            return False

        try:
            async with self._engine_ctx(engine):
                deleted = await engine.delete([memory_id])
            return deleted > 0
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False

    async def delete_relationship_graph_doc(self) -> bool:
        """Purge the legacy fixed-id relationship DOCUMENTATION doc (Option C E1).

        Relationships now live in dbsphere.data["join_graph"]; this removes the
        pre-Option-C doc so it can't double-surface via similarity retrieval.
        Idempotent (no-op if absent). PR#219-era random-id orphans are not caught
        here — the E2 retrieve-stage filter excludes those.
        """
        return await self.delete_memory(
            f"{self.dbsphere_id}{RELATIONSHIP_DOC_ID_SUFFIX}"
        )

    async def delete_memories_by_type(
        self,
        memory_type: MemoryType,
    ) -> int:
        """
        Delete all memories of a specific type.

        Args:
            memory_type: The type of memories to delete

        Returns:
            Number of memories deleted
        """
        engine = self._get_engine()
        if not engine:
            return 0

        try:
            filter_expr = (
                f"collection eq '{self.dbsphere_id}' and "
                f"entity_type eq '{memory_type.value}'"
            )

            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return 0
                results = await engine.filter_by_metadata(
                    filter_expr=filter_expr,
                    limit=1000,
                )

                if not results:
                    return 0

                memory_ids = [doc.id for doc in results]
                deleted = await engine.delete(memory_ids)
                return deleted

        except Exception as e:
            logger.error(f"Failed to delete memories by type: {e}")
            return 0

    async def delete_memories_by_table_name(
        self,
        table_name: str,
    ) -> Dict[str, int]:
        """
        Delete all memories associated with a specific table.

        Deletes DDL_SCHEMA entries and SQL_MEMORY entries (sample Q&A)
        that have matching table_name in metadata.

        For SQL_MEMORY, also handles legacy entries where table_name was not
        stored (table_name eq null) by checking the sql_query content.

        Args:
            table_name: The table name to delete memories for

        Returns:
            Dict mapping memory type name to number of deleted items
        """
        engine = self._get_engine()
        if not engine:
            return {}

        results = {}

        try:
            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return {}

                # DDL_SCHEMA: filter directly by table_name
                ddl_filter = (
                    f"collection eq '{self.dbsphere_id}' and "
                    f"entity_type eq '{MemoryType.DDL_SCHEMA.value}' and "
                    f"table_name eq '{_odata_quote(table_name)}'"
                )
                ddl_docs = await engine.filter_by_metadata(
                    filter_expr=ddl_filter,
                    limit=1000,
                )
                if ddl_docs:
                    deleted = await engine.delete([doc.id for doc in ddl_docs])
                    results[MemoryType.DDL_SCHEMA.value] = deleted
                    logger.info(
                        f"Deleted {deleted} ddl_schema memories "
                        f"for table {table_name} in dbsphere {self.dbsphere_id}"
                    )
                else:
                    results[MemoryType.DDL_SCHEMA.value] = 0

                # SQL_MEMORY: filter by table_name (set from schema extraction onwards)
                # Legacy entries without table_name cannot be safely attributed to a
                # single table (JOIN queries may reference multiple tables), so they
                # are intentionally excluded from table-scoped deletion.
                sql_filter = (
                    f"collection eq '{self.dbsphere_id}' and "
                    f"entity_type eq '{MemoryType.SQL_MEMORY.value}' and "
                    f"table_name eq '{_odata_quote(table_name)}'"
                )
                sql_docs = await engine.filter_by_metadata(
                    filter_expr=sql_filter,
                    limit=1000,
                )
                if sql_docs:
                    deleted = await engine.delete([doc.id for doc in sql_docs])
                    results[MemoryType.SQL_MEMORY.value] = deleted
                    logger.info(
                        f"Deleted {deleted} sql_memory memories "
                        f"for table {table_name} in dbsphere {self.dbsphere_id}"
                    )
                else:
                    results[MemoryType.SQL_MEMORY.value] = 0

            return results

        except Exception as e:
            logger.error(f"Failed to delete memories for table {table_name}: {e}")
            return results

    async def delete_all_memories(
        self,
        include_types: Optional[List[MemoryType]] = None,
    ) -> Dict[str, int]:
        """
        Delete all memories for this dbsphere.

        Args:
            include_types: List of memory types to delete.
                          If None, deletes all types.

        Returns:
            Dict mapping memory type name to number of deleted items
        """
        if include_types is None:
            include_types = list(MemoryType)

        engine = self._get_engine()
        if not engine:
            return {}

        results = {}
        try:
            async with self._engine_ctx(engine):
                if not await engine.index_exists():
                    return {}

                for memory_type in include_types:
                    filter_expr = (
                        f"collection eq '{self.dbsphere_id}' and "
                        f"entity_type eq '{memory_type.value}'"
                    )

                    docs = await engine.filter_by_metadata(
                        filter_expr=filter_expr,
                        limit=1000,
                    )

                    if docs:
                        memory_ids = [doc.id for doc in docs]
                        deleted = await engine.delete(memory_ids)
                        results[memory_type.value] = deleted
                        logger.info(
                            f"Deleted {deleted} {memory_type.value} memories "
                            f"for dbsphere {self.dbsphere_id}"
                        )
                    else:
                        results[memory_type.value] = 0

            return results

        except Exception as e:
            logger.error(f"Failed to delete all memories: {e}")
            return results


# Backward compatibility alias
SearchEngineSqlMemory = SearchEngineDbSphereMemory
