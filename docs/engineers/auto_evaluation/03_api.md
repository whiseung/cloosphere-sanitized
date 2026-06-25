> Last Updated: 2026-04-08

# Auto Evaluation API

**License gate**: `require_feature("evaluation")` (전체 라우터)
**Router**: `backend/open_webui/routers/auto_evaluations.py` (10 endpoints)

## 1. API 엔드포인트

### 라우터 등록

```python
# backend/open_webui/main.py
from open_webui.routers import auto_evaluations
app.include_router(auto_evaluations.router, prefix="/api/v1/auto-evaluations", tags=["auto-evaluations"])
```

### 엔드포인트 목록 (10개)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | 평가 목록 조회 (필터, 페이지네이션). 응답에 user 정보 포함 (`AutoEvaluationListResponse`) |
| GET | `/stats` | 통계 조회 (`AutoEvaluationStatsResponse`) |
| GET | `/export` | 전체 데이터 내보내기 (JSON/CSV) |
| GET | `/{id}` | 특정 평가 상세 조회 (`AutoEvaluationWithUserResponse` — user info 포함) |
| POST | `/` | 새 평가 생성 (테스트/수동용) |
| PUT | `/{id}` | 평가 결과 업데이트 |
| DELETE | `/{id}` | **특정 평가 삭제** |
| DELETE | `/` | **전체 평가 일괄 삭제 (admin)** |
| GET | `/chat/{chat_id}` | 특정 채팅의 평가 목록 |
| GET | `/message/{message_id}` | 특정 메시지의 평가 목록 |

> **신규 엔드포인트**: `DELETE /{id}`, `DELETE /` (bulk), `AutoEvaluationWithUserResponse` 응답 타입은 2026-03 추가. 과거 문서는 `DELETE /{id}`만 명시했었음.

## 2. 요청/응답 스키마

### AutoEvaluationForm (생성 요청)

```python
class AutoEvaluationForm(BaseModel):
    chat_id: str
    message_id: str
    model_id: str
    judge_model_id: str
    evaluation_type: str  # retrieval, faithfulness, quality

    user_query: Optional[str] = None
    assistant_response: Optional[str] = None
    retrieved_contexts: Optional[list[dict]] = None
```

### AutoEvaluationUpdateForm (업데이트 요청)

```python
class AutoEvaluationUpdateForm(BaseModel):
    score: Optional[float] = None        # 0.0 ~ 1.0
    reasoning: Optional[str] = None      # 평가 근거
    details: Optional[dict] = None       # 상세 정보
    status: Optional[str] = None         # pending, completed, failed
    error_message: Optional[str] = None  # 실패 시 에러
```

### AutoEvaluationListResponse (목록 응답)

```python
class AutoEvaluationListResponse(BaseModel):
    items: list[AutoEvaluationResponse]
    total: int
    page: int
    limit: int
```

### AutoEvaluationStatsResponse (통계 응답)

```python
class AutoEvaluationStatsResponse(BaseModel):
    total_count: int
    completed_count: int
    pending_count: int
    failed_count: int
    avg_score: Optional[float] = None
    by_model: dict  # {model_id: {count, avg_score}}
    by_type: dict   # {evaluation_type: {count, avg_score}}
```

## 3. API 사용 예시

### 평가 목록 조회

```bash
GET /api/v1/auto-evaluations/?model_id=gpt-4&status=completed&page=1&limit=20

# 응답
{
  "items": [
    {
      "id": "uuid",
      "chat_id": "chat_123",
      "message_id": "msg_456",
      "model_id": "gpt-4",
      "judge_model_id": "gpt-4",
      "evaluation_type": "quality",
      "score": 0.85,
      "reasoning": "응답이 명확하고 정확합니다...",
      "status": "completed",
      "created_at": 1706000000,
      "completed_at": 1706000010
    }
  ],
  "total": 150,
  "page": 1,
  "limit": 20
}
```

### 통계 조회

```bash
GET /api/v1/auto-evaluations/stats

# 응답
{
  "total_count": 500,
  "completed_count": 450,
  "pending_count": 30,
  "failed_count": 20,
  "avg_score": 0.78,
  "by_model": {
    "gpt-4": {"count": 200, "avg_score": 0.82},
    "claude-3": {"count": 150, "avg_score": 0.80},
    "my-agent": {"count": 100, "avg_score": 0.75}
  },
  "by_type": {
    "quality": {"count": 250, "avg_score": 0.80},
    "retrieval": {"count": 150, "avg_score": 0.75},
    "faithfulness": {"count": 50, "avg_score": 0.78}
  }
}
```

### 내보내기

```bash
# JSON 형식
GET /api/v1/auto-evaluations/export?format=json

# CSV 형식
GET /api/v1/auto-evaluations/export?format=csv
```

### 평가 생성 (테스트용)

```bash
POST /api/v1/auto-evaluations/

{
  "chat_id": "chat_123",
  "message_id": "msg_456",
  "model_id": "my-agent",
  "judge_model_id": "gpt-4",
  "evaluation_type": "quality",
  "user_query": "매출 데이터를 분석해주세요.",
  "assistant_response": "2023년 4분기 매출은 전년 대비 15% 증가했습니다..."
}
```

## 4. 프론트엔드 API 클라이언트

```typescript
// src/lib/apis/auto-evaluations/index.ts

export type AutoEvaluationFilter = {
  model_id?: string;
  evaluation_type?: string;
  status?: string;
  score_min?: number;
  score_max?: number;
  date_from?: number;
  date_to?: number;
  page?: number;
  limit?: number;
  sort_by?: string;
  order?: string;
};

export const getAutoEvaluations = async (
  token: string,
  filters: AutoEvaluationFilter = {}
): Promise<AutoEvaluationListResponse> => {
  const params = new URLSearchParams();
  if (filters.model_id) params.append('model_id', filters.model_id);
  if (filters.evaluation_type) params.append('evaluation_type', filters.evaluation_type);
  if (filters.status) params.append('status', filters.status);
  if (filters.date_from) params.append('date_from', filters.date_from.toString());
  if (filters.date_to) params.append('date_to', filters.date_to.toString());
  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/?${params}`, {
    headers: { authorization: `Bearer ${token}` }
  });
  return res.json();
};

export const getAutoEvaluationStats = async (
  token: string
): Promise<AutoEvaluationStats> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/stats`, {
    headers: { authorization: `Bearer ${token}` }
  });
  return res.json();
};

export const exportAutoEvaluations = async (
  token: string,
  format: 'json' | 'csv' = 'json'
): Promise<any> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/export?format=${format}`, {
    headers: {
      Accept: format === 'csv' ? 'text/csv' : 'application/json',
      authorization: `Bearer ${token}`
    }
  });
  return format === 'csv' ? res.text() : res.json();
};
```
