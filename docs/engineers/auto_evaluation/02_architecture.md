# Auto Evaluation 아키텍처

## 1. 데이터베이스 모델

### AutoEvaluation 테이블

```python
# backend/open_webui/models/auto_evaluations.py

class AutoEvaluation(Base):
    __tablename__ = "auto_evaluation"

    id = Column(Text, primary_key=True)             # UUID
    chat_id = Column(Text, nullable=False)          # 대상 채팅 ID
    message_id = Column(Text, nullable=False)       # 대상 메시지 ID
    user_id = Column(Text, nullable=False)          # 채팅 사용자 ID
    model_id = Column(Text, nullable=False)         # 평가 대상 모델
    judge_model_id = Column(Text, nullable=False)   # 심사 수행 모델

    evaluation_type = Column(Text, nullable=False)  # retrieval, faithfulness, quality

    # 평가 입력 (스냅샷)
    user_query = Column(Text, nullable=True)        # 사용자 질문
    assistant_response = Column(Text, nullable=True) # 어시스턴트 응답
    retrieved_contexts = Column(JSON, nullable=True) # RAG 검색 문서들

    # 평가 결과
    score = Column(Float, nullable=True)            # 0.0 ~ 1.0 (pending 시 null)
    reasoning = Column(Text, nullable=True)         # 평가 근거
    details = Column(JSON, nullable=True)           # 유형별 상세 정보

    status = Column(Text, default="pending")        # pending, completed, failed
    error_message = Column(Text, nullable=True)     # 실패 시 에러 메시지

    created_at = Column(BigInteger, nullable=False) # 생성 시간 (epoch)
    completed_at = Column(BigInteger, nullable=True) # 완료 시간 (epoch)
```

### 인덱스

```python
# migrations/versions/e5f6a7b8c9d0_add_auto_evaluation_table.py

op.create_index('ix_auto_evaluation_model_id', 'auto_evaluation', ['model_id'])
op.create_index('ix_auto_evaluation_chat_id', 'auto_evaluation', ['chat_id'])
op.create_index('ix_auto_evaluation_status', 'auto_evaluation', ['status'])
op.create_index('ix_auto_evaluation_created_at', 'auto_evaluation', ['created_at'])
```

## 2. 에이전트 메타 구조

### AutoEvaluation 설정

```typescript
// 에이전트 model.meta.autoEvaluation 구조

interface AutoEvaluationConfig {
  enabled: boolean;           // 자동 평가 활성화 여부
  samplingRate: number;       // 샘플링 비율 (0.01 ~ 1.0)
  evaluationTypes: string[];  // 평가 유형 ['retrieval', 'faithfulness', 'quality']
  judgeModelId: string | null; // 심사 모델 ID
}

// 예시
{
  "enabled": true,
  "samplingRate": 0.1,        // 10% 샘플링
  "evaluationTypes": ["retrieval", "faithfulness"],
  "judgeModelId": "gpt-4"
}
```

## 3. 평가 상태 흐름

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   pending   │────▶│  completed  │     │   failed    │
│  (대기중)   │     │   (완료)    │     │   (실패)    │
└─────────────┘     └─────────────┘     └─────────────┘
      │                                       ▲
      │                                       │
      └───────────────────────────────────────┘
               (평가 실행 중 오류 발생)
```

## 4. 통계 쿼리

### 기본 통계

```python
class AutoEvaluationTable:
    def get_stats(self) -> dict:
        with get_db() as db:
            from sqlalchemy import func

            # 총 카운트
            total_count = db.query(AutoEvaluation).count()
            completed_count = db.query(AutoEvaluation).filter_by(status="completed").count()
            pending_count = db.query(AutoEvaluation).filter_by(status="pending").count()
            failed_count = db.query(AutoEvaluation).filter_by(status="failed").count()

            # 평균 점수 (completed만)
            avg_score = db.query(func.avg(AutoEvaluation.score))\
                .filter(AutoEvaluation.status == "completed").scalar()

            # 모델별 통계
            by_model = db.query(
                AutoEvaluation.model_id,
                func.count(AutoEvaluation.id),
                func.avg(AutoEvaluation.score)
            ).filter(AutoEvaluation.status == "completed")\
             .group_by(AutoEvaluation.model_id).all()

            # 유형별 통계
            by_type = db.query(
                AutoEvaluation.evaluation_type,
                func.count(AutoEvaluation.id),
                func.avg(AutoEvaluation.score)
            ).filter(AutoEvaluation.status == "completed")\
             .group_by(AutoEvaluation.evaluation_type).all()

            return {
                "total_count": total_count,
                "completed_count": completed_count,
                "pending_count": pending_count,
                "failed_count": failed_count,
                "avg_score": avg_score,
                "by_model": {row[0]: {"count": row[1], "avg_score": row[2]} for row in by_model},
                "by_type": {row[0]: {"count": row[1], "avg_score": row[2]} for row in by_type}
            }
```

## 5. 필터링 및 페이지네이션

```python
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
    """
    필터링 및 페이지네이션을 적용한 평가 목록 조회

    Returns:
        (평가 목록, 전체 개수)
    """
    with get_db() as db:
        query = db.query(AutoEvaluation)

        # 필터 적용
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

        # 전체 개수
        total = query.count()

        # 정렬 및 페이지네이션
        sort_column = getattr(AutoEvaluation, sort_by, AutoEvaluation.created_at)
        if order == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        return ([AutoEvaluationModel.model_validate(ae) for ae in query.all()], total)
```
