"""
Message Trace Models

LangSmith 스타일의 메시지 단위 LLM 호출 트레이싱을 위한 모델.
각 Run은 트리 구조를 형성하여 복잡한 체인 실행 흐름을 추적합니다.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Index, Integer, String, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Run Type Enum
####################


class RunType(str, Enum):
    """Run 타입 정의 (LangSmith 호환)"""

    CHAIN = "chain"  # 복합 작업 (메시지 처리)
    LLM = "llm"  # LLM API 호출
    TOOL = "tool"  # 도구 실행
    RETRIEVAL = "retrieval"  # RAG 문서 검색
    WEB_SEARCH = "web_search"  # 웹 검색
    GUARDRAIL = "guardrail"  # 가드레일 체크
    EMBEDDING = "embedding"  # 임베딩 생성
    FILTER = "filter"  # 필터 함수 실행
    PIPELINE = "pipeline"  # 파이프라인 처리
    IMAGE = "image"  # 이미지 생성
    TASK = "task"  # 백그라운드 태스크 (title/tags 생성 등)


class RunStatus(str, Enum):
    """Run 상태"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


####################
# MessageTrace DB Schema
####################


class MessageTrace(Base):
    __tablename__ = "message_trace"

    # 핵심 ID 필드
    id = Column(String, primary_key=True)
    trace_id = Column(String, nullable=False, index=True)  # 같은 요청의 모든 Run 공유
    parent_run_id = Column(String, nullable=True)  # 부모 Run ID (트리 구조)
    dotted_order = Column(String, nullable=False)  # 계층 순서 ("1.2.1")

    # 컨텍스트 필드
    chat_id = Column(String, nullable=True, index=True)
    message_id = Column(String, nullable=True)
    user_id = Column(String, nullable=False, index=True)

    # Run 정보
    run_type = Column(String, nullable=False)  # llm, tool, retrieval, chain 등
    name = Column(String, nullable=False)  # 실행 이름
    status = Column(String, nullable=False, default=RunStatus.PENDING.value)

    # 입출력 데이터
    inputs = Column(JSON, nullable=True)
    outputs = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    # 타이밍 정보
    start_time = Column(BigInteger, nullable=False)  # 시작 시간 (ms)
    end_time = Column(BigInteger, nullable=True)  # 종료 시간 (ms)
    latency_ms = Column(Integer, nullable=True)  # 지연 시간

    # LLM 관련 정보
    token_usage = Column(
        JSON, nullable=True
    )  # {prompt_tokens, completion_tokens, total_tokens}
    model_id = Column(String, nullable=True)

    # 메타데이터
    meta = Column(JSON, nullable=True)

    # 타임스탬프
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    # 인덱스 정의
    __table_args__ = (
        Index("ix_message_trace_trace_id", "trace_id"),
        Index("ix_message_trace_chat_message", "chat_id", "message_id"),
        Index("ix_message_trace_user_created", "user_id", "created_at"),
        Index("ix_message_trace_status", "status"),
    )


####################
# Pydantic Models
####################


class MessageTraceModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trace_id: str
    parent_run_id: Optional[str] = None
    dotted_order: str

    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    user_id: str

    run_type: str
    name: str
    status: str

    inputs: Optional[dict] = None
    outputs: Optional[dict] = None
    error: Optional[str] = None

    start_time: int
    end_time: Optional[int] = None
    latency_ms: Optional[int] = None

    token_usage: Optional[dict] = None
    model_id: Optional[str] = None

    meta: Optional[dict] = None

    created_at: int
    updated_at: int


class MessageTraceResponse(MessageTraceModel):
    """API 응답용 모델"""

    children: Optional[list["MessageTraceResponse"]] = None


class TraceTreeResponse(BaseModel):
    """트레이스 트리 응답"""

    trace_id: str
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    user_id: str
    total_latency_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    status: str
    runs: list[MessageTraceResponse]


####################
# Forms
####################


class MessageTraceCreateForm(BaseModel):
    """MessageTrace 생성 폼 (내부 사용)"""

    trace_id: str
    parent_run_id: Optional[str] = None
    dotted_order: str

    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    user_id: str

    run_type: str
    name: str
    status: str = RunStatus.RUNNING.value

    inputs: Optional[dict] = None
    model_id: Optional[str] = None
    meta: Optional[dict] = None


class MessageTraceUpdateForm(BaseModel):
    """MessageTrace 업데이트 폼"""

    status: Optional[str] = None
    outputs: Optional[dict] = None
    error: Optional[str] = None
    end_time: Optional[int] = None
    latency_ms: Optional[int] = None
    token_usage: Optional[dict] = None


class TraceQueryParams(BaseModel):
    """트레이스 조회 쿼리 파라미터"""

    page: int = 1
    limit: int = 50

    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    user_id: Optional[str] = None
    run_type: Optional[str] = None
    status: Optional[str] = None

    from_date: Optional[int] = None  # Unix timestamp (ms)
    to_date: Optional[int] = None  # Unix timestamp (ms)


####################
# MessageTrace Table Operations
####################


class MessageTraceTable:
    def _get_current_time_ms(self) -> int:
        """현재 시간을 밀리초로 반환"""
        return int(time.time() * 1000)

    def create_trace(
        self, form_data: MessageTraceCreateForm
    ) -> Optional[MessageTraceModel]:
        """새 트레이스 레코드 생성"""
        with get_db() as db:
            now = self._get_current_time_ms()

            trace = MessageTrace(
                id=str(uuid.uuid4()),
                trace_id=form_data.trace_id,
                parent_run_id=form_data.parent_run_id,
                dotted_order=form_data.dotted_order,
                chat_id=form_data.chat_id,
                message_id=form_data.message_id,
                user_id=form_data.user_id,
                run_type=form_data.run_type,
                name=form_data.name,
                status=form_data.status,
                inputs=form_data.inputs,
                model_id=form_data.model_id,
                meta=form_data.meta,
                start_time=now,
                created_at=now,
                updated_at=now,
            )

            try:
                db.add(trace)
                db.commit()
                db.refresh(trace)
                return MessageTraceModel.model_validate(trace)
            except Exception as e:
                log.exception(f"Error creating message trace: {e}")
                return None

    def update_trace(
        self, trace_id: str, form_data: MessageTraceUpdateForm
    ) -> Optional[MessageTraceModel]:
        """트레이스 레코드 업데이트"""
        with get_db() as db:
            trace = db.query(MessageTrace).filter_by(id=trace_id).first()
            if not trace:
                return None

            now = self._get_current_time_ms()

            if form_data.status is not None:
                trace.status = form_data.status
            if form_data.outputs is not None:
                trace.outputs = form_data.outputs
            if form_data.error is not None:
                trace.error = form_data.error
            if form_data.end_time is not None:
                trace.end_time = form_data.end_time
            if form_data.latency_ms is not None:
                trace.latency_ms = form_data.latency_ms
            if form_data.token_usage is not None:
                trace.token_usage = form_data.token_usage

            trace.updated_at = now

            try:
                db.commit()
                db.refresh(trace)
                return MessageTraceModel.model_validate(trace)
            except Exception as e:
                log.exception(f"Error updating message trace: {e}")
                return None

    def complete_trace(
        self,
        trace_id: str,
        outputs: Optional[dict] = None,
        token_usage: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> Optional[MessageTraceModel]:
        """트레이스 완료 처리"""
        with get_db() as db:
            trace = db.query(MessageTrace).filter_by(id=trace_id).first()
            if not trace:
                return None

            now = self._get_current_time_ms()
            trace.end_time = now
            trace.latency_ms = now - trace.start_time
            trace.updated_at = now

            if error:
                trace.status = RunStatus.ERROR.value
                trace.error = error
            else:
                trace.status = RunStatus.SUCCESS.value

            if outputs is not None:
                trace.outputs = outputs
            if token_usage is not None:
                trace.token_usage = token_usage

            try:
                db.commit()
                db.refresh(trace)
                return MessageTraceModel.model_validate(trace)
            except Exception as e:
                log.exception(f"Error completing message trace: {e}")
                return None

    def get_trace_by_id(self, trace_id: str) -> Optional[MessageTraceModel]:
        """ID로 트레이스 조회"""
        with get_db() as db:
            trace = db.query(MessageTrace).filter_by(id=trace_id).first()
            return MessageTraceModel.model_validate(trace) if trace else None

    def get_traces_by_trace_id(self, trace_id: str) -> list[MessageTraceModel]:
        """trace_id로 모든 Run 조회 (트리 구성용)"""
        with get_db() as db:
            traces = (
                db.query(MessageTrace)
                .filter_by(trace_id=trace_id)
                .order_by(MessageTrace.start_time)
                .all()
            )
            return [MessageTraceModel.model_validate(t) for t in traces]

    def get_trace_tree(self, trace_id: str) -> Optional[TraceTreeResponse]:
        """trace_id로 트리 구조 조회"""
        traces = self.get_traces_by_trace_id(trace_id)
        if not traces:
            return None

        # 트리 구성
        trace_map = {
            t.id: MessageTraceResponse(**t.model_dump(), children=[]) for t in traces
        }
        root_traces = []

        for trace in traces:
            trace_response = trace_map[trace.id]
            if trace.parent_run_id and trace.parent_run_id in trace_map:
                trace_map[trace.parent_run_id].children.append(trace_response)
            else:
                root_traces.append(trace_response)

        # 통계 계산
        root = traces[0] if traces else None
        total_latency = None
        total_tokens = None
        overall_status = RunStatus.SUCCESS.value

        for trace in traces:
            if trace.status == RunStatus.ERROR.value:
                overall_status = RunStatus.ERROR.value
            elif (
                trace.status == RunStatus.RUNNING.value
                and overall_status != RunStatus.ERROR.value
            ):
                overall_status = RunStatus.RUNNING.value

            if trace.token_usage:
                if total_tokens is None:
                    total_tokens = 0
                total_tokens += trace.token_usage.get("total_tokens", 0)

        if root and root.end_time:
            total_latency = root.end_time - root.start_time

        return TraceTreeResponse(
            trace_id=trace_id,
            chat_id=root.chat_id if root else None,
            message_id=root.message_id if root else None,
            user_id=root.user_id if root else "",
            total_latency_ms=total_latency,
            total_tokens=total_tokens,
            status=overall_status,
            runs=root_traces,
        )

    def get_traces_by_message(
        self, chat_id: str, message_id: str
    ) -> list[MessageTraceModel]:
        """특정 메시지의 트레이스 조회"""
        with get_db() as db:
            traces = (
                db.query(MessageTrace)
                .filter_by(chat_id=chat_id, message_id=message_id)
                .order_by(MessageTrace.start_time)
                .all()
            )
            return [MessageTraceModel.model_validate(t) for t in traces]

    def get_trace_tree_by_message(
        self, chat_id: str, message_id: str
    ) -> Optional[TraceTreeResponse]:
        """특정 메시지의 트레이스 트리 조회"""
        traces = self.get_traces_by_message(chat_id, message_id)
        if not traces:
            return None

        # trace_id로 그룹화 (하나의 메시지에 여러 trace가 있을 수 있음)
        trace_ids = set(t.trace_id for t in traces)
        if len(trace_ids) == 1:
            return self.get_trace_tree(traces[0].trace_id)

        # 여러 trace가 있는 경우 가장 최근 것 반환
        latest_trace_id = traces[0].trace_id
        return self.get_trace_tree(latest_trace_id)

    def get_traces_by_chat(
        self, chat_id: str, limit: int = 100
    ) -> list[MessageTraceModel]:
        """특정 채팅의 트레이스 조회 (최상위 Run만)"""
        with get_db() as db:
            traces = (
                db.query(MessageTrace)
                .filter_by(chat_id=chat_id, parent_run_id=None)
                .order_by(MessageTrace.created_at.desc())
                .limit(limit)
                .all()
            )
            return [MessageTraceModel.model_validate(t) for t in traces]

    def get_traces(
        self, params: TraceQueryParams, user_id: Optional[str] = None
    ) -> tuple[list[MessageTraceModel], int]:
        """트레이스 목록 조회 (페이지네이션)"""
        with get_db() as db:
            query = db.query(MessageTrace).filter(MessageTrace.parent_run_id == None)

            if user_id:
                query = query.filter(MessageTrace.user_id == user_id)
            elif params.user_id:
                query = query.filter(MessageTrace.user_id == params.user_id)

            if params.chat_id:
                query = query.filter(MessageTrace.chat_id == params.chat_id)
            if params.message_id:
                query = query.filter(MessageTrace.message_id == params.message_id)
            if params.run_type:
                query = query.filter(MessageTrace.run_type == params.run_type)
            if params.status:
                query = query.filter(MessageTrace.status == params.status)
            if params.from_date:
                query = query.filter(MessageTrace.created_at >= params.from_date)
            if params.to_date:
                query = query.filter(MessageTrace.created_at <= params.to_date)

            total = query.count()

            offset = (params.page - 1) * params.limit
            traces = (
                query.order_by(MessageTrace.created_at.desc())
                .offset(offset)
                .limit(params.limit)
                .all()
            )

            return ([MessageTraceModel.model_validate(t) for t in traces], total)

    def delete_traces_before(self, timestamp_ms: int) -> int:
        """특정 시점 이전의 트레이스 삭제 (보존 기간 정책)"""
        try:
            with get_db() as db:
                count = (
                    db.query(MessageTrace)
                    .filter(MessageTrace.created_at < timestamp_ms)
                    .delete()
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old traces: {e}")
            return 0

    def get_trace_stats(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """트레이스 통계 조회"""
        from sqlalchemy import func

        with get_db() as db:
            query = db.query(MessageTrace)

            if from_date:
                query = query.filter(MessageTrace.created_at >= from_date)
            if to_date:
                query = query.filter(MessageTrace.created_at <= to_date)
            if user_id:
                query = query.filter(MessageTrace.user_id == user_id)

            # 타입별 카운트
            type_counts = (
                query.with_entities(MessageTrace.run_type, func.count(MessageTrace.id))
                .group_by(MessageTrace.run_type)
                .all()
            )

            # 상태별 카운트
            status_counts = (
                query.with_entities(MessageTrace.status, func.count(MessageTrace.id))
                .group_by(MessageTrace.status)
                .all()
            )

            # 평균 레이턴시
            avg_latency = (
                query.with_entities(func.avg(MessageTrace.latency_ms))
                .filter(MessageTrace.latency_ms != None)
                .scalar()
            )

            # 총 토큰 사용량 (LLM 타입만)
            llm_traces = query.filter(MessageTrace.run_type == RunType.LLM.value).all()
            total_tokens = 0
            for trace in llm_traces:
                if trace.token_usage:
                    total_tokens += trace.token_usage.get("total_tokens", 0)

            return {
                "by_type": {rt: count for rt, count in type_counts},
                "by_status": {status: count for status, count in status_counts},
                "avg_latency_ms": round(avg_latency, 2) if avg_latency else None,
                "total_tokens": total_tokens,
                "total": query.count(),
            }


# Singleton instance
MessageTraces = MessageTraceTable()
