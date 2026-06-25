"""
Guardrail Log Models

가드레일 감지 이벤트(PII, 차단 단어, LLM Judge)를 기록하는 로그 모델.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Index, String, Text, distinct, or_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Enums
####################


class GuardrailAction(str, Enum):
    """가드레일 처리 액션"""

    BLOCK = "block"
    REDACT = "redact"
    MASK = "mask"
    HASH = "hash"
    LOG = "log"


class GuardrailDetectionSource(str, Enum):
    """가드레일 감지 소스"""

    PII = "pii"
    CUSTOM_PATTERN = "custom_pattern"
    BLOCKED_WORD = "blocked_word"
    LLM_JUDGE = "llm_judge"


####################
# GuardrailLog DB Schema
####################


class GuardrailLog(Base):
    __tablename__ = "log_guardrail"

    id = Column(Text, primary_key=True)

    # === 누가 ===
    user_id = Column(Text, nullable=True)
    user_email = Column(Text, nullable=True)
    user_name = Column(Text, nullable=True)

    # === 채팅 컨텍스트 ===
    chat_id = Column(Text, nullable=True)
    message_id = Column(Text, nullable=True)

    # === 가드레일 정보 ===
    guardrail_id = Column(Text, nullable=True)
    guardrail_name = Column(Text, nullable=True)

    # === 감지 결과 ===
    action = Column(String(20), nullable=False)  # block, redact, mask, hash
    detection_source = Column(
        String(50), nullable=False
    )  # pii, blocked_word, llm_judge
    detection_detail = Column(Text, nullable=True)  # email, credit_card, 차단 단어 등

    # === 콘텐츠 ===
    original_content = Column(Text, nullable=True)
    processed_content = Column(Text, nullable=True)

    # === 메타데이터 ===
    meta = Column(JSON, nullable=True)

    # === 타임스탬프 ===
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_log_guardrail_user_id", "user_id"),
        Index("ix_log_guardrail_chat_id", "chat_id"),
        Index("ix_log_guardrail_action", "action"),
        Index("ix_log_guardrail_detection_source", "detection_source"),
        Index("ix_log_guardrail_created_at", "created_at"),
    )


####################
# Pydantic Models
####################


class GuardrailLogModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None

    chat_id: Optional[str] = None
    message_id: Optional[str] = None

    guardrail_id: Optional[str] = None
    guardrail_name: Optional[str] = None

    action: str
    detection_source: str
    detection_detail: Optional[str] = None

    original_content: Optional[str] = None
    processed_content: Optional[str] = None

    meta: Optional[dict] = None

    created_at: int


####################
# Forms
####################


class GuardrailLogCreateForm(BaseModel):
    """Guardrail Log 생성 폼 (내부 사용)"""

    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None

    chat_id: Optional[str] = None
    message_id: Optional[str] = None

    guardrail_id: Optional[str] = None
    guardrail_name: Optional[str] = None

    action: str
    detection_source: str
    detection_detail: Optional[str] = None

    original_content: Optional[str] = None
    processed_content: Optional[str] = None

    meta: Optional[dict] = None


class GuardrailLogQueryParams(BaseModel):
    """Guardrail Log 조회 쿼리 파라미터"""

    page: int = 1
    limit: int = 50

    action: Optional[str] = None
    detection_source: Optional[str] = None
    user_search: Optional[str] = None
    chat_id: Optional[str] = None
    source: Optional[str] = None  # "code_gateway" etc. — filters by meta.source

    from_date: Optional[int] = None
    to_date: Optional[int] = None


####################
# GuardrailLog Table Operations
####################


class GuardrailLogTable:
    def _apply_cascading_filters(
        self,
        query,
        action: Optional[str] = None,
        detection_source: Optional[str] = None,
        source: Optional[str] = None,
        user_search: Optional[str] = None,
    ):
        """Cascading 필터 공통 적용"""
        if action:
            actions = [a.strip() for a in action.split(",")]
            query = query.filter(GuardrailLog.action.in_(actions))
        if detection_source:
            sources = [s.strip() for s in detection_source.split(",")]
            query = query.filter(GuardrailLog.detection_source.in_(sources))
        if source:
            if source == "chat":
                query = query.filter(
                    or_(
                        GuardrailLog.meta.is_(None),
                        GuardrailLog.meta["source"].is_(None),
                    )
                )
            else:
                query = query.filter(GuardrailLog.meta["source"].as_string() == source)
        if user_search:
            keyword = f"%{user_search}%"
            query = query.filter(
                or_(
                    GuardrailLog.user_id.ilike(keyword),
                    GuardrailLog.user_email.ilike(keyword),
                    GuardrailLog.user_name.ilike(keyword),
                )
            )
        return query

    def get_distinct_actions(
        self,
        detection_source: Optional[str] = None,
        source: Optional[str] = None,
        user_search: Optional[str] = None,
    ) -> list[str]:
        """DB에 실제 존재하는 액션 목록 (cascading)"""
        with get_db() as db:
            query = db.query(distinct(GuardrailLog.action)).filter(
                GuardrailLog.action.isnot(None)
            )
            query = self._apply_cascading_filters(
                query,
                detection_source=detection_source,
                source=source,
                user_search=user_search,
            )
            return sorted([r[0] for r in query.all() if r[0]])

    def get_distinct_detection_sources(
        self,
        action: Optional[str] = None,
        source: Optional[str] = None,
        user_search: Optional[str] = None,
    ) -> list[str]:
        """DB에 실제 존재하는 감지 소스 목록 (cascading)"""
        with get_db() as db:
            query = db.query(distinct(GuardrailLog.detection_source)).filter(
                GuardrailLog.detection_source.isnot(None)
            )
            query = self._apply_cascading_filters(
                query,
                action=action,
                source=source,
                user_search=user_search,
            )
            return sorted([r[0] for r in query.all() if r[0]])

    def insert_guardrail_log(
        self, form_data: GuardrailLogCreateForm
    ) -> Optional[GuardrailLogModel]:
        """가드레일 로그 생성"""
        with get_db() as db:
            guardrail_log = GuardrailLogModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "created_at": int(time.time()),
                }
            )

            try:
                result = GuardrailLog(**guardrail_log.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return GuardrailLogModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting guardrail log: {e}")
                return None

    def get_guardrail_logs(
        self, params: GuardrailLogQueryParams
    ) -> tuple[list[GuardrailLogModel], int]:
        """가드레일 로그 조회 (페이지네이션 포함)"""
        with get_db() as db:
            query = db.query(GuardrailLog)

            if params.action:
                actions = [a.strip() for a in params.action.split(",")]
                if len(actions) == 1:
                    query = query.filter(GuardrailLog.action == actions[0])
                else:
                    query = query.filter(GuardrailLog.action.in_(actions))
            if params.detection_source:
                sources = [s.strip() for s in params.detection_source.split(",")]
                if len(sources) == 1:
                    query = query.filter(GuardrailLog.detection_source == sources[0])
                else:
                    query = query.filter(GuardrailLog.detection_source.in_(sources))
            if params.user_search:
                keyword = f"%{params.user_search}%"
                query = query.filter(
                    or_(
                        GuardrailLog.user_id.ilike(keyword),
                        GuardrailLog.user_email.ilike(keyword),
                        GuardrailLog.user_name.ilike(keyword),
                    )
                )
            if params.chat_id:
                query = query.filter(GuardrailLog.chat_id.like(f"{params.chat_id}%"))
            if params.source:
                if params.source == "chat":
                    query = query.filter(
                        or_(
                            GuardrailLog.meta.is_(None),
                            GuardrailLog.meta["source"].is_(None),
                        )
                    )
                else:
                    query = query.filter(
                        GuardrailLog.meta["source"].as_string() == params.source
                    )
            if params.from_date:
                query = query.filter(GuardrailLog.created_at >= params.from_date)
            if params.to_date:
                query = query.filter(GuardrailLog.created_at <= params.to_date)

            total = query.count()

            offset = (params.page - 1) * params.limit
            logs = (
                query.order_by(GuardrailLog.created_at.desc())
                .offset(offset)
                .limit(params.limit)
                .all()
            )

            return (
                [GuardrailLogModel.model_validate(log) for log in logs],
                total,
            )

    def get_guardrail_log_by_id(self, id: str) -> Optional[GuardrailLogModel]:
        """ID로 가드레일 로그 조회"""
        try:
            with get_db() as db:
                guardrail_log = db.query(GuardrailLog).filter_by(id=id).first()
                return (
                    GuardrailLogModel.model_validate(guardrail_log)
                    if guardrail_log
                    else None
                )
        except Exception:
            return None

    def delete_guardrail_logs_before(self, timestamp: int) -> int:
        """특정 시점 이전의 로그 삭제 (보존 기간 정책용)"""
        try:
            with get_db() as db:
                count = (
                    db.query(GuardrailLog)
                    .filter(GuardrailLog.created_at < timestamp)
                    .delete()
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old guardrail logs: {e}")
            return 0


# Singleton instance
GuardrailLogs = GuardrailLogTable()
