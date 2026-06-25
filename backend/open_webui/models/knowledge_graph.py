"""
Knowledge Graph 모델

워크스페이스 리소스로서의 KG 인스턴스(`knowledge_graph`)와
그래프를 구성하는 노드/엣지(`kg_node`, `kg_edge`)를 정의한다.

설계 노트:
- KG 인스턴스의 `data` 필드에 소스 참조와 옵션을 저장한다.
  ```
  data = {
      "sources": {
          "glossary_ids": ["..."],
          "dbsphere_ids": ["..."],
          "knowledge_ids": ["..."],
      },
      "options": {
          "llm_model_id": "...",            # sync/추출용 LLM
          "tool_description_model_id": "...",  # 도구 설명 생성용 LLM
          "sync_mode": "manual",  # manual | nightly | realtime
      },
      "stats": {
          "node_count": 0,
          "edge_count": 0,
          "last_synced_at": None,
      },
  }
  ```
- 노드 ID는 가능하면 결정적(`kg_<kgid>__term__<glossary_id>__<entry_id>`).
  재동기화 시 동일 ID가 만들어져 idempotent upsert가 가능하다.
- 노드/엣지 테이블은 FK 제약을 두지 않는다 (Cloosphere 전반의 패턴 일치).
  대신 인덱스로 빠른 트래버설을 보장한다.
"""

import hashlib
import logging
import re
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserResponse, Users
from open_webui.utils.access_control import has_access
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, BigInteger, Column, Float, Index, Integer, Text, or_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Node / Edge Type Constants
####################


class NodeType:
    # 리프 / 구조 (기존)
    TERM = "term"
    CONCEPT = "concept"
    TABLE = "table"
    COLUMN = "column"
    DOC_ENTITY = "doc_entity"  # LLM 이 청크에서 뽑은 속성/언급 엔티티
    DOC_ATTR = "doc_attr"  # KB 필터 값에서 파생된 문서 속성 노드
    # 컨테이너 (신규)
    DATABASE = "database"
    KNOWLEDGE_BASE = "knowledge_base"
    GLOSSARY = "glossary"
    # 문서 (KB 파일 단위)
    DOCUMENT = "document"


class EdgeType:
    """시스템 고정 엣지 타입 (글로서리/스키마 sync 등 코드가 직접 만드는 것).

    LLM 이 뽑아내는 도메인 엣지 타입은 KG 별로 ``kg.meta.edge_types`` 레지스트리에
    동적으로 누적된다 — 여기에 하드코딩하지 않는다.
    """

    # 글로서리 / 코드 sync 용 고정 타입
    SYNONYM_OF = "synonym_of"
    BROADER_THAN = "broader_than"
    NARROWER_THAN = "narrower_than"
    RELATED_TO = "related_to"
    MAPS_TO = "maps_to"
    DEFINED_AS = "defined_as"
    FOREIGN_KEY = "foreign_key"
    BELONGS_TO = "belongs_to"
    COMPUTED_FROM = "computed_from"
    # LLM 추출 결과 중 canonical 매칭 실패 시 기본 fallback
    HAS_FEATURE = "has_feature"
    # 계층 컨테인먼트 (상위 → 하위, Phase 2)
    CONTAINS_TABLE = "contains_table"
    CONTAINS_COLUMN = "contains_column"
    CONTAINS_DOCUMENT = "contains_document"
    CONTAINS_CONCEPT = "contains_concept"
    CONTAINS_TERM = "contains_term"
    # 프로비넌스 (doc_entity → DOCUMENT)
    EXTRACTED_FROM = "extracted_from"
    # 문서 단위 용어 매칭 (KB 필터 결과 기반)
    MENTIONS = "mentions"  # document → term


_EDGE_LABEL_NORMALIZE_RE = re.compile(r"[\s\-/.]+")


def normalize_edge_label(label: str) -> str:
    """LLM 이 준 엣지 라벨을 레지스트리 key 로 쓸 수 있게 정규화.

    - 앞뒤 공백 제거
    - 내부 공백/하이픈/슬래시/점 → 단일 언더스코어
    - ASCII 부분은 소문자 (한글은 그대로 유지)

    예: "Has Side-Effect" → "has_side_effect"
        " 주의 사항 " → "주의_사항"
    """
    if not label:
        return ""
    s = label.strip()
    s = _EDGE_LABEL_NORMALIZE_RE.sub("_", s)
    # ASCII 부분만 소문자 (한글 대소문자 없음)
    return "".join(ch.lower() if ch.isascii() else ch for ch in s)


def resolve_llm_edge_type(relation_label: str) -> str:
    """LLM 이 반환한 관계 라벨을 정규화된 key 로 변환.

    동적 레지스트리 구조이므로 별칭 매핑 / 화이트리스트 검증은 하지 않는다.
    Stage B 파이프라인이 ``kg.meta.edge_types`` 에 upsert 하는 과정에서
    기존 엣지와 의미 중복이 있으면 LLM 프롬프트가 재사용을 유도하고,
    정말 새로운 타입이면 레지스트리에 추가된다.

    빈 입력 시 HAS_FEATURE fallback.
    """
    if not relation_label:
        return EdgeType.HAS_FEATURE
    normalized = normalize_edge_label(relation_label)
    return normalized or EdgeType.HAS_FEATURE


class EdgeSource:
    """엣지가 어떻게 만들어졌는지 추적."""

    GLOSSARY_SYNC = "glossary_sync"
    SCHEMA_EXTRACTOR = "schema_extractor"
    LLM_EXTRACT = "llm_extract"
    MANUAL = "manual"
    DB_DERIVATION = "db_derivation"
    KB_MATCH = "kb_match"


####################
# DB Schema
####################


class KnowledgeGraph(Base):
    __tablename__ = "knowledge_graph"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class KGNode(Base):
    __tablename__ = "kg_node"

    id = Column(Text, primary_key=True)
    kg_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False)

    node_type = Column(Text, nullable=False)
    label = Column(Text, nullable=False)

    properties = Column(JSON, nullable=True)
    source_ref = Column(JSON, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("kg_node_kg_type_idx", "kg_id", "node_type"),
        Index("kg_node_kg_label_idx", "kg_id", "label"),
    )


class KGEdge(Base):
    __tablename__ = "kg_edge"

    id = Column(Text, primary_key=True)
    kg_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False)

    src_id = Column(Text, nullable=False)
    dst_id = Column(Text, nullable=False)
    edge_type = Column(Text, nullable=False)

    weight = Column(Float, nullable=True)
    properties = Column(JSON, nullable=True)
    source = Column(Text, nullable=False)

    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("kg_edge_kg_src_idx", "kg_id", "src_id", "edge_type"),
        Index("kg_edge_kg_dst_idx", "kg_id", "dst_id", "edge_type"),
    )


class CandidateStatus:
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class KGCandidate(Base):
    """LLM이 추출한 용어집 용어 후보 (검수 큐).

    Slice 6 — KG가 DbSphere 컬럼/KB 문서를 분석해서 비즈니스 용어 후보를
    생성하고, 사람이 검수해 수락하면 용어집 entry + maps_to 엣지가 자동
    생성된다. 거부하면 status가 rejected로 마킹된다.
    """

    __tablename__ = "kg_candidate"

    id = Column(Text, primary_key=True)
    kg_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False)

    candidate_type = Column(Text, nullable=False)  # 'term'
    suggested_label = Column(Text, nullable=False)  # LLM이 제안한 용어
    target_node_id = Column(Text, nullable=True)  # 매핑 대상 (보통 column 노드)

    properties = Column(JSON, nullable=True)
    # properties = {
    #     "confidence": 0.85,
    #     "reasoning": "...",
    #     "source_column": "users.tier",
    #     "data_type": "varchar(8)",
    #     "suggested_filter": "tier='V'" (선택),
    #     "model_id": "gpt-4.1",
    # }

    status = Column(Text, nullable=False)  # pending | accepted | rejected
    resolved_glossary_id = Column(
        Text, nullable=True
    )  # accept 시 어느 용어집에 들어갔는지
    resolved_entry_id = Column(Text, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    resolved_at = Column(BigInteger, nullable=True)

    __table_args__ = (Index("kg_candidate_kg_status_idx", "kg_id", "status"),)


class KGExtractState(Base):
    """KB 추출 상태 — KG별 KB별 처리 이력.

    기존에는 KnowledgeGraph.data["kb_extract_state"][kb_id] JSON에 저장했으나
    concurrent worker가 동시에 다른 KB 상태를 갱신하면 race condition이 발생했다.
    별도 테이블로 분리해 per-KB atomic update를 보장한다.
    """

    __tablename__ = "kg_extract_state"

    id = Column(Text, primary_key=True)  # f"{kg_id}__{kb_id}"
    kg_id = Column(Text, nullable=False)
    kb_id = Column(Text, nullable=False)
    processed_chunks = Column(JSON, nullable=True)  # list of chunk IDs
    last_run_at = Column(BigInteger, nullable=True)
    last_model = Column(Text, nullable=True)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("kg_extract_state_kg_kb_idx", "kg_id", "kb_id", unique=True),
    )


class KGAgePending(Base):
    """AGE dual-write 실패 시 재시도 대기열 (WAL).

    SQL은 성공했지만 AGE에 쓰기 실패한 작업을 기록하여
    이후 retry로 AGE 그래프 일관성을 복구한다.
    """

    __tablename__ = "kg_age_pending"

    id = Column(Text, primary_key=True)
    kg_id = Column(Text, nullable=False, index=True)
    operation = Column(
        Text, nullable=False
    )  # "upsert_node" | "upsert_edge" | "delete_node" | "delete_edge"
    payload = Column(JSON, nullable=False)  # operation-specific data
    retries = Column(BigInteger, nullable=False, default=0)
    created_at = Column(BigInteger, nullable=False)
    last_retry_at = Column(BigInteger, nullable=True)


class KGExtractJob(Base):
    """KG 백그라운드 추출/동기화 잡 추적 (Slice 9).

    long-running LLM 추출의 진행 상황을 사용자에게 노출하기 위함.
    `_extract_kb_bg`, `_sync_all_sources` 등이 잡 row를 만들고
    진행률 + 통계 + 에러를 갱신한다.
    """

    __tablename__ = "kg_extract_job"

    id = Column(Text, primary_key=True)
    kg_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)

    # 'kb_extract' | 'kb_cleanup' | 'candidate_extract' | 'sync_all'
    kind = Column(Text, nullable=False)
    # 'pending' | 'running' | 'completed' | 'failed'
    status = Column(Text, nullable=False)

    # 옵션: target 리소스 ID (예: knowledge_id, dbsphere_id)
    target_id = Column(Text, nullable=True)
    # 호출 시 form data — 재실행/디버깅용
    params = Column(JSON, nullable=True)

    progress_current = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    progress_label = Column(Text, nullable=True)

    stats = Column(JSON, nullable=True)
    errors = Column(JSON, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    started_at = Column(BigInteger, nullable=True)
    finished_at = Column(BigInteger, nullable=True)
    last_heartbeat_at = Column(BigInteger, nullable=True)

    __table_args__ = (
        Index("kg_extract_job_kg_idx", "kg_id", "created_at"),
        Index("kg_extract_job_status_idx", "status"),
    )


class KGKnowledgeLink(Base):
    """지식 연결 — 용어집 → 지식베이스(KB) 매핑.

    스키마 단순화 이후 source 는 항상 용어집, target 은 항상 KB(복수) 이다.
    기존 컬럼(dbsphere_id, table_name 등) 은 레거시 호환을 위해 nullable 로
    남겨두지만 신규 레코드는 모두 null 로 생성된다. 관련 마이그레이션에서
    기존 `source_type='db_column'` 레코드는 제거된다.
    """

    __tablename__ = "kg_knowledge_link"

    id = Column(Text, primary_key=True)
    kg_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False)
    # Source (현재는 항상 glossary)
    source_type = Column(Text, nullable=False, default="glossary")
    dbsphere_id = Column(Text, nullable=True)  # legacy
    table_name = Column(Text, nullable=True)  # legacy
    label_column = Column(Text, nullable=True)  # legacy
    key_column = Column(Text, nullable=True)  # legacy
    glossary_id = Column(Text, nullable=True)
    # Target (현재는 항상 knowledge + knowledge_ids 복수)
    target_type = Column(Text, nullable=False, default="knowledge")
    knowledge_ids = Column(JSON, nullable=True)
    target_dbsphere_id = Column(Text, nullable=True)  # legacy
    target_table_name = Column(Text, nullable=True)  # legacy
    target_column = Column(Text, nullable=True)  # legacy
    edge_type = Column(Text, nullable=True)  # legacy
    # Status
    status = Column(JSON, nullable=True)
    # Per-link config (link 단위 엣지 타입 카탈로그 + locked 토글 등)
    config = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


####################
# Pydantic Models
####################


class KnowledgeGraphModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int
    updated_at: int


class KnowledgeGraphUserModel(KnowledgeGraphModel):
    user: Optional[UserResponse] = None


class KnowledgeGraphResponse(KnowledgeGraphModel):
    pass


class KnowledgeGraphUserResponse(KnowledgeGraphUserModel):
    pass


class KnowledgeGraphSources(BaseModel):
    glossary_ids: list[str] = Field(default_factory=list)
    dbsphere_ids: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)


class KnowledgeGraphOptions(BaseModel):
    llm_model_id: Optional[str] = None
    tool_description_model_id: Optional[str] = None
    sync_mode: str = "manual"  # manual | nightly | realtime


class LinkSourceType:
    """지식 연결 Source 타입 — 단순화 후 glossary 하나."""

    GLOSSARY = "glossary"


class LinkTargetType:
    """지식 연결 Target 타입 — 단순화 후 knowledge 하나."""

    KNOWLEDGE = "knowledge"


class KnowledgeLinkForm(BaseModel):
    """지식 연결 생성/수정 폼 — 용어집 → KB(복수) 매핑."""

    glossary_id: str
    knowledge_ids: list[str] = Field(default_factory=list)


class KnowledgeGraphForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class KGNodeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    user_id: str
    node_type: str
    label: str
    properties: Optional[dict] = None
    source_ref: Optional[dict] = None
    created_at: int
    updated_at: int


class KGEdgeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    user_id: str
    src_id: str
    dst_id: str
    edge_type: str
    weight: Optional[float] = None
    properties: Optional[dict] = None
    source: str
    created_at: int


class KGCandidateModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    user_id: str
    candidate_type: str
    suggested_label: str
    target_node_id: Optional[str] = None
    properties: Optional[dict] = None
    status: str
    resolved_glossary_id: Optional[str] = None
    resolved_entry_id: Optional[str] = None
    created_at: int
    resolved_at: Optional[int] = None


class KGNeighborhoodNode(BaseModel):
    """`/neighbors` 응답 항목."""

    id: str
    label: str
    node_type: str
    depth: int


class JobKind:
    KB_EXTRACT = "kb_extract"
    KB_CLEANUP = "kb_cleanup"
    CANDIDATE_EXTRACT = "candidate_extract"
    SYNC_ALL = "sync_all"
    GLOSSARY_SYNC = "glossary_sync"


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class KGExtractJobModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    user_id: str
    kind: str
    status: str
    target_id: Optional[str] = None
    params: Optional[dict] = None
    progress_current: int = 0
    progress_total: int = 0
    progress_label: Optional[str] = None
    stats: Optional[dict] = None
    errors: Optional[list] = None
    created_at: int
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    last_heartbeat_at: Optional[int] = None


class KGExtractStateModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    kb_id: str
    processed_chunks: Optional[list[str]] = None
    last_run_at: Optional[int] = None
    last_model: Optional[str] = None
    updated_at: int


class KGAgePendingModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    operation: str
    payload: dict
    retries: int = 0
    created_at: int
    last_retry_at: Optional[int] = None


class KGKnowledgeLinkModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kg_id: str
    user_id: str
    source_type: str = "db_column"
    dbsphere_id: Optional[str] = None
    table_name: Optional[str] = None
    label_column: Optional[str] = None
    key_column: Optional[str] = None
    glossary_id: Optional[str] = None
    target_type: str = "knowledge"
    knowledge_ids: Optional[list[str]] = None
    target_dbsphere_id: Optional[str] = None
    target_table_name: Optional[str] = None
    target_column: Optional[str] = None
    edge_type: Optional[str] = None
    status: Optional[dict] = None
    config: Optional[dict] = None
    created_at: int
    updated_at: int


####################
# Helpers
####################


_SAFE_KEY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-="
)


def _safe_id_part(s: str, max_len: int = 64) -> str:
    """ID 단편을 Azure Search document key 규칙에 맞게 정규화.

    Azure AI Search는 document key에 letters/digits/`_`/`-`/`=`만 허용한다.
    한글·공백·특수문자가 들어가면 batch 전체가 거부된다.

    전략:
    - 이미 안전한 ASCII 단편(UUID, 영어 식별자 등)은 그대로 둔다.
      → 기존 prefix 기반 cleanup(`delete_nodes_by_source`)이 깨지지 않음.
    - 안전하지 않은 단편(한글, 공백 등)은 sanitize + 짧은 해시 suffix 부착.
      → 충돌 방지 + 결정적(같은 input → 같은 output).
    """
    if all(c in _SAFE_KEY_CHARS for c in s):
        return s[:max_len]
    sanitized = "".join(c if c in _SAFE_KEY_CHARS else "_" for c in s)
    digest = hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]
    return f"{sanitized[:max_len]}_{digest}"


def make_node_id(kg_id: str, source_kind: str, *parts: str) -> str:
    """결정적 노드 ID. 재동기화 idempotency 보장.

    각 part를 Azure Search document key 안전 형식으로 정규화한다.
    """
    suffix = "__".join(_safe_id_part(p) for p in parts)
    return f"{kg_id}__{source_kind}__{suffix}"


def make_edge_id(kg_id: str, src_id: str, dst_id: str, edge_type: str) -> str:
    """결정적 엣지 ID."""
    return f"{kg_id}__{edge_type}__{src_id}__{dst_id}"


####################
# CRUD
####################


class KnowledgeGraphTable:
    # ---- KG instances ----

    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(KnowledgeGraph).filter(KnowledgeGraph.name == name.strip())
            if exclude_id:
                query = query.filter(KnowledgeGraph.id != exclude_id)
            return query.first() is not None

    def insert_new_kg(
        self, user_id: str, form_data: KnowledgeGraphForm
    ) -> Optional[KnowledgeGraphModel]:
        with get_db() as db:
            kg = KnowledgeGraphModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = KnowledgeGraph(**kg.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                return KnowledgeGraphModel.model_validate(result) if result else None
            except Exception as e:
                log.exception(e)
                return None

    def get_kgs(self) -> list[KnowledgeGraphUserModel]:
        with get_db() as db:
            kgs = []
            for kg in (
                db.query(KnowledgeGraph)
                .order_by(KnowledgeGraph.updated_at.desc())
                .all()
            ):
                user = Users.get_user_by_id(kg.user_id)
                kgs.append(
                    KnowledgeGraphUserModel.model_validate(
                        {
                            **KnowledgeGraphModel.model_validate(kg).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return kgs

    def get_kgs_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[KnowledgeGraphUserModel]:
        kgs = self.get_kgs()
        return [
            kg
            for kg in kgs
            if kg.user_id == user_id
            or has_access(user_id, permission, kg.access_control)
        ]

    def get_kg_by_id(self, id: str) -> Optional[KnowledgeGraphModel]:
        try:
            with get_db() as db:
                kg = db.query(KnowledgeGraph).filter_by(id=id).first()
                return KnowledgeGraphModel.model_validate(kg) if kg else None
        except Exception:
            return None

    def update_kg_by_id(
        self, id: str, form_data: KnowledgeGraphForm
    ) -> Optional[KnowledgeGraphModel]:
        """KG 메타 업데이트.

        Note: `data` 필드가 form_data에 들어오면 통째로 replace하지 않고
        기존 data와 top-level 키 단위로 merge한다. 이렇게 안 하면 sync로
        저장된 `data.stats.last_synced_at`이 사용자가 sources를 save할
        때마다 사라지는 버그가 발생한다.
        """
        try:
            with get_db() as db:
                kg = db.query(KnowledgeGraph).filter_by(id=id).first()
                if not kg:
                    return None
                for key, value in form_data.model_dump(exclude_none=True).items():
                    if key == "data" and isinstance(value, dict):
                        merged = dict(kg.data or {})
                        merged.update(value)
                        setattr(kg, key, merged)
                    else:
                        setattr(kg, key, value)
                kg.updated_at = int(time.time())
                db.commit()
                db.refresh(kg)
                return KnowledgeGraphModel.model_validate(kg)
        except Exception as e:
            log.exception(e)
            return None

    def update_kg_data_by_id(
        self, id: str, data: dict
    ) -> Optional[KnowledgeGraphModel]:
        try:
            with get_db() as db:
                kg = db.query(KnowledgeGraph).filter_by(id=id).first()
                if not kg:
                    return None
                kg.data = data
                kg.updated_at = int(time.time())
                db.commit()
                db.refresh(kg)
                return KnowledgeGraphModel.model_validate(kg)
        except Exception as e:
            log.exception(e)
            return None

    # ---- Dynamic edge type registry (kg.meta.edge_types) ----

    def get_edge_types(self, kg_id: str) -> dict[str, dict]:
        """KG 에 현재까지 누적된 엣지 타입 레지스트리를 반환.

        구조: ``{edge_type_name: {description, examples, use_count, created_at, updated_at}}``
        비어있으면 빈 dict.
        """
        try:
            with get_db() as db:
                kg = db.query(KnowledgeGraph).filter_by(id=kg_id).first()
                if not kg:
                    return {}
                meta = dict(kg.meta or {})
                types = meta.get("edge_types") or {}
                return types if isinstance(types, dict) else {}
        except Exception:
            return {}

    def register_edge_type(
        self,
        kg_id: str,
        name: str,
        description: Optional[str] = None,
        example: Optional[str] = None,
        increment_use: int = 1,
        source: str = "llm",
    ) -> Optional[dict]:
        """엣지 타입을 KG 메타 레지스트리에 upsert.

        이미 있으면 use_count 증가 + updated_at 갱신, description/example 은
        **빈 경우에만** 채운다. 새로 등록이면 모든 필드 기록.
        동시성: 짧은 트랜잭션 내 read-modify-write — 청크 워커가 병렬로 호출해도
        마지막 write 가 이긴다 (use_count 가 약간 underflow 가능하지만 통계 용도라 허용).

        ``source`` 는 신규 항목 생성 시에만 적용 — 기존 항목의 source 는 보존.
        """
        if not name:
            return None
        try:
            with get_db() as db:
                kg = db.query(KnowledgeGraph).filter_by(id=kg_id).first()
                if not kg:
                    return None
                meta = dict(kg.meta or {})
                types = dict(meta.get("edge_types") or {})
                now = int(time.time())
                existing = dict(types.get(name) or {})
                if existing:
                    existing["use_count"] = (
                        int(existing.get("use_count") or 0) + increment_use
                    )
                    existing["updated_at"] = now
                    if description and not existing.get("description"):
                        existing["description"] = description
                    if example:
                        ex_list = list(existing.get("examples") or [])
                        if example not in ex_list and len(ex_list) < 5:
                            ex_list.append(example)
                            existing["examples"] = ex_list
                else:
                    existing = {
                        "name": name,
                        "display_name": name,
                        "description": description or "",
                        "examples": [example] if example else [],
                        "source": source,
                        "recommendation_reason": None,
                        "use_count": increment_use,
                        "created_at": now,
                        "updated_at": now,
                    }
                types[name] = existing
                meta["edge_types"] = types
                kg.meta = meta
                kg.updated_at = now
                db.commit()
                return existing
        except Exception as e:
            log.warning(f"[kg] register_edge_type failed ({name}): {e}")
            return None

    # ---- Per-link edge type catalog ----

    @staticmethod
    def _normalize_catalog_entry(name: str, raw: dict) -> dict:
        """카탈로그 항목을 응답 스키마로 정규화 (호환 필드 채움).

        - ``category``: intra-카테고리 전용 (한 카테고리 내부 속성)
        - ``src_category`` + ``dst_category``: cross-카테고리 (카테고리 간 관계)
        - 셋 다 없음: 범용/레거시 (모든 anchor 에 적용)
        """
        raw = dict(raw or {})
        return {
            "key": name,
            "name": name,
            "display_name": raw.get("display_name") or raw.get("name") or name,
            "description": raw.get("description") or "",
            "examples": list(raw.get("examples") or []),
            "source": raw.get("source") or "manual",
            "recommendation_reason": raw.get("recommendation_reason"),
            "category": raw.get("category"),
            "src_category": raw.get("src_category"),
            "dst_category": raw.get("dst_category"),
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
        }

    def get_link_edge_type_catalog(self, link_id: str) -> dict:
        """링크 단위 엣지 타입 카탈로그 + locked 플래그 + 추천 모델 반환.

        반환: ``{"items": [...], "locked": bool, "recommend_model_id": str|None}``
        """
        try:
            with get_db() as db:
                link = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
                if not link:
                    return {
                        "items": [],
                        "locked": False,
                        "recommend_model_id": None,
                    }
                config = dict(link.config or {})
                types = config.get("edge_types") or {}
                if not isinstance(types, dict):
                    types = {}
                items = [
                    self._normalize_catalog_entry(name, raw)
                    for name, raw in types.items()
                    if isinstance(raw, dict)
                ]
                items.sort(key=lambda x: x["key"])
                # locked 은 명시 저장된 경우에만 bool 반환, 미설정은 None
                # (프론트가 "기본값" 결정을 할 수 있도록)
                raw_locked = config.get("edge_types_locked")
                locked_val = bool(raw_locked) if raw_locked is not None else None
                return {
                    "items": items,
                    "locked": locked_val,
                    "recommend_model_id": config.get("recommend_model_id") or None,
                }
        except Exception as e:
            log.warning(f"[kg] get_link_edge_type_catalog failed ({link_id}): {e}")
            return {"items": [], "locked": None, "recommend_model_id": None}

    def replace_link_edge_type_catalog(
        self,
        link_id: str,
        items: list[dict],
        locked: bool,
        recommend_model_id: Optional[str] = None,
    ) -> Optional[dict]:
        """링크 카탈로그 전체 교체. 기존 항목의 created_at 은 키 매칭 시 보존.

        ``recommend_model_id`` 가 None 이면 기존 값 유지, 빈 문자열이면 clear.
        """
        try:
            with get_db() as db:
                link = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
                if not link:
                    return None
                config = dict(link.config or {})
                old = dict(config.get("edge_types") or {})
                now = int(time.time())
                new_types: dict[str, dict] = {}
                for item in items or []:
                    key = (item.get("key") or item.get("name") or "").strip()
                    if not key:
                        continue
                    prev = dict(old.get(key) or {})
                    new_types[key] = {
                        "name": key,
                        "display_name": (
                            item.get("display_name") or item.get("name") or key
                        ),
                        "description": item.get("description") or "",
                        "examples": list(
                            item.get("examples") or prev.get("examples") or []
                        ),
                        "source": item.get("source") or prev.get("source") or "manual",
                        "recommendation_reason": item.get("recommendation_reason"),
                        "category": item.get("category") or prev.get("category"),
                        "src_category": item.get("src_category")
                        or prev.get("src_category"),
                        "dst_category": item.get("dst_category")
                        or prev.get("dst_category"),
                        "created_at": prev.get("created_at") or now,
                        "updated_at": now,
                    }
                config["edge_types"] = new_types
                config["edge_types_locked"] = bool(locked)
                if recommend_model_id is not None:
                    if recommend_model_id:
                        config["recommend_model_id"] = recommend_model_id
                    else:
                        config.pop("recommend_model_id", None)
                link.config = config
                link.updated_at = now
                db.commit()
                return self.get_link_edge_type_catalog(link_id)
        except Exception as e:
            log.warning(f"[kg] replace_link_edge_type_catalog failed ({link_id}): {e}")
            return None

    def get_link_node_filters(self, link_id: str) -> dict:
        """링크 단위 "노드로 추출할 KB 필터 slot" 선택 목록 + 캐시된 엣지 이름 맵.

        반환: ``{"slots": [{"kb_id", "slot"}, ...], "edge_names": {"kb_id::slot": "has_xxx"}}``.
        저장 전(null) 과 빈 리스트 모두 빈 slots 반환.
        """
        try:
            with get_db() as db:
                link = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
                if not link:
                    return {"slots": [], "edge_names": {}}
                config = link.config or {}
                raw = config.get("extracted_filter_slots") or []
                slots: list[dict] = []
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    kb_id = entry.get("kb_id")
                    slot = entry.get("slot")
                    if (
                        isinstance(kb_id, str)
                        and isinstance(slot, str)
                        and kb_id
                        and slot
                    ):
                        slots.append({"kb_id": kb_id, "slot": slot})
                edge_names_raw = config.get("filter_edge_names") or {}
                edge_names: dict[str, str] = {}
                if isinstance(edge_names_raw, dict):
                    for k, v in edge_names_raw.items():
                        if isinstance(k, str) and isinstance(v, str) and k and v:
                            edge_names[k] = v
                return {"slots": slots, "edge_names": edge_names}
        except Exception as e:
            log.warning(f"[kg] get_link_node_filters failed ({link_id}): {e}")
            return {"slots": [], "edge_names": {}}

    def replace_link_node_filters(
        self,
        link_id: str,
        slots: list[dict],
        edge_names: Optional[dict] = None,
    ) -> Optional[dict]:
        """링크의 `config.extracted_filter_slots` + `config.filter_edge_names` 교체.

        slots: ``[{"kb_id", "slot"}, ...]``. 유효한 항목만 필터링해서 저장.
        링크의 현재 knowledge_ids 에 속하지 않는 kb_id 는 drop.

        edge_names: ``{"kb_id::slot": "has_xxx", ...}`` — 라우터에서 LLM 제안 +
        규칙 기반으로 미리 계산한 결과. 없으면 기존 값 유지.
        """
        try:
            with get_db() as db:
                link = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
                if not link:
                    return None
                valid_kb_ids = set(link.knowledge_ids or [])
                clean: list[dict] = []
                seen: set[tuple[str, str]] = set()
                for entry in slots or []:
                    if not isinstance(entry, dict):
                        continue
                    kb_id = entry.get("kb_id")
                    slot = entry.get("slot")
                    if not isinstance(kb_id, str) or not isinstance(slot, str):
                        continue
                    if not kb_id or not slot:
                        continue
                    if valid_kb_ids and kb_id not in valid_kb_ids:
                        continue
                    key = (kb_id, slot)
                    if key in seen:
                        continue
                    seen.add(key)
                    clean.append({"kb_id": kb_id, "slot": slot})
                config = dict(link.config or {})
                config["extracted_filter_slots"] = clean
                if edge_names is not None:
                    # 유효한 slot 에 해당하는 이름만 유지 (나머지는 정리)
                    valid_keys = {f"{e['kb_id']}::{e['slot']}" for e in clean}
                    cleaned_names: dict[str, str] = {}
                    for k, v in (edge_names or {}).items():
                        if k in valid_keys and isinstance(v, str) and v:
                            cleaned_names[k] = v
                    config["filter_edge_names"] = cleaned_names
                link.config = config
                link.updated_at = int(time.time())
                db.commit()
                return {
                    "slots": clean,
                    "edge_names": config.get("filter_edge_names") or {},
                }
        except Exception as e:
            log.warning(f"[kg] replace_link_node_filters failed ({link_id}): {e}")
            return None

    def delete_kg_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                # 자식 테이블 모두 정리 (orphan 방지)
                db.query(KGEdge).filter_by(kg_id=id).delete()
                db.query(KGNode).filter_by(kg_id=id).delete()
                db.query(KGCandidate).filter_by(kg_id=id).delete()
                db.query(KGExtractJob).filter_by(kg_id=id).delete()
                db.query(KGExtractState).filter_by(kg_id=id).delete()
                kg = db.query(KnowledgeGraph).filter_by(id=id).first()
                if kg:
                    db.delete(kg)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    # ---- Nodes ----

    def upsert_node(
        self,
        kg_id: str,
        user_id: str,
        node_id: str,
        node_type: str,
        label: str,
        properties: Optional[dict] = None,
        source_ref: Optional[dict] = None,
    ) -> Optional[KGNodeModel]:
        """노드 upsert — race-safe.

        결정적 id 를 가진 여러 워커가 동시에 같은 노드를 upsert 하면
        `SELECT → INSERT` 패턴은 race 에서 IntegrityError 를 낸다. PG 의
        `INSERT ... ON CONFLICT DO UPDATE` 로 원자적 처리해서 여러 워커가
        동시에 같은 node_id 를 upsert 해도 안전하게 만든다. SQLite 는
        `INSERT OR REPLACE` (on conflict do update) 로 동일하게 동작.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        now = int(time.time())
        values = {
            "id": node_id,
            "kg_id": kg_id,
            "user_id": user_id,
            "node_type": node_type,
            "label": label,
            "properties": properties,
            "source_ref": source_ref,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with get_db() as db:
                dialect = db.bind.dialect.name
                if dialect == "postgresql":
                    stmt = pg_insert(KGNode).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "label": stmt.excluded.label,
                            "node_type": stmt.excluded.node_type,
                            "properties": stmt.excluded.properties,
                            "source_ref": stmt.excluded.source_ref,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    db.execute(stmt)
                elif dialect == "sqlite":
                    stmt = sqlite_insert(KGNode).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "label": stmt.excluded.label,
                            "node_type": stmt.excluded.node_type,
                            "properties": stmt.excluded.properties,
                            "source_ref": stmt.excluded.source_ref,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    db.execute(stmt)
                else:
                    # 알 수 없는 dialect — fallback 은 기존 SELECT+INSERT/UPDATE
                    existing = db.query(KGNode).filter_by(id=node_id).first()
                    if existing:
                        existing.label = label
                        existing.node_type = node_type
                        existing.properties = properties
                        existing.source_ref = source_ref
                        existing.updated_at = now
                    else:
                        db.add(KGNode(**values))
                db.commit()
                row = db.query(KGNode).filter_by(id=node_id).first()
                return KGNodeModel.model_validate(row) if row else None
        except Exception as e:
            log.exception(e)
            return None

    def get_nodes(
        self,
        kg_id: str,
        node_type: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KGNodeModel]:
        """KG 노드 목록 — 타입/검색어 필터 + 서버 사이드 페이징.

        ``q`` 가 주어지면 label 에 대해 case-insensitive 부분 일치(LIKE) 검색.
        대량 노드를 가진 KG 에서 클라이언트 페이징이 첫 페이지에서 특정 타입을
        놓치는 문제를 피하기 위해 항상 서버에서 필터링한다.
        """
        from sqlalchemy import func

        with get_db() as db:
            query = db.query(KGNode).filter_by(kg_id=kg_id)
            if node_type:
                query = query.filter_by(node_type=node_type)
            if q:
                pattern = f"%{q.strip().lower()}%"
                if pattern != "%%":
                    query = query.filter(func.lower(KGNode.label).like(pattern))
            rows = query.order_by(KGNode.label).offset(offset).limit(limit).all()
            return [KGNodeModel.model_validate(r) for r in rows]

    def count_nodes(
        self,
        kg_id: str,
        node_type: Optional[str] = None,
        q: Optional[str] = None,
    ) -> int:
        """`get_nodes` 와 동일한 필터 조건의 총 개수 — 페이지네이션 UI 용."""
        from sqlalchemy import func

        with get_db() as db:
            query = db.query(KGNode).filter_by(kg_id=kg_id)
            if node_type:
                query = query.filter_by(node_type=node_type)
            if q:
                pattern = f"%{q.strip().lower()}%"
                if pattern != "%%":
                    query = query.filter(func.lower(KGNode.label).like(pattern))
            return query.count()

    def find_nodes_by_label_ci(
        self,
        kg_id: str,
        label: str,
        node_types: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[KGNodeModel]:
        """라벨 정확 매칭(case-insensitive) 으로 노드 검색.

        `tools.KGToolManager._find_term_nodes_by_label` 가 매 도구 호출마다
        `get_nodes(limit=500)` 로 한 KG 당 최대 1000~2500 행을 fetch 한 뒤
        Python 에서 비교하던 핫패스를 SQL 로 푸시하기 위해 추가.

        `kg_node_kg_label_idx` 인덱스가 (kg_id, label) 에 걸려 있으므로 SQL
        레벨에서 효율적으로 처리되며 저장된 라벨이 이미 대소문자가 일정하면
        단일 row 만 반환된다. label 에 대해 lower() 를 양쪽에 적용하므로
        대소문자 무시 매칭이 보장된다.
        """
        from sqlalchemy import func

        target = label.strip().lower()
        if not target:
            return []
        with get_db() as db:
            query = db.query(KGNode).filter(KGNode.kg_id == kg_id)
            if node_types:
                query = query.filter(KGNode.node_type.in_(node_types))
            query = query.filter(func.lower(KGNode.label) == target)
            rows = query.limit(limit).all()
            return [KGNodeModel.model_validate(r) for r in rows]

    def get_node_by_id(self, node_id: str) -> Optional[KGNodeModel]:
        with get_db() as db:
            node = db.query(KGNode).filter_by(id=node_id).first()
            return KGNodeModel.model_validate(node) if node else None

    def get_nodes_by_source(
        self,
        kg_id: str,
        source_kind: str,
        source_id: str,
        limit: int = 5000,
    ) -> list[KGNodeModel]:
        """특정 source(예: 특정 KB)에서 만들어진 모든 노드를 prefix 매칭으로 fetch.

        node_id 형식: `{kg_id}__{kind}__{source_id}__...` 라서 prefix LIKE로 조회.
        KB 부분 cleanup(삭제된 청크 정리)에 사용.
        """
        prefix = f"{kg_id}__{source_kind}__{source_id}__"
        with get_db() as db:
            rows = (
                db.query(KGNode)
                .filter(KGNode.kg_id == kg_id)
                .filter(KGNode.id.like(f"{prefix}%"))
                .order_by(KGNode.label)
                .limit(limit)
                .all()
            )
            return [KGNodeModel.model_validate(r) for r in rows]

    def delete_node_by_id(self, node_id: str) -> bool:
        """단일 노드 + 관련 엣지를 모두 삭제 (양방향).

        manual 엣지든 auto 엣지든 모두 삭제한다 — 노드가 사라지는 것이므로
        엣지가 dangling 상태로 남는 게 더 위험하다.
        """
        try:
            with get_db() as db:
                node = db.query(KGNode).filter_by(id=node_id).first()
                if not node:
                    return False
                db.query(KGEdge).filter(
                    or_(KGEdge.src_id == node_id, KGEdge.dst_id == node_id)
                ).delete(synchronize_session=False)
                db.delete(node)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def get_distinct_source_ids(self, kg_id: str, source_kind: str) -> list[str]:
        """KG 내 노드 ID 접두사에서 특정 source_kind의 distinct source_id 추출.

        node_id 형식: `{kg_id}__{kind}__{source_id}__...`. 재동기화 시
        detach된 소스를 찾기 위해 사용한다.
        """
        prefix = f"{kg_id}__{source_kind}__"
        prefix_len = len(prefix)
        with get_db() as db:
            rows = (
                db.query(KGNode.id)
                .filter(KGNode.kg_id == kg_id)
                .filter(KGNode.id.like(f"{prefix}%"))
                .all()
            )
        seen: set[str] = set()
        for row in rows:
            tail = row.id[prefix_len:]
            sep = tail.find("__")
            if sep > 0:
                seen.add(tail[:sep])
        return sorted(seen)

    def delete_nodes_by_source(
        self,
        kg_id: str,
        source_kind: str,
        source_id: str,
        include_manual_edges: bool = False,
    ) -> int:
        """특정 소스에서 온 노드를 모두 삭제 (재동기화 시 cleanup).

        기본(`include_manual_edges=False`):
            manual(사용자 큐레이션) 엣지는 삭제하지 않는다. 노드 ID가 결정적이라
            재동기화로 같은 ID의 노드가 다시 생성되면 manual 엣지는 자연스럽게
            다시 붙는다. 자동 sync로 만들어진 엣지만 정리.

        `include_manual_edges=True`:
            소스가 KG에서 *완전히 분리(detach)*된 경우 사용. 노드가 다시 생성될
            일이 없으므로 dangling manual 엣지를 남겨두면 mappings/graph에
            null 참조가 노출된다. detach 시점에 같이 정리한다.
        """
        prefix = f"{kg_id}__{source_kind}__{source_id}__"
        with get_db() as db:
            ids = [
                row.id
                for row in db.query(KGNode.id)
                .filter(KGNode.kg_id == kg_id)
                .filter(KGNode.id.like(f"{prefix}%"))
                .all()
            ]
            if not ids:
                return 0
            edge_q = db.query(KGEdge).filter(
                KGEdge.kg_id == kg_id,
                or_(KGEdge.src_id.in_(ids), KGEdge.dst_id.in_(ids)),
            )
            if not include_manual_edges:
                edge_q = edge_q.filter(KGEdge.source != EdgeSource.MANUAL)
            edge_q.delete(synchronize_session=False)
            db.query(KGNode).filter(KGNode.id.in_(ids)).delete(
                synchronize_session=False
            )
            db.commit()
            return len(ids)

    # ---- Edges ----

    def upsert_edge(
        self,
        kg_id: str,
        user_id: str,
        src_id: str,
        dst_id: str,
        edge_type: str,
        source: str,
        weight: Optional[float] = None,
        properties: Optional[dict] = None,
    ) -> Optional[KGEdgeModel]:
        """엣지 upsert — race-safe. `upsert_node` 와 동일한 ON CONFLICT 패턴."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        if src_id == dst_id:
            return None
        edge_id = make_edge_id(kg_id, src_id, dst_id, edge_type)
        now = int(time.time())
        values = {
            "id": edge_id,
            "kg_id": kg_id,
            "user_id": user_id,
            "src_id": src_id,
            "dst_id": dst_id,
            "edge_type": edge_type,
            "weight": weight,
            "properties": properties,
            "source": source,
            "created_at": now,
        }
        try:
            with get_db() as db:
                dialect = db.bind.dialect.name
                if dialect == "postgresql":
                    stmt = pg_insert(KGEdge).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "weight": stmt.excluded.weight,
                            "properties": stmt.excluded.properties,
                            "source": stmt.excluded.source,
                        },
                    )
                    db.execute(stmt)
                elif dialect == "sqlite":
                    stmt = sqlite_insert(KGEdge).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "weight": stmt.excluded.weight,
                            "properties": stmt.excluded.properties,
                            "source": stmt.excluded.source,
                        },
                    )
                    db.execute(stmt)
                else:
                    existing = db.query(KGEdge).filter_by(id=edge_id).first()
                    if existing:
                        existing.weight = weight
                        existing.properties = properties
                        existing.source = source
                    else:
                        db.add(KGEdge(**values))
                db.commit()
                row = db.query(KGEdge).filter_by(id=edge_id).first()
                return KGEdgeModel.model_validate(row) if row else None
        except Exception as e:
            log.exception(e)
            return None

    def bulk_upsert_nodes(self, specs: list[dict]) -> int:
        """노드 여러 개를 한 트랜잭션/단일 SQL 로 upsert.

        specs: 각 항목은 ``upsert_node`` 인자와 동일한 키:
            id, kg_id, user_id, node_type, label, properties, source_ref.

        같은 id 가 여러 번 들어오면 나중 값이 승리하도록 dedup — PG
        ``INSERT ... ON CONFLICT`` 는 같은 statement 안에서 같은 row 에
        두 번 action 적용 불가.

        Returns: 실제 DB 에 반영된 고유 id 수.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        if not specs:
            return 0

        now = int(time.time())
        dedup: dict[str, dict] = {}
        for s in specs:
            nid = s["id"]
            dedup[nid] = {
                "id": nid,
                "kg_id": s["kg_id"],
                "user_id": s["user_id"],
                "node_type": s["node_type"],
                "label": s["label"],
                "properties": s.get("properties"),
                "source_ref": s.get("source_ref"),
                "created_at": now,
                "updated_at": now,
            }
        values = list(dedup.values())
        try:
            with get_db() as db:
                dialect = db.bind.dialect.name
                if dialect == "postgresql":
                    stmt = pg_insert(KGNode).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "label": stmt.excluded.label,
                            "node_type": stmt.excluded.node_type,
                            "properties": stmt.excluded.properties,
                            "source_ref": stmt.excluded.source_ref,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    db.execute(stmt)
                elif dialect == "sqlite":
                    stmt = sqlite_insert(KGNode).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "label": stmt.excluded.label,
                            "node_type": stmt.excluded.node_type,
                            "properties": stmt.excluded.properties,
                            "source_ref": stmt.excluded.source_ref,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    db.execute(stmt)
                else:
                    for v in values:
                        existing = db.query(KGNode).filter_by(id=v["id"]).first()
                        if existing:
                            existing.label = v["label"]
                            existing.node_type = v["node_type"]
                            existing.properties = v["properties"]
                            existing.source_ref = v["source_ref"]
                            existing.updated_at = now
                        else:
                            db.add(KGNode(**v))
                db.commit()
                return len(values)
        except Exception as e:
            log.exception(f"bulk_upsert_nodes failed ({len(values)} specs): {e}")
            return 0

    def bulk_upsert_edges(self, specs: list[dict]) -> int:
        """엣지 여러 개를 한 트랜잭션/단일 SQL 로 upsert.

        specs: 각 항목은 ``upsert_edge`` 인자와 동일한 키:
            kg_id, user_id, src_id, dst_id, edge_type, source, weight, properties.

        id 는 ``make_edge_id(kg_id, src, dst, type)`` 로 자동 계산.
        self-loop (src_id == dst_id) 는 skip.
        같은 (src, dst, type) 는 나중 값 승리.

        Returns: 실제 DB 에 반영된 고유 edge_id 수.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        if not specs:
            return 0

        now = int(time.time())
        dedup: dict[str, dict] = {}
        for s in specs:
            src_id = s["src_id"]
            dst_id = s["dst_id"]
            if src_id == dst_id:
                continue
            edge_id = make_edge_id(s["kg_id"], src_id, dst_id, s["edge_type"])
            dedup[edge_id] = {
                "id": edge_id,
                "kg_id": s["kg_id"],
                "user_id": s["user_id"],
                "src_id": src_id,
                "dst_id": dst_id,
                "edge_type": s["edge_type"],
                "weight": s.get("weight"),
                "properties": s.get("properties"),
                "source": s["source"],
                "created_at": now,
            }
        if not dedup:
            return 0
        values = list(dedup.values())
        try:
            with get_db() as db:
                dialect = db.bind.dialect.name
                if dialect == "postgresql":
                    stmt = pg_insert(KGEdge).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "weight": stmt.excluded.weight,
                            "properties": stmt.excluded.properties,
                            "source": stmt.excluded.source,
                        },
                    )
                    db.execute(stmt)
                elif dialect == "sqlite":
                    stmt = sqlite_insert(KGEdge).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "weight": stmt.excluded.weight,
                            "properties": stmt.excluded.properties,
                            "source": stmt.excluded.source,
                        },
                    )
                    db.execute(stmt)
                else:
                    for v in values:
                        existing = db.query(KGEdge).filter_by(id=v["id"]).first()
                        if existing:
                            existing.weight = v["weight"]
                            existing.properties = v["properties"]
                            existing.source = v["source"]
                        else:
                            db.add(KGEdge(**v))
                db.commit()
                return len(values)
        except Exception as e:
            log.exception(f"bulk_upsert_edges failed ({len(values)} specs): {e}")
            return 0

    def count_edges(self, kg_id: str) -> int:
        with get_db() as db:
            return db.query(KGEdge).filter_by(kg_id=kg_id).count()

    def get_distinct_edge_types(self, kg_id: str) -> list[tuple[str, int]]:
        """KG 에 실제 존재하는 edge_type 목록 (distinct + count, 사용 빈도 desc).

        kg.meta.edge_types 레지스트리는 LLM 추출 단계의 카운터라 stale 가능성이
        있어, 실제 kg_edge 테이블에서 distinct 로 직접 가져온다.
        """
        from sqlalchemy import func

        with get_db() as db:
            rows = (
                db.query(KGEdge.edge_type, func.count(KGEdge.id))
                .filter(KGEdge.kg_id == kg_id)
                .group_by(KGEdge.edge_type)
                .order_by(func.count(KGEdge.id).desc())
                .all()
            )
            return [(r[0], int(r[1])) for r in rows]

    def get_edges_paginated(
        self,
        kg_id: str,
        edge_type: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KGEdgeModel]:
        """페이징 엣지 조회 + 좌측 패널 검색용.

        q 가 주어지면 src/dst 노드의 label 또는 edge_type 에 substring 매치.
        검색은 join 으로 처리 (src/dst 노드 라벨까지 보기 위해).
        """
        from sqlalchemy import or_

        with get_db() as db:
            query = db.query(KGEdge).filter(KGEdge.kg_id == kg_id)
            if edge_type:
                query = query.filter(KGEdge.edge_type == edge_type)
            if q:
                # src/dst 노드 라벨로 필터 — 두 alias 로 join
                src_alias = KGNode.__table__.alias("src_n")
                dst_alias = KGNode.__table__.alias("dst_n")
                query = (
                    query.join(src_alias, KGEdge.src_id == src_alias.c.id)
                    .join(dst_alias, KGEdge.dst_id == dst_alias.c.id)
                    .filter(
                        or_(
                            src_alias.c.label.ilike(f"%{q}%"),
                            dst_alias.c.label.ilike(f"%{q}%"),
                            KGEdge.edge_type.ilike(f"%{q}%"),
                        )
                    )
                )
            rows = (
                query.order_by(KGEdge.created_at.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            return [KGEdgeModel.model_validate(r) for r in rows]

    def count_edges_filtered(
        self,
        kg_id: str,
        edge_type: Optional[str] = None,
        q: Optional[str] = None,
    ) -> int:
        from sqlalchemy import or_

        with get_db() as db:
            query = db.query(KGEdge).filter(KGEdge.kg_id == kg_id)
            if edge_type:
                query = query.filter(KGEdge.edge_type == edge_type)
            if q:
                src_alias = KGNode.__table__.alias("src_n")
                dst_alias = KGNode.__table__.alias("dst_n")
                query = (
                    query.join(src_alias, KGEdge.src_id == src_alias.c.id)
                    .join(dst_alias, KGEdge.dst_id == dst_alias.c.id)
                    .filter(
                        or_(
                            src_alias.c.label.ilike(f"%{q}%"),
                            dst_alias.c.label.ilike(f"%{q}%"),
                            KGEdge.edge_type.ilike(f"%{q}%"),
                        )
                    )
                )
            return query.count()

    def get_all_edges(
        self,
        kg_id: str,
        edge_types: Optional[list[str]] = None,
        limit: int = 5000,
    ) -> list[KGEdgeModel]:
        """KG의 모든 엣지 (시각화용 batch fetch)."""
        with get_db() as db:
            query = db.query(KGEdge).filter_by(kg_id=kg_id)
            if edge_types:
                query = query.filter(KGEdge.edge_type.in_(edge_types))
            rows = query.limit(limit).all()
            return [KGEdgeModel.model_validate(r) for r in rows]

    def get_edges_for_node_set(
        self,
        kg_id: str,
        node_ids: set[str],
        edge_types: Optional[list[str]] = None,
        limit: int = 10000,
    ) -> list[KGEdgeModel]:
        """양 endpoint 가 모두 `node_ids` 에 포함되는 엣지만 반환.

        그래프 시각화(`get_kg_graph`)에서 기존 방식은 전체 엣지를 over-fetch 한
        뒤 Python 에서 필터했다. 이 메서드는 SQL 에서 src_id IN (...) AND
        dst_id IN (...) 으로 바로 좁혀 round-trip + 불필요한 row 전송을 줄인다.
        """
        if not node_ids:
            return []
        id_list = list(node_ids)
        with get_db() as db:
            query = db.query(KGEdge).filter(
                KGEdge.kg_id == kg_id,
                KGEdge.src_id.in_(id_list),
                KGEdge.dst_id.in_(id_list),
            )
            if edge_types:
                query = query.filter(KGEdge.edge_type.in_(edge_types))
            rows = query.limit(limit).all()
            return [KGEdgeModel.model_validate(r) for r in rows]

    def get_edges_touching_nodes(
        self,
        kg_id: str,
        node_ids: set[str],
        edge_types: Optional[list[str]] = None,
        limit: int = 10000,
    ) -> list[KGEdgeModel]:
        """한쪽 endpoint 라도 `node_ids` 에 속하면 매칭되는 엣지를 반환.

        priority_node_type 그래프 뷰에서 anchor 노드의 1-hop 이웃을 확장할 때
        사용한다. `get_edges_for_node_set` 은 양쪽 모두 안에 있어야 하므로
        이웃 발견에는 부적합.
        """
        if not node_ids:
            return []
        id_list = list(node_ids)
        with get_db() as db:
            query = db.query(KGEdge).filter(
                KGEdge.kg_id == kg_id,
                or_(KGEdge.src_id.in_(id_list), KGEdge.dst_id.in_(id_list)),
            )
            if edge_types:
                query = query.filter(KGEdge.edge_type.in_(edge_types))
            rows = query.limit(limit).all()
            return [KGEdgeModel.model_validate(r) for r in rows]

    def get_nodes_by_ids(
        self,
        kg_id: str,
        node_ids: list[str],
        limit: int = 5000,
    ) -> list[KGNodeModel]:
        """주어진 ID 들에 해당하는 노드를 한 번에 fetch.

        그래프 priority view 에서 anchor 의 이웃 노드들을 ID 로 끌어올 때 사용.
        """
        if not node_ids:
            return []
        with get_db() as db:
            rows = (
                db.query(KGNode)
                .filter(KGNode.kg_id == kg_id, KGNode.id.in_(node_ids))
                .order_by(KGNode.label)
                .limit(limit)
                .all()
            )
            return [KGNodeModel.model_validate(r) for r in rows]

    def get_edge_by_id(self, edge_id: str) -> Optional[KGEdgeModel]:
        try:
            with get_db() as db:
                edge = db.query(KGEdge).filter_by(id=edge_id).first()
                return KGEdgeModel.model_validate(edge) if edge else None
        except Exception as e:
            log.exception(e)
            return None

    def delete_edge_by_id(self, edge_id: str) -> bool:
        try:
            with get_db() as db:
                edge = db.query(KGEdge).filter_by(id=edge_id).first()
                if not edge:
                    return False
                db.delete(edge)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def get_edges_for_node(
        self,
        kg_id: str,
        node_id: str,
        edge_types: Optional[list[str]] = None,
    ) -> list[KGEdgeModel]:
        """주어진 노드를 src 또는 dst로 가지는 모든 엣지."""
        with get_db() as db:
            query = db.query(KGEdge).filter(
                KGEdge.kg_id == kg_id,
                or_(KGEdge.src_id == node_id, KGEdge.dst_id == node_id),
            )
            if edge_types:
                query = query.filter(KGEdge.edge_type.in_(edge_types))
            return [KGEdgeModel.model_validate(e) for e in query.all()]

    def get_manual_edges_with_nodes(
        self,
        kg_id: str,
        edge_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """`source='manual'` 엣지 + 양 endpoint 노드 정보를 한 번에 반환.

        UI에서 매핑 리스트를 표시할 때 N+1 쿼리를 피하기 위해 단일 fetch.
        """
        with get_db() as db:
            edge_query = db.query(KGEdge).filter(
                KGEdge.kg_id == kg_id,
                KGEdge.source == EdgeSource.MANUAL,
            )
            if edge_types:
                edge_query = edge_query.filter(KGEdge.edge_type.in_(edge_types))
            edges = edge_query.order_by(KGEdge.created_at.desc()).all()
            if not edges:
                return []

            # 양 endpoint 노드를 한 번에 fetch
            node_ids = set()
            for e in edges:
                node_ids.add(e.src_id)
                node_ids.add(e.dst_id)
            node_rows = db.query(KGNode).filter(KGNode.id.in_(list(node_ids))).all()
            node_by_id = {n.id: n for n in node_rows}

            results: list[dict] = []
            for e in edges:
                src = node_by_id.get(e.src_id)
                dst = node_by_id.get(e.dst_id)
                results.append(
                    {
                        "edge": KGEdgeModel.model_validate(e),
                        "src_node": (KGNodeModel.model_validate(src) if src else None),
                        "dst_node": (KGNodeModel.model_validate(dst) if dst else None),
                    }
                )
            return results

    # ---- Traversal ----

    def get_neighbors(
        self,
        kg_id: str,
        node_id: str,
        hops: int = 1,
        edge_types: Optional[list[str]] = None,
        limit: int = 200,
    ) -> list[KGNeighborhoodNode]:
        """N-hop BFS 트래버설.

        PostgreSQL 인 경우 WITH RECURSIVE CTE 로 한 번의 쿼리로 처리하고,
        SQLite 등 나머지 엔진은 Python ORM BFS fallback 을 사용한다.
        """
        if hops < 1:
            return []

        with get_db() as db:
            dialect = db.bind.dialect.name if db.bind else "unknown"
            if dialect == "postgresql":
                return self._get_neighbors_cte(
                    db, kg_id, node_id, hops, edge_types, limit
                )
            return self._get_neighbors_orm(db, kg_id, node_id, hops, edge_types, limit)

    @staticmethod
    def _get_neighbors_cte(
        db,
        kg_id: str,
        node_id: str,
        hops: int,
        edge_types: Optional[list[str]],
        limit: int,
    ) -> list[KGNeighborhoodNode]:
        """PostgreSQL WITH RECURSIVE — hops>2 에서 10~100× 빠름."""
        from sqlalchemy import text

        # edge_type 필터 절 (없으면 빈 문자열)
        et_filter = ""
        params: dict = {
            "kg_id": kg_id,
            "start_id": node_id,
            "max_depth": hops,
            "limit": limit,
        }
        if edge_types:
            placeholders = ", ".join(f":et{i}" for i in range(len(edge_types)))
            et_filter = f"AND e.edge_type IN ({placeholders})"
            for i, et in enumerate(edge_types):
                params[f"et{i}"] = et

        sql = text(f"""
            WITH RECURSIVE neighbors AS (
                SELECT :start_id AS nid, 0 AS depth
                UNION
                SELECT
                    CASE WHEN e.src_id = nb.nid THEN e.dst_id ELSE e.src_id END,
                    nb.depth + 1
                FROM neighbors nb
                JOIN kg_edge e
                    ON e.kg_id = :kg_id
                    AND (e.src_id = nb.nid OR e.dst_id = nb.nid)
                    {et_filter}
                WHERE nb.depth < :max_depth
            )
            SELECT DISTINCT ON (n.id) n.id, n.label, n.node_type, nb.depth
            FROM neighbors nb
            JOIN kg_node n ON n.id = nb.nid AND n.kg_id = :kg_id
            WHERE nb.nid != :start_id AND nb.depth > 0
            ORDER BY n.id, nb.depth
            LIMIT :limit
        """)

        rows = db.execute(sql, params).fetchall()
        return [
            KGNeighborhoodNode(id=r[0], label=r[1], node_type=r[2], depth=r[3])
            for r in rows
        ]

    @staticmethod
    def _get_neighbors_orm(
        db,
        kg_id: str,
        node_id: str,
        hops: int,
        edge_types: Optional[list[str]],
        limit: int,
    ) -> list[KGNeighborhoodNode]:
        """ORM BFS fallback (SQLite 등)."""
        visited: dict[str, int] = {}  # node_id → depth
        frontier: list[str] = [node_id]
        visited[node_id] = 0

        for depth in range(1, hops + 1):
            if not frontier:
                break

            query = db.query(KGEdge).filter(
                KGEdge.kg_id == kg_id,
                or_(
                    KGEdge.src_id.in_(frontier),
                    KGEdge.dst_id.in_(frontier),
                ),
            )
            if edge_types:
                query = query.filter(KGEdge.edge_type.in_(edge_types))

            next_frontier: set[str] = set()
            for edge in query.all():
                for nid in (edge.src_id, edge.dst_id):
                    if nid not in visited:
                        visited[nid] = depth
                        next_frontier.add(nid)
                        if len(visited) >= limit + 1:  # +1 for start
                            break
                if len(visited) >= limit + 1:
                    break
            frontier = list(next_frontier)

        # 시작 노드 제외
        visited.pop(node_id, None)
        if not visited:
            return []

        nodes = db.query(KGNode).filter(KGNode.id.in_(list(visited.keys()))).all()
        return [
            KGNeighborhoodNode(
                id=n.id,
                label=n.label,
                node_type=n.node_type,
                depth=visited[n.id],
            )
            for n in nodes
        ]

    # ---- Candidates (Slice 6) ----

    def insert_candidate(
        self,
        kg_id: str,
        user_id: str,
        candidate_type: str,
        suggested_label: str,
        target_node_id: Optional[str] = None,
        properties: Optional[dict] = None,
    ) -> Optional[KGCandidateModel]:
        """후보 추가 — DB 레벨 dedup 포함.

        같은 (kg_id, suggested_label, target_node_id, status='pending') 조합이
        이미 있으면 새로 만들지 않고 기존 것 반환.
        """
        try:
            with get_db() as db:
                # Cross-call dedup: 같은 label+target 조합의 pending 후보 존재 시 skip
                dedup_filter = {
                    "kg_id": kg_id,
                    "suggested_label": suggested_label,
                    "status": CandidateStatus.PENDING,
                }
                if target_node_id:
                    dedup_filter["target_node_id"] = target_node_id
                existing = db.query(KGCandidate).filter_by(**dedup_filter).first()
                if existing:
                    return KGCandidateModel.model_validate(existing)

                cand = KGCandidate(
                    id=str(uuid.uuid4()),
                    kg_id=kg_id,
                    user_id=user_id,
                    candidate_type=candidate_type,
                    suggested_label=suggested_label,
                    target_node_id=target_node_id,
                    properties=properties,
                    status=CandidateStatus.PENDING,
                    created_at=int(time.time()),
                )
                db.add(cand)
                db.commit()
                db.refresh(cand)
                return KGCandidateModel.model_validate(cand)
        except Exception as e:
            log.exception(e)
            return None

    def get_candidates(
        self,
        kg_id: str,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> list[KGCandidateModel]:
        with get_db() as db:
            query = db.query(KGCandidate).filter(KGCandidate.kg_id == kg_id)
            if status:
                query = query.filter(KGCandidate.status == status)
            rows = query.order_by(KGCandidate.created_at.desc()).limit(limit).all()
            return [KGCandidateModel.model_validate(r) for r in rows]

    def get_candidate_by_id(self, cid: str) -> Optional[KGCandidateModel]:
        with get_db() as db:
            row = db.query(KGCandidate).filter_by(id=cid).first()
            return KGCandidateModel.model_validate(row) if row else None

    def update_candidate_status(
        self,
        cid: str,
        status: str,
        resolved_glossary_id: Optional[str] = None,
        resolved_entry_id: Optional[str] = None,
    ) -> bool:
        try:
            with get_db() as db:
                row = db.query(KGCandidate).filter_by(id=cid).first()
                if not row:
                    return False
                row.status = status
                row.resolved_glossary_id = resolved_glossary_id
                row.resolved_entry_id = resolved_entry_id
                row.resolved_at = int(time.time())
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def delete_candidate(self, cid: str) -> bool:
        try:
            with get_db() as db:
                row = db.query(KGCandidate).filter_by(id=cid).first()
                if not row:
                    return False
                db.delete(row)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def count_candidates_by_status(self, kg_id: str) -> dict:
        with get_db() as db:
            from sqlalchemy import func

            rows = (
                db.query(KGCandidate.status, func.count(KGCandidate.id))
                .filter(KGCandidate.kg_id == kg_id)
                .group_by(KGCandidate.status)
                .all()
            )
            return {status: count for status, count in rows}

    # ---- Extract jobs (Slice 9) ----

    def start_job(
        self,
        kg_id: str,
        user_id: str,
        kind: str,
        target_id: Optional[str] = None,
        params: Optional[dict] = None,
        progress_total: int = 0,
        progress_label: Optional[str] = None,
    ) -> Optional[KGExtractJobModel]:
        """잡을 'running' 상태로 새로 생성. 생성 시점이 곧 시작 시점."""
        try:
            now = int(time.time())
            with get_db() as db:
                row = KGExtractJob(
                    id=str(uuid.uuid4()),
                    kg_id=kg_id,
                    user_id=user_id,
                    kind=kind,
                    status=JobStatus.RUNNING,
                    target_id=target_id,
                    params=params,
                    progress_current=0,
                    progress_total=progress_total,
                    progress_label=progress_label,
                    created_at=now,
                    started_at=now,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                return KGExtractJobModel.model_validate(row)
        except Exception as e:
            log.exception(e)
            return None

    def update_job_progress(
        self,
        job_id: str,
        progress_current: Optional[int] = None,
        progress_total: Optional[int] = None,
        progress_label: Optional[str] = None,
    ) -> bool:
        try:
            with get_db() as db:
                row = db.query(KGExtractJob).filter_by(id=job_id).first()
                if not row:
                    return False
                if progress_current is not None:
                    row.progress_current = progress_current
                if progress_total is not None:
                    row.progress_total = progress_total
                if progress_label is not None:
                    row.progress_label = progress_label
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def heartbeat_job(self, job_id: str) -> bool:
        """Update job heartbeat timestamp."""
        try:
            with get_db() as db:
                job = db.query(KGExtractJob).filter_by(id=job_id).first()
                if job and job.status == "running":
                    job.last_heartbeat_at = int(time.time())
                    db.commit()
                    return True
                return False
        except Exception as e:
            log.exception(e)
            return False

    def complete_job(
        self,
        job_id: str,
        stats: Optional[dict] = None,
        errors: Optional[list] = None,
    ) -> bool:
        try:
            with get_db() as db:
                row = db.query(KGExtractJob).filter_by(id=job_id).first()
                if not row:
                    return False
                row.status = JobStatus.COMPLETED
                row.stats = stats
                row.errors = errors
                row.finished_at = int(time.time())
                # 100% 진행률로 마감
                if row.progress_total and row.progress_current < row.progress_total:
                    row.progress_current = row.progress_total
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def set_job_params(self, job_id: str, params: dict) -> bool:
        """Job.params 를 통째로 설정. fan-out 시 finalize 단계에서 필요한
        컨텍스트(예: glossary_id, dbsphere_ids) 를 저장할 때 사용."""
        try:
            with get_db() as db:
                row = db.query(KGExtractJob).filter_by(id=job_id).first()
                if not row:
                    return False
                row.params = params
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def fail_job(
        self,
        job_id: str,
        errors: list,
        stats: Optional[dict] = None,
    ) -> bool:
        try:
            with get_db() as db:
                row = db.query(KGExtractJob).filter_by(id=job_id).first()
                if not row:
                    return False
                row.status = JobStatus.FAILED
                row.errors = errors
                row.stats = stats
                row.finished_at = int(time.time())
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def get_jobs(
        self,
        kg_id: str,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 50,
    ) -> list[KGExtractJobModel]:
        with get_db() as db:
            q = db.query(KGExtractJob).filter_by(kg_id=kg_id)
            if status:
                q = q.filter_by(status=status)
            if kind:
                q = q.filter_by(kind=kind)
            rows = q.order_by(KGExtractJob.created_at.desc()).limit(limit).all()
            return [KGExtractJobModel.model_validate(r) for r in rows]

    def get_job_by_id(self, job_id: str) -> Optional[KGExtractJobModel]:
        with get_db() as db:
            row = db.query(KGExtractJob).filter_by(id=job_id).first()
            return KGExtractJobModel.model_validate(row) if row else None

    def increment_job_progress(
        self,
        job_id: str,
        delta: int = 1,
        progress_label: Optional[str] = None,
        success_delta: int = 0,
        failure_delta: int = 0,
    ) -> Optional[KGExtractJobModel]:
        """progress_current를 원자적으로 증가 (분산 워커가 호출).

        stats JSON에 chunks_succeeded/chunks_failed도 함께 누적.
        with_for_update()로 row lock — PG에서는 row-level lock,
        SQLite에서는 single writer 직렬화에 의존.
        """
        try:
            with get_db() as db:
                row = (
                    db.query(KGExtractJob)
                    .filter_by(id=job_id)
                    .with_for_update()
                    .first()
                )
                if not row:
                    return None
                row.progress_current = (row.progress_current or 0) + delta
                if progress_label is not None:
                    row.progress_label = progress_label
                if success_delta or failure_delta:
                    stats = dict(row.stats or {})
                    if success_delta:
                        stats["chunks_succeeded"] = (
                            int(stats.get("chunks_succeeded", 0)) + success_delta
                        )
                    if failure_delta:
                        stats["chunks_failed"] = (
                            int(stats.get("chunks_failed", 0)) + failure_delta
                        )
                    row.stats = stats
                db.commit()
                db.refresh(row)
                return KGExtractJobModel.model_validate(row)
        except Exception as e:
            log.exception(e)
            return None

    def try_claim_job_finalization(self, job_id: str) -> Optional[KGExtractJobModel]:
        """완료 조건(progress_current >= progress_total)을 만족하면 job을 'completed'로
        마킹하고 row를 반환. 그렇지 않거나 이미 완료/실패면 None 반환.

        분산 워커 fan-in 패턴: 마지막으로 incrementing한 워커만 True를 받아
        finalization 코드(KG state 저장 + 재인덱싱 등)를 실행.

        주의: progress_total > 0 인 경우에만 클레임을 허용한다. 이렇게 하지 않으면
        producer가 task를 publish 한 *직후* progress_total을 설정하는 fan-out 경로에서,
        빠른 worker가 첫 increment 만으로 (1 >= 0) 조건을 만족시켜 progress_total이
        설정되기 전에 job이 finalize 되는 경합 조건이 발생한다. 0개 task 케이스는
        producer 가 명시적으로 complete_job 을 호출한다.
        """
        try:
            with get_db() as db:
                row = (
                    db.query(KGExtractJob)
                    .filter_by(id=job_id)
                    .with_for_update()
                    .first()
                )
                if not row:
                    return None
                if row.status != JobStatus.RUNNING:
                    return None
                # progress_total 이 아직 미설정(0) 이면 아직 producer 가 enqueue 중일 수
                # 있으므로 클레임을 보류한다.
                if not row.progress_total or row.progress_total <= 0:
                    return None
                if (row.progress_current or 0) < row.progress_total:
                    return None
                row.status = JobStatus.COMPLETED
                row.finished_at = int(time.time())
                db.commit()
                db.refresh(row)
                return KGExtractJobModel.model_validate(row)
        except Exception as e:
            log.exception(e)
            return None

    def cancel_job(self, job_id: str) -> bool:
        """running 잡을 cancelled 상태로 전환.

        이미 완료/실패/취소된 잡은 무시 (False 반환).
        워커는 `increment_job_progress` 전에 job status를 확인해서
        cancelled 감지 시 빠르게 종료한다.
        """
        try:
            with get_db() as db:
                row = (
                    db.query(KGExtractJob)
                    .filter_by(id=job_id)
                    .with_for_update()
                    .first()
                )
                if not row:
                    return False
                if row.status != JobStatus.RUNNING:
                    return False
                row.status = JobStatus.CANCELLED
                row.finished_at = int(time.time())
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def is_job_cancelled(self, job_id: str) -> bool:
        """워커용 — 잡이 취소되었는지 빠르게 확인 (row lock 불필요)."""
        try:
            with get_db() as db:
                row = db.query(KGExtractJob.status).filter_by(id=job_id).first()
                return row is not None and row.status == JobStatus.CANCELLED
        except Exception:
            return False

    # ---- AGE pending (WAL) ----

    def add_age_pending(self, kg_id: str, operation: str, payload: dict) -> bool:
        try:
            with get_db() as db:
                db.add(
                    KGAgePending(
                        id=str(uuid.uuid4()),
                        kg_id=kg_id,
                        operation=operation,
                        payload=payload,
                        retries=0,
                        created_at=int(time.time()),
                    )
                )
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def get_age_pending(self, kg_id: str, limit: int = 100) -> list[KGAgePendingModel]:
        with get_db() as db:
            rows = (
                db.query(KGAgePending)
                .filter_by(kg_id=kg_id)
                .order_by(KGAgePending.created_at)
                .limit(limit)
                .all()
            )
            return [KGAgePendingModel.model_validate(r) for r in rows]

    def delete_age_pending(self, pending_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(KGAgePending).filter_by(id=pending_id).delete()
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def increment_age_pending_retry(self, pending_id: str) -> bool:
        try:
            with get_db() as db:
                row = db.query(KGAgePending).filter_by(id=pending_id).first()
                if row:
                    row.retries += 1
                    row.last_retry_at = int(time.time())
                    db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    # ---- Extract State (per-KB processed chunks) ----

    def get_extract_state(
        self, kg_id: str, kb_id: str
    ) -> Optional[KGExtractStateModel]:
        """Get extract state for a specific KB. Falls back to legacy JSON."""
        with get_db() as db:
            row = db.query(KGExtractState).filter_by(kg_id=kg_id, kb_id=kb_id).first()
            if row:
                return KGExtractStateModel.model_validate(row)
        # Legacy fallback — read from KG.data.kb_extract_state
        kg = self.get_kg_by_id(kg_id)
        if kg and kg.data:
            state = (kg.data or {}).get("kb_extract_state", {}).get(kb_id)
            if state:
                return KGExtractStateModel(
                    id=f"{kg_id}__{kb_id}",
                    kg_id=kg_id,
                    kb_id=kb_id,
                    processed_chunks=state.get("processed_chunks"),
                    last_run_at=state.get("last_run_at"),
                    last_model=state.get("last_model"),
                    updated_at=state.get("last_run_at") or int(time.time()),
                )
        return None

    def upsert_extract_state(
        self,
        kg_id: str,
        kb_id: str,
        processed_chunks: list[str],
        model_id: str = "",
    ) -> bool:
        now = int(time.time())
        state_id = f"{kg_id}__{kb_id}"
        try:
            with get_db() as db:
                row = (
                    db.query(KGExtractState)
                    .filter_by(id=state_id)
                    .with_for_update()
                    .first()
                )
                if row:
                    row.processed_chunks = sorted(processed_chunks)
                    row.last_run_at = now
                    row.last_model = model_id
                    row.updated_at = now
                else:
                    row = KGExtractState(
                        id=state_id,
                        kg_id=kg_id,
                        kb_id=kb_id,
                        processed_chunks=sorted(processed_chunks),
                        last_run_at=now,
                        last_model=model_id,
                        updated_at=now,
                    )
                    db.add(row)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def append_processed_chunks(
        self,
        kg_id: str,
        kb_id: str,
        chunk_ids: list[str],
        model_id: str = "",
    ) -> bool:
        """kg_extract_state.processed_chunks 에 원자적 append.

        기존 리스트와 `chunk_ids` 를 union 해서 저장. 동시 호출은 SELECT FOR
        UPDATE 로 직렬화. KB 청크 워커가 성공 시점마다 본인이 처리한 청크 ID
        하나를 자기 혼자만 append 하도록 설계돼 있어 race 는 거의 없지만
        finalize 등 다른 경로와 겹칠 수 있으므로 잠금을 둔다.
        """
        if not chunk_ids:
            return True
        now = int(time.time())
        state_id = f"{kg_id}__{kb_id}"
        try:
            with get_db() as db:
                row = (
                    db.query(KGExtractState)
                    .filter_by(id=state_id)
                    .with_for_update()
                    .first()
                )
                if row:
                    existing = set(row.processed_chunks or [])
                    existing.update(chunk_ids)
                    row.processed_chunks = sorted(existing)
                    row.last_run_at = now
                    if model_id:
                        row.last_model = model_id
                    row.updated_at = now
                else:
                    row = KGExtractState(
                        id=state_id,
                        kg_id=kg_id,
                        kb_id=kb_id,
                        processed_chunks=sorted(set(chunk_ids)),
                        last_run_at=now,
                        last_model=model_id,
                        updated_at=now,
                    )
                    db.add(row)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def delete_extract_state(self, kg_id: str, kb_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(KGExtractState).filter_by(kg_id=kg_id, kb_id=kb_id).delete()
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def delete_extract_states_for_kg(self, kg_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(KGExtractState).filter_by(kg_id=kg_id).delete()
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    # ---- Knowledge Links ----

    def get_knowledge_links(self, kg_id: str) -> list[KGKnowledgeLinkModel]:
        """Get all links for a KG. Falls back to legacy JSON if table is empty."""
        with get_db() as db:
            rows = (
                db.query(KGKnowledgeLink)
                .filter_by(kg_id=kg_id)
                .order_by(KGKnowledgeLink.created_at.desc())
                .all()
            )
            if rows:
                return [KGKnowledgeLinkModel.model_validate(r) for r in rows]
        # Legacy fallback: read from data JSON
        kg = self.get_kg_by_id(kg_id)
        if kg and kg.data:
            legacy = (kg.data or {}).get("knowledge_links") or []
            now = int(time.time())
            return [
                KGKnowledgeLinkModel(
                    **{
                        **link,
                        "kg_id": kg_id,
                        "user_id": kg.user_id,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                for link in legacy
                if link.get("id")
            ]
        return []

    def create_knowledge_link(
        self, kg_id: str, user_id: str, form_data: dict
    ) -> Optional[KGKnowledgeLinkModel]:
        """지식 연결 생성 — 용어집 → KB(복수) + DbSphere(복수) 매핑.

        ``config.dbsphere_ids`` 에 명시적으로 선택된 DbSphere 목록을 저장한다.
        비어있거나 미전달 시 sync 단계에서 glossary.extraction_sources 기반
        자동 추출(fallback)이 돌아간다.
        """
        now = int(time.time())
        form_dbspheres = form_data.get("dbsphere_ids")
        initial_config: dict = {}
        if form_dbspheres is not None:
            # 빈 list 도 "명시적으로 비워둠" 의미라 그대로 저장.
            initial_config["dbsphere_ids"] = list(form_dbspheres)
        link = KGKnowledgeLink(
            id=str(uuid.uuid4()),
            kg_id=kg_id,
            user_id=user_id,
            source_type=LinkSourceType.GLOSSARY,
            glossary_id=form_data.get("glossary_id"),
            target_type=LinkTargetType.KNOWLEDGE,
            knowledge_ids=form_data.get("knowledge_ids") or [],
            status=None,
            config=initial_config or None,
            created_at=now,
            updated_at=now,
        )
        try:
            with get_db() as db:
                db.add(link)
                db.commit()
                db.refresh(link)
                return KGKnowledgeLinkModel.model_validate(link)
        except Exception as e:
            log.exception(e)
            return None

    def recompute_kg_sources_from_links(self, kg_id: str) -> None:
        """KG 의 모든 KnowledgeLink 기반으로 ``kg.data.sources`` 를 재계산해 저장.

        - ``glossaries``: union(link.glossary_id)
        - ``knowledge_bases``: union(link.knowledge_ids)
        - ``dbspheres``: union(link.config.dbsphere_ids) — 명시 선택된 것만.
          한 link 라도 빈 subset 이면 fallback 으로 glossary.extraction_sources
          에서 추출한 dbsphere_id 를 포함시켜 "연결됨" 상태를 유지.

        ``sources`` 의 options 등 다른 필드는 건드리지 않는다. 링크 생성/삭제
        훅과 sync 부모에서 호출해 UI/DB 가 언제나 실제 연결 상태를 반영하게
        한다.
        """
        # lazy import — 순환 회피
        from extension_modules.knowledge_graph.sync.glossary_sync import (
            get_referenced_dbsphere_ids,
        )

        links = self.get_knowledge_links(kg_id)
        gid_set: set[str] = set()
        kb_set: set[str] = set()
        ds_set: set[str] = set()
        for lk in links:
            if lk.glossary_id:
                gid_set.add(lk.glossary_id)
            for kbid in lk.knowledge_ids or []:
                if kbid:
                    kb_set.add(kbid)
            cfg = dict(lk.config or {})
            configured_dbs = cfg.get("dbsphere_ids")
            if isinstance(configured_dbs, list) and configured_dbs:
                for dsid in configured_dbs:
                    if dsid:
                        ds_set.add(dsid)
            elif lk.glossary_id:
                try:
                    for dsid in get_referenced_dbsphere_ids(lk.glossary_id):
                        if dsid:
                            ds_set.add(dsid)
                except Exception:
                    pass

        try:
            with get_db() as db:
                row = db.query(KnowledgeGraph).filter_by(id=kg_id).first()
                if not row:
                    return
                data = dict(row.data or {})
                sources = dict(data.get("sources") or {})
                sources["glossaries"] = [{"id": g} for g in sorted(gid_set)]
                sources["knowledge_bases"] = [{"id": k} for k in sorted(kb_set)]
                sources["dbspheres"] = [{"id": d} for d in sorted(ds_set)]
                data["sources"] = sources
                row.data = data
                row.updated_at = int(time.time())
                db.commit()
        except Exception as e:
            log.warning(f"[kg] recompute_kg_sources_from_links failed: {e}")

    def delete_knowledge_link(self, link_id: str) -> bool:
        try:
            with get_db() as db:
                link = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
                if not link:
                    return False
                db.delete(link)
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False

    def get_knowledge_link_by_id(self, link_id: str) -> Optional[KGKnowledgeLinkModel]:
        with get_db() as db:
            row = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
            return KGKnowledgeLinkModel.model_validate(row) if row else None

    def check_duplicate_link(self, kg_id: str, form_data: dict) -> bool:
        """같은 KG 안에 동일 용어집 기반 링크가 이미 있는지 검사."""
        with get_db() as db:
            q = db.query(KGKnowledgeLink).filter_by(
                kg_id=kg_id,
                source_type=LinkSourceType.GLOSSARY,
                glossary_id=form_data.get("glossary_id"),
            )
            return q.first() is not None

    def update_knowledge_link_status(self, link_id: str, status_data: dict) -> bool:
        """Update the status field of a knowledge link."""
        try:
            with get_db() as db:
                row = db.query(KGKnowledgeLink).filter_by(id=link_id).first()
                if not row:
                    return False
                row.status = status_data
                row.updated_at = int(time.time())
                db.commit()
                return True
        except Exception as e:
            log.exception(e)
            return False


KnowledgeGraphs = KnowledgeGraphTable()
