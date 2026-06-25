"""
DbSphere Memory Usage Models

few-shot(sql_memory) 등 DbSphere 메모리가 벡터검색에 걸려 프롬프트에 "주입"될 때마다
이벤트 행을 한 건 기록한다. GROUP BY 로 참조(주입) 횟수·마지막 참조일을 집계해
한 번도 참조되지 않은 few-shot 을 식별(수동 정리)하는 데 쓴다.

주의(설계 전제):
- 여기서 "참조" = 검색되어 프롬프트에 주입됨(retrieval/injection)이며, LLM 이 실제로 그
  예시를 사용했다는 뜻이 아니다. 한 쿼리가 여러 주입 경로(system_prompt / tool_result /
  kg_fetch_data)를 동시에 타면 같은 memory_id 가 여러 행으로 쌓일 수 있다(주입 이벤트 수).
- 자기강화 오염 few-shot 은 재주입마다 카운트가 올라가 '사용중'으로 보인다. 따라서
  use_count 는 품질/오염 지표가 아니다(미사용=count 0 만 의미가 있다).
- 기록은 fire-and-forget(누락돼도 쿼리 흐름 영향 0)이라 under-count 가능. cleanup 은
  grace 기간 + 수동 검토로 false-positive(실사용을 미사용으로 오판)를 방어한다.
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Index, String, Text, distinct, func

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# DbsphereMemoryUsage DB Schema
####################


class DbsphereMemoryUsage(Base):
    __tablename__ = "dbsphere_memory_usage"

    # Primary key
    id = Column(Text, primary_key=True)

    # === 무엇이 참조되었나 ===
    memory_id = Column(Text, nullable=False)  # 주입된 메모리(문서) id
    dbsphere_id = Column(Text, nullable=False)
    entity_type = Column(String(50), nullable=True)  # sql_memory 등

    # === 누가/어디서 유발했나 ===
    user_id = Column(Text, nullable=True)
    chat_id = Column(Text, nullable=True)

    # === 어떤 경로로 주입되었나 ===
    injection_point = Column(
        String(30), nullable=True
    )  # system_prompt | tool_result | kg_fetch_data

    # === 타임스탬프 ===
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_dbsphere_memory_usage_memory_id", "memory_id"),
        Index("ix_dbsphere_memory_usage_dbsphere_id", "dbsphere_id"),
        Index("ix_dbsphere_memory_usage_user_id", "user_id"),
        Index("ix_dbsphere_memory_usage_created_at", "created_at"),
        # 집계는 항상 dbsphere_id 로 스코핑 후 memory_id 로 GROUP BY → 복합 인덱스로 커버.
        Index("ix_dbsphere_memory_usage_dbsphere_memory", "dbsphere_id", "memory_id"),
    )


####################
# Pydantic Models
####################


class DbsphereMemoryUsageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_id: str
    dbsphere_id: str
    entity_type: Optional[str] = None
    user_id: Optional[str] = None
    chat_id: Optional[str] = None
    injection_point: Optional[str] = None
    created_at: int


####################
# Forms
####################


class DbsphereMemoryUsageForm(BaseModel):
    """참조 이벤트 기록 폼 (내부 사용 — fire-and-forget 로깅)."""

    memory_id: str
    dbsphere_id: str
    entity_type: Optional[str] = None
    user_id: Optional[str] = None
    chat_id: Optional[str] = None
    injection_point: Optional[str] = None


####################
# Table Operations
####################


class DbsphereMemoryUsageTable:
    def insert_usage(
        self, form_data: DbsphereMemoryUsageForm
    ) -> Optional[DbsphereMemoryUsageModel]:
        """참조 이벤트 1건 기록."""
        with get_db() as db:
            usage = DbsphereMemoryUsageModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "created_at": int(time.time()),
                }
            )
            try:
                result = DbsphereMemoryUsage(**usage.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                return DbsphereMemoryUsageModel.model_validate(result)
            except Exception as e:
                log.exception(f"Error inserting memory usage: {e}")
                return None

    def insert_usage_bulk(self, forms: list[DbsphereMemoryUsageForm]) -> int:
        """참조 이벤트 N건을 한 번에 기록 — 주입 시 memory_id 별 1행씩.

        반환: 실제 기록된 행 수(실패 시 0). fire-and-forget 호출자가 무시 가능.
        """
        if not forms:
            return 0
        with get_db() as db:
            now = int(time.time())
            try:
                objs = [
                    DbsphereMemoryUsage(
                        **{
                            **f.model_dump(),
                            "id": str(uuid.uuid4()),
                            "created_at": now,
                        }
                    )
                    for f in forms
                ]
                db.add_all(objs)
                db.commit()
                return len(objs)
            except Exception as e:
                log.exception(f"Error bulk-inserting memory usage: {e}")
                return 0

    def get_usage_counts(
        self, dbsphere_id: str, memory_ids: Optional[list[str]] = None
    ) -> dict[str, dict]:
        """dbsphere 단위로 memory_id 별 {use_count, last_used_at} 집계.

        항상 dbsphere_id 로 스코핑(다른 dbsphere 카운트 누출 방지). memory_ids 가
        주어지면 그 집합만(목록 enrich 시 over-fetch 회피).
        """
        with get_db() as db:
            query = db.query(
                DbsphereMemoryUsage.memory_id,
                func.count(DbsphereMemoryUsage.id),
                func.max(DbsphereMemoryUsage.created_at),
            ).filter(DbsphereMemoryUsage.dbsphere_id == dbsphere_id)
            if memory_ids:
                query = query.filter(DbsphereMemoryUsage.memory_id.in_(memory_ids))
            query = query.group_by(DbsphereMemoryUsage.memory_id)
            return {
                mid: {
                    "use_count": int(cnt),
                    "last_used_at": int(last) if last else None,
                }
                for mid, cnt, last in query.all()
            }

    def get_used_memory_ids(self, dbsphere_id: str) -> set[str]:
        """dbsphere 에서 한 번이라도 참조(주입)된 distinct memory_id 집합.

        '미사용' 판정은 (벡터인덱스의 전체 sql_memory id) - (이 집합) 의 left-anti-join.
        usage 테이블은 append-on-injection 이라 미사용 row 가 구조적으로 부재하므로,
        후보 집합은 벡터인덱스에서 열거하고 여기 distinct 집합으로 차집합한다.
        """
        with get_db() as db:
            rows = (
                db.query(distinct(DbsphereMemoryUsage.memory_id))
                .filter(DbsphereMemoryUsage.dbsphere_id == dbsphere_id)
                .all()
            )
            return {r[0] for r in rows if r[0]}

    def get_logging_active_since(self, dbsphere_id: str) -> Optional[int]:
        """이 dbsphere 의 첫 참조 기록 시각(epoch). 로깅이 언제부터 쌓였는지의 근사.

        None = 아직 한 건도 기록 안 됨. trust-window 게이트에서 (now - 이 값) < grace 면
        '미사용' 신호를 신뢰하지 않는다(배포 직후·저활동 dbsphere 의 거짓 flag 차단).
        """
        with get_db() as db:
            v = (
                db.query(func.min(DbsphereMemoryUsage.created_at))
                .filter(DbsphereMemoryUsage.dbsphere_id == dbsphere_id)
                .scalar()
            )
            return int(v) if v is not None else None

    def delete_by_memory_ids(self, dbsphere_id: str, memory_ids: list[str]) -> int:
        """메모리 삭제 시 그에 딸린 usage 행도 정리(고아 행 방지)."""
        if not memory_ids:
            return 0
        try:
            with get_db() as db:
                count = (
                    db.query(DbsphereMemoryUsage)
                    .filter(
                        DbsphereMemoryUsage.dbsphere_id == dbsphere_id,
                        DbsphereMemoryUsage.memory_id.in_(memory_ids),
                    )
                    .delete(synchronize_session=False)
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting memory usage rows: {e}")
            return 0

    def delete_usage_before(self, timestamp: int) -> int:
        """특정 시점 이전 행 삭제(보존 정책용). horizon ≫ grace 로만 사용할 것."""
        try:
            with get_db() as db:
                count = (
                    db.query(DbsphereMemoryUsage)
                    .filter(DbsphereMemoryUsage.created_at < timestamp)
                    .delete(synchronize_session=False)
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old memory usage rows: {e}")
            return 0


# Singleton instance
DbsphereMemoryUsages = DbsphereMemoryUsageTable()
