import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# TraceAnalysis DB Schema
####################


class TraceAnalysis(Base):
    __tablename__ = "trace_analysis"

    id = Column(Text, primary_key=True)
    trace_id = Column(Text, nullable=False, index=True)
    chat_id = Column(Text, nullable=True)
    message_id = Column(Text, nullable=True)
    user_id = Column(Text, nullable=False, index=True)

    model_id = Column(Text, nullable=False)  # 분석에 사용한 LLM
    user_description = Column(Text, nullable=True)  # 사용자 문제 설명/요구사항
    status = Column(Text, default="pending")  # pending → running → completed | failed
    error_message = Column(Text, nullable=True)

    report = Column(Text, nullable=True)  # 생성된 마크다운 리포트
    file_path = Column(Text, nullable=True)  # backend/data/report/ 파일 경로
    context_summary = Column(JSON, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    completed_at = Column(BigInteger, nullable=True)


class TraceAnalysisModel(BaseModel):
    id: str
    trace_id: str
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    user_id: str

    model_id: str
    user_description: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None

    report: Optional[str] = None
    file_path: Optional[str] = None
    context_summary: Optional[dict] = None

    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class TraceAnalysisCreateForm(BaseModel):
    trace_id: str
    model_id: str
    user_description: str = ""


class TraceAnalysisUpdateForm(BaseModel):
    status: Optional[str] = None
    error_message: Optional[str] = None
    report: Optional[str] = None
    file_path: Optional[str] = None
    context_summary: Optional[dict] = None


class TraceAnalysisResponse(BaseModel):
    id: str
    trace_id: str
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    user_id: str

    model_id: str
    user_description: Optional[str] = None
    status: str
    error_message: Optional[str] = None

    report: Optional[str] = None
    file_path: Optional[str] = None
    context_summary: Optional[dict] = None

    created_at: int
    completed_at: Optional[int] = None


####################
# Table Operations
####################


class TraceAnalysisTable:
    def insert_new_analysis(
        self,
        user_id: str,
        form_data: TraceAnalysisCreateForm,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Optional[TraceAnalysisModel]:
        with get_db() as db:
            id = str(uuid.uuid4())
            analysis = TraceAnalysisModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "trace_id": form_data.trace_id,
                    "model_id": form_data.model_id,
                    "user_description": form_data.user_description,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "status": "pending",
                    "created_at": int(time.time()),
                }
            )
            try:
                result = TraceAnalysis(**analysis.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return TraceAnalysisModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error creating trace analysis: {e}")
                return None

    def get_analysis_by_id(self, id: str) -> Optional[TraceAnalysisModel]:
        try:
            with get_db() as db:
                analysis = db.query(TraceAnalysis).filter_by(id=id).first()
                if not analysis:
                    return None
                return TraceAnalysisModel.model_validate(analysis)
        except Exception:
            return None

    def get_analyses_by_trace_id(self, trace_id: str) -> list[TraceAnalysisModel]:
        with get_db() as db:
            analyses = (
                db.query(TraceAnalysis)
                .filter_by(trace_id=trace_id)
                .order_by(TraceAnalysis.created_at.desc())
                .all()
            )
            return [TraceAnalysisModel.model_validate(a) for a in analyses]

    def update_analysis(
        self, id: str, form_data: TraceAnalysisUpdateForm
    ) -> Optional[TraceAnalysisModel]:
        with get_db() as db:
            analysis = db.query(TraceAnalysis).filter_by(id=id).first()
            if not analysis:
                return None

            update_data = form_data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if value is not None:
                    setattr(analysis, key, value)

            if form_data.status == "completed":
                analysis.completed_at = int(time.time())

            db.commit()
            db.refresh(analysis)
            return TraceAnalysisModel.model_validate(analysis)

    def delete_analysis(self, id: str) -> bool:
        with get_db() as db:
            analysis = db.query(TraceAnalysis).filter_by(id=id).first()
            if not analysis:
                return False
            db.delete(analysis)
            db.commit()
            return True

    def delete_analyses_before(self, timestamp: int) -> int:
        """특정 시점 이전의 트레이스 분석 삭제 (보존 기간 정책용)"""
        try:
            with get_db() as db:
                count = (
                    db.query(TraceAnalysis)
                    .filter(TraceAnalysis.created_at < timestamp)
                    .delete()
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old trace analyses: {e}")
            return 0


TraceAnalyses = TraceAnalysisTable()
