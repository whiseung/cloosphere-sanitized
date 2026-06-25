import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Float, Index, Text, and_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# AutoEvaluation DB Schema
####################


class AutoEvaluation(Base):
    __tablename__ = "auto_evaluation"
    __table_args__ = (
        Index("ix_auto_evaluation_model_id", "model_id"),
        Index("ix_auto_evaluation_chat_id", "chat_id"),
        Index("ix_auto_evaluation_status", "status"),
        Index("ix_auto_evaluation_created_at", "created_at"),
        Index("ix_auto_evaluation_user_id", "user_id"),
    )

    id = Column(Text, primary_key=True)
    chat_id = Column(Text, nullable=False)
    message_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    model_id = Column(Text, nullable=False)
    judge_model_id = Column(Text, nullable=False)

    evaluation_type = Column(Text, nullable=False)  # retrieval, faithfulness, quality

    # Evaluation input (snapshot)
    user_query = Column(Text, nullable=True)
    assistant_response = Column(Text, nullable=True)
    retrieved_contexts = Column(JSON, nullable=True)  # RAG documents

    # Evaluation result
    score = Column(Float, nullable=True)  # 0.0 ~ 1.0 (nullable for pending status)
    reasoning = Column(Text, nullable=True)  # Evaluation reasoning
    details = Column(JSON, nullable=True)  # Type-specific details

    status = Column(
        Text, nullable=False, default="pending"
    )  # pending, completed, failed
    error_message = Column(Text, nullable=True)

    created_at = Column(BigInteger, nullable=False)
    completed_at = Column(BigInteger, nullable=True)


class AutoEvaluationModel(BaseModel):
    id: str
    chat_id: str
    message_id: str
    user_id: str
    model_id: str
    judge_model_id: str

    evaluation_type: str

    user_query: Optional[str] = None
    assistant_response: Optional[str] = None
    retrieved_contexts: Optional[list[dict]] = None

    score: Optional[float] = None
    reasoning: Optional[str] = None
    details: Optional[dict] = None

    status: str = "pending"
    error_message: Optional[str] = None

    created_at: int
    completed_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class AutoEvaluationForm(BaseModel):
    chat_id: str
    message_id: str
    model_id: str
    judge_model_id: str
    evaluation_type: str

    user_query: Optional[str] = None
    assistant_response: Optional[str] = None
    retrieved_contexts: Optional[list[dict]] = None


class AutoEvaluationUpdateForm(BaseModel):
    score: Optional[float] = None
    reasoning: Optional[str] = None
    details: Optional[dict] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


class AutoEvaluationResponse(BaseModel):
    id: str
    chat_id: str
    message_id: str
    user_id: str
    model_id: str
    judge_model_id: str

    evaluation_type: str

    user_query: Optional[str] = None
    assistant_response: Optional[str] = None
    retrieved_contexts: Optional[list[dict]] = None

    score: Optional[float] = None
    reasoning: Optional[str] = None
    details: Optional[dict] = None

    status: str
    error_message: Optional[str] = None

    created_at: int
    completed_at: Optional[int] = None


class AutoEvaluationStatsResponse(BaseModel):
    total_count: int
    completed_count: int
    pending_count: int
    failed_count: int
    avg_score: Optional[float] = None
    by_model: dict  # model_id -> {count, avg_score}
    by_type: dict  # evaluation_type -> {count, avg_score}


class AutoEvaluationListResponse(BaseModel):
    items: list[AutoEvaluationResponse]
    total: int
    page: int
    limit: int


####################
# Table Operations
####################


class AutoEvaluationTable:
    def insert_new_auto_evaluation(
        self, user_id: str, form_data: AutoEvaluationForm
    ) -> Optional[AutoEvaluationModel]:
        with get_db() as db:
            id = str(uuid.uuid4())
            auto_eval = AutoEvaluationModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    **form_data.model_dump(),
                    "status": "pending",
                    "created_at": int(time.time()),
                }
            )
            try:
                result = AutoEvaluation(**auto_eval.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return AutoEvaluationModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error creating a new auto evaluation: {e}")
                return None

    def get_auto_evaluation_by_id(self, id: str) -> Optional[AutoEvaluationModel]:
        try:
            with get_db() as db:
                auto_eval = db.query(AutoEvaluation).filter_by(id=id).first()
                if not auto_eval:
                    return None
                return AutoEvaluationModel.model_validate(auto_eval)
        except Exception:
            return None

    def get_auto_evaluations(
        self,
        model_id: Optional[str] = None,
        evaluation_type: Optional[str] = None,
        status: Optional[str] = None,
        score_min: Optional[float] = None,
        score_max: Optional[float] = None,
        date_from: Optional[int] = None,
        date_to: Optional[int] = None,
        page: int = 1,
        limit: int = 50,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[AutoEvaluationModel], int]:
        with get_db() as db:
            query = db.query(AutoEvaluation)

            # Apply filters
            filters = []
            if model_id:
                filters.append(AutoEvaluation.model_id == model_id)
            if evaluation_type:
                filters.append(AutoEvaluation.evaluation_type == evaluation_type)
            if status:
                filters.append(AutoEvaluation.status == status)
            if score_min is not None:
                filters.append(AutoEvaluation.score >= score_min)
            if score_max is not None:
                filters.append(AutoEvaluation.score <= score_max)
            if date_from:
                filters.append(AutoEvaluation.created_at >= date_from)
            if date_to:
                filters.append(AutoEvaluation.created_at <= date_to)

            if filters:
                query = query.filter(and_(*filters))

            # Get total count before pagination
            total = query.count()

            # Apply sorting
            sort_column = getattr(AutoEvaluation, sort_by, AutoEvaluation.created_at)
            if order == "asc":
                query = query.order_by(sort_column.asc())
            else:
                query = query.order_by(sort_column.desc())

            # Apply pagination
            offset = (page - 1) * limit
            query = query.offset(offset).limit(limit)

            auto_evals = query.all()
            return (
                [AutoEvaluationModel.model_validate(ae) for ae in auto_evals],
                total,
            )

    def get_auto_evaluations_by_chat_id(
        self, chat_id: str
    ) -> list[AutoEvaluationModel]:
        with get_db() as db:
            auto_evals = (
                db.query(AutoEvaluation)
                .filter_by(chat_id=chat_id)
                .order_by(AutoEvaluation.created_at.desc())
                .all()
            )
            return [AutoEvaluationModel.model_validate(ae) for ae in auto_evals]

    def get_auto_evaluations_by_message_id(
        self, message_id: str
    ) -> list[AutoEvaluationModel]:
        with get_db() as db:
            auto_evals = (
                db.query(AutoEvaluation)
                .filter_by(message_id=message_id)
                .order_by(AutoEvaluation.created_at.desc())
                .all()
            )
            return [AutoEvaluationModel.model_validate(ae) for ae in auto_evals]

    def get_stats(self) -> dict:
        with get_db() as db:
            from sqlalchemy import func

            # Total counts
            total_count = db.query(AutoEvaluation).count()
            completed_count = (
                db.query(AutoEvaluation).filter_by(status="completed").count()
            )
            pending_count = db.query(AutoEvaluation).filter_by(status="pending").count()
            failed_count = db.query(AutoEvaluation).filter_by(status="failed").count()

            # Average score (only completed)
            avg_score_result = (
                db.query(func.avg(AutoEvaluation.score))
                .filter(AutoEvaluation.status == "completed")
                .scalar()
            )
            avg_score = float(avg_score_result) if avg_score_result else None

            # Stats by model
            by_model_results = (
                db.query(
                    AutoEvaluation.model_id,
                    func.count(AutoEvaluation.id),
                    func.avg(AutoEvaluation.score),
                )
                .filter(AutoEvaluation.status == "completed")
                .group_by(AutoEvaluation.model_id)
                .all()
            )
            by_model = {
                row[0]: {
                    "count": row[1],
                    "avg_score": float(row[2]) if row[2] else None,
                }
                for row in by_model_results
            }

            # Stats by evaluation type
            by_type_results = (
                db.query(
                    AutoEvaluation.evaluation_type,
                    func.count(AutoEvaluation.id),
                    func.avg(AutoEvaluation.score),
                )
                .filter(AutoEvaluation.status == "completed")
                .group_by(AutoEvaluation.evaluation_type)
                .all()
            )
            by_type = {
                row[0]: {
                    "count": row[1],
                    "avg_score": float(row[2]) if row[2] else None,
                }
                for row in by_type_results
            }

            return {
                "total_count": total_count,
                "completed_count": completed_count,
                "pending_count": pending_count,
                "failed_count": failed_count,
                "avg_score": avg_score,
                "by_model": by_model,
                "by_type": by_type,
            }

    def update_auto_evaluation_by_id(
        self, id: str, form_data: AutoEvaluationUpdateForm
    ) -> Optional[AutoEvaluationModel]:
        with get_db() as db:
            auto_eval = db.query(AutoEvaluation).filter_by(id=id).first()
            if not auto_eval:
                return None

            update_data = form_data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if value is not None:
                    setattr(auto_eval, key, value)

            # Set completed_at when status is completed
            if form_data.status == "completed":
                auto_eval.completed_at = int(time.time())

            db.commit()
            db.refresh(auto_eval)
            return AutoEvaluationModel.model_validate(auto_eval)

    def delete_auto_evaluation_by_id(self, id: str) -> bool:
        with get_db() as db:
            auto_eval = db.query(AutoEvaluation).filter_by(id=id).first()
            if not auto_eval:
                return False
            db.delete(auto_eval)
            db.commit()
            return True

    def delete_auto_evaluations_by_chat_id(self, chat_id: str) -> bool:
        with get_db() as db:
            auto_evals = db.query(AutoEvaluation).filter_by(chat_id=chat_id).all()
            if not auto_evals:
                return False
            for auto_eval in auto_evals:
                db.delete(auto_eval)
            db.commit()
            return True

    def get_all_auto_evaluations(self) -> list[AutoEvaluationModel]:
        """Get all auto evaluations for export"""
        with get_db() as db:
            auto_evals = (
                db.query(AutoEvaluation)
                .order_by(AutoEvaluation.created_at.desc())
                .all()
            )
            return [AutoEvaluationModel.model_validate(ae) for ae in auto_evals]

    def delete_auto_evaluations_before(self, timestamp: int) -> int:
        """특정 시점 이전의 자동 평가 삭제 (보존 기간 정책용)"""
        try:
            with get_db() as db:
                count = (
                    db.query(AutoEvaluation)
                    .filter(AutoEvaluation.created_at < timestamp)
                    .delete()
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old auto evaluations: {e}")
            return 0


AutoEvaluations = AutoEvaluationTable()
