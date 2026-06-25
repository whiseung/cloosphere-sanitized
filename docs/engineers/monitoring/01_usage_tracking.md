> Last Updated: 2026-04-08

# Usage Tracking (사용량 추적)

## 1. 개요

Usage Tracking은 Cloosphere에서 발생하는 모든 LLM API 호출을 추적하고 기록합니다. 이를 통해 비용 분석, 사용 패턴 분석, 리소스 최적화가 가능합니다.

## 2. 데이터베이스 모델

### Usage 테이블

```python
# backend/open_webui/models/usage.py

class Usage(Base):
    __tablename__ = "log_usage"

    id = Column(String, primary_key=True)           # UUID
    user_id = Column(String)                         # 사용자 ID
    chat_id = Column(String)                         # 채팅 ID
    agent_id = Column(String, nullable=True)         # 워크스페이스 에이전트 ID
    model_id = Column(String)                        # 실제 LLM 모델 ID
    message_id = Column(String)                      # 메시지 ID
    message_step = Column(Integer)                   # 에이전트 단계
    message_type = Column(String)                    # 메시지 유형
    total_tokens = Column(Integer)                   # 총 토큰 수
    usage = Column(JSON, nullable=True)              # 상세 usage 정보
    tool_calls = Column(JSON, nullable=True)         # 도구 호출 정보
    created_at = Column(BigInteger)                  # 생성 시간
    updated_at = Column(BigInteger)                  # 수정 시간
```

### Message Type Enum

```python
class UsageMessageType(Enum):
    # 일반 채팅
    CHAT = "chat"

    # 임베딩
    EMBEDDING = "embedding"

    # 에이전트 관련
    AGENT_STATE = "agent_state"
    TOOL_CALL = "tool_call"
    REASONING = "reasoning"

    # 백그라운드 태스크
    TITLE_GENERATION = "title_generation"
    TAGS_GENERATION = "tags_generation"
    EMOJI_GENERATION = "emoji_generation"
    QUERY_GENERATION = "query_generation"
    IMAGE_PROMPT_GENERATION = "image_prompt_generation"
    AUTOCOMPLETE_GENERATION = "autocomplete_generation"
    FUNCTION_CALLING = "function_calling"
    MOA_RESPONSE_GENERATION = "moa_response_generation"

    # 기타
    GENERATION = "generation"
    SYSTEM = "system"
```

### Usage JSON 필드 구조

```python
usage = {
    "input_tokens": 150,
    "output_tokens": 250,
    "total_tokens": 400,
    "completion_tokens": 250,  # OpenAI 호환
    "prompt_tokens": 150,      # OpenAI 호환
    "cached_tokens": 0,        # 캐시된 토큰
}
```

## 3. Agent ID vs Model ID

### 개념 분리

| 필드 | 설명 | 예시 |
|------|------|------|
| `agent_id` | 워크스페이스에서 생성한 에이전트 | `my-knowledge-agent` |
| `model_id` | 실제 사용된 LLM 모델 | `gpt-4`, `claude-3-opus` |

### 판별 로직

```python
# 에이전트 vs 일반 모델 판별

model_info = metadata.get("model", {})
base_model_id = model_info.get("info", {}).get("base_model_id")

if base_model_id:
    # 에이전트 - base_model_id가 있음
    agent_id = model_info.get("id")
    model_id = base_model_id  # 실제 LLM
else:
    # 일반 모델 - base_model_id가 없음
    agent_id = None
    model_id = model_info.get("id")
```

### 데이터 예시

**일반 채팅 (GPT-4 직접 사용)**:
```json
{
  "agent_id": null,
  "model_id": "gpt-4"
}
```

**에이전트 채팅 (Knowledge Agent → GPT-4)**:
```json
{
  "agent_id": "my-knowledge-agent",
  "model_id": "gpt-4"
}
```

## 4. 추적 포인트

### 4.1 OpenAI 라우터 (일반 채팅)

```python
# backend/open_webui/routers/openai.py

@router.post("/chat/completions")
async def generate_chat_completion(...):
    # 원본 모델 ID 저장
    original_model_id = model_id

    # 스트리밍 시 usage 옵션 추가
    if is_streaming:
        payload["stream_options"] = {"include_usage": True}

    # 응답 처리
    response = await call_llm(payload)

    # Usage 추적
    if is_streaming:
        return await stream_with_usage_tracking(
            response,
            user_id=user.id,
            chat_id=chat_id,
            message_id=message_id,
            model_id=model_id,
            agent_id=agent_id,
            task_type=task_type,  # 백그라운드 태스크인 경우
        )
    else:
        # 비스트리밍 응답에서 usage 추출
        usage = response.get("usage", {})
        Usages.insert_new_usage(
            user_id=user.id,
            chat_id=chat_id,
            model_id=model_id,
            agent_id=agent_id,
            message_id=message_id,
            message_type=UsageMessageType.CHAT,
            total_tokens=usage.get("total_tokens", 0),
            usage=usage,
        )
```

### 4.2 스트리밍 Usage 추출

```python
async def stream_with_usage_tracking(
    response,
    user_id: str,
    chat_id: str,
    message_id: str,
    model_id: str,
    agent_id: str = None,
    task_type: str = None,
):
    """SSE 스트림에서 usage 정보 추출"""
    usage_data = None

    async for chunk in response.content:
        # 청크 전달
        yield chunk

        # usage 정보 추출
        if chunk.startswith(b"data: "):
            try:
                data = json.loads(chunk[6:])
                if "usage" in data:
                    usage_data = data["usage"]
            except:
                pass

    # 스트림 종료 후 usage 기록
    if usage_data:
        message_type = task_type if task_type else UsageMessageType.CHAT
        Usages.insert_new_usage(
            user_id=user_id,
            chat_id=chat_id,
            agent_id=agent_id,
            model_id=model_id,
            message_id=message_id or f"task:{task_type}",
            message_type=message_type,
            total_tokens=usage_data.get("total_tokens", 0),
            usage=usage_data,
        )
```

### 4.3 에이전트 미들웨어 (ReAct Agent)

```python
# backend/extension_modules/react/react_middleware_base.py

class MiddlewareBase(AgentMiddleware):
    async def aafter_model(
        self, state: AgentStateBase, runtime: Runtime
    ) -> dict[str, Any] | None:
        ai_message = state.get("messages", [])[-1]

        if isinstance(ai_message, AIMessage):
            usage = ai_message.usage_metadata
            tool_calls = ai_message.content_blocks

            # 메시지 타입 결정
            if tool_calls:
                message_type = UsageMessageType.TOOL_CALL
            else:
                message_type = UsageMessageType.AGENT_STATE

            # 에이전트 ID 판별
            model_info = self.metadata.get("model", {})
            base_model_id = model_info.get("info", {}).get("base_model_id")
            agent_id = model_info.get("id") if base_model_id else None

            # Usage 기록
            Usages.insert_new_usage(
                user_id=self.metadata.get("user_id"),
                chat_id=self.metadata.get("chat_id"),
                agent_id=agent_id,
                model_id=self.metadata.get("llm_model_id"),
                message_id=self.metadata.get("message_id"),
                message_step=self.message_step,
                message_type=message_type,
                total_tokens=usage.get("total_tokens"),
                usage=usage,
                tool_calls=tool_calls,
            )
```

### 4.4 임베딩 Usage

```python
# backend/open_webui/retrieval/utils.py

def generate_openai_batch_embeddings(
    model: str,
    texts: list[str],
    key: str,
    url: str,
    user: UserModel = None,  # Usage 추적용
):
    # API 호출
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()

    # Usage 추적
    if user and "usage" in data:
        usage_data = data["usage"]
        Usages.insert_new_usage(
            user_id=user.id,
            chat_id="",
            model_id=model,
            message_id=f"embedding:{len(texts)}",
            message_type=UsageMessageType.EMBEDDING,
            total_tokens=usage_data.get("total_tokens", 0),
            usage=usage_data,
        )

    return data["data"]
```

## 5. API 엔드포인트 (18개)

**Router**: `backend/open_webui/routers/usage.py`
**Base path**: `/api/v1/usages`
**Auth**: 대부분 `get_admin_user` 또는 `get_admin_monitoring_read_access`

### 엔드포인트 목록

#### Filter (카스케이딩 필터 드롭다운 소스)

| Method | Path | Description | Response |
|---|---|---|---|
| GET | `/filters/models` | 사용 데이터에 실제 존재하는 model ID 목록 | `list[FilterOptionItem]` |
| GET | `/filters/users` | 사용 데이터에 실제 존재하는 user 목록 | `list[FilterOptionItem]` |
| GET | `/filters/groups` | 사용 데이터에 실제 존재하는 group 목록 | `list[FilterOptionItem]` |
| GET | `/filters/organizations` | 사용 데이터에 실제 존재하는 organization 목록 | `list[FilterOptionItem]` |
| GET | `/filters/agents` | 사용 데이터에 실제 존재하는 agent 목록 | `list[FilterOptionItem]` |

#### Real-time + 통계

| Method | Path | Description | Response |
|---|---|---|---|
| GET | `/online-users` | 현재 온라인 사용자 (최근 활동 기준) | `OnlineUsersResponse` |
| GET | `/stats` | 통합 통계 (토큰, 요청, 활성 사용자 등) | `UsageStatsResponse` |
| GET | `/trends` | 시계열 추이 (일/주/월) | `list[UsageTrendItem]` |

#### 차원별 집계 (dimension breakdown)

| Method | Path | Description | Response |
|---|---|---|---|
| GET | `/by-model` | 모델별 사용량 집계 | `list[UsageByModelItem]` |
| GET | `/by-user` | 사용자별 사용량 집계 | `list[UsageByUserItem]` |
| GET | `/by-group` | 그룹별 사용량 집계 | `list[UsageByGroupItem]` |
| GET | `/by-organization` | 조직별 사용량 집계 | `list[UsageByOrganizationItem]` |
| GET | `/by-type` | message_type별 집계 (chat, embedding, tool_call …) | `list[UsageByTypeItem]` |
| GET | `/by-agent` | Agent별 집계 (워크스페이스 에이전트 단위) | `list[UsageByAgentItem]` |

#### Conversation Logs (세부 대화 이력)

| Method | Path | Description |
|---|---|---|
| GET | `/conversation-logs` | 대화 로그 목록 (chat_id, message별 세부) |
| GET | `/conversation-logs/stats` | 대화 로그 통계 |
| GET | `/conversation-logs/filters/models` | 대화 로그 필터: 모델 |
| GET | `/conversation-logs/filters/users` | 대화 로그 필터: 사용자 |

### 공통 쿼리 파라미터

대부분 엔드포인트가 공유하는 필터:

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `from_date` | int | 시작 날짜 (Unix timestamp) |
| `to_date` | int | 종료 날짜 |
| `group_by` | str | `day` / `week` / `month` (/trends, /stats) |
| `model_ids` | list[str] | 콤마 구분 모델 필터 |
| `user_ids` | list[str] | 콤마 구분 사용자 필터 |
| `group_ids` | list[str] | 그룹 필터 |
| `organization_ids` | list[str] | 조직 필터 |
| `agent_ids` | list[str] | 에이전트 필터 |
| `message_types` | list[str] | `chat`, `embedding`, `tool_call` 등 필터 |

### 주요 Response 타입 (개요)

```python
class FilterOptionItem(BaseModel):
    value: str
    label: str
    count: int            # 해당 옵션의 실제 사용 건수 (cascading 용)

class UsageStatsResponse(BaseModel):
    total_tokens: int
    total_requests: int
    active_users: int
    ...

class UsageTrendItem(BaseModel):
    date: str
    total_tokens: int
    total_requests: int
    ...

class UsageByModelItem(BaseModel):
    model_id: str
    model_name: str
    total_tokens: int
    total_requests: int
    ...
```

### 레거시 엔드포인트 (제거됨)

과거 문서에 있던 `GET /`, `GET /my` 엔드포인트는 현재 라우터에 **존재하지 않습니다**. 사용자 본인 조회는 `/by-user` + user_id 필터로 대체되었고, 목록 조회는 `/conversation-logs`로 이관되었습니다.

## 6. 프론트엔드

### Usage 컴포넌트

```svelte
<!-- src/lib/components/admin/Monitoring/Usage.svelte -->
<script lang="ts">
  import { getUsageStats } from '$lib/apis/usage';

  let dateRange = { start: null, end: null };
  let filters = {
    user_id: '',
    agent_id: '',
    model_id: ''
  };
  let stats = null;

  async function loadStats() {
    stats = await getUsageStats(
      localStorage.token,
      dateRange.start,
      dateRange.end,
      filters
    );
  }
</script>

<!-- 필터 영역 -->
<div class="filters">
  <DateRangePicker bind:value={dateRange} />
  <UserSelect bind:value={filters.user_id} />
  <AgentSelect bind:value={filters.agent_id} />
  <ModelSelect bind:value={filters.model_id} />
  <button on:click={loadStats}>조회</button>
</div>

<!-- 통계 차트 -->
{#if stats}
  <UsageChart data={stats.daily} />
  <TokenSummary data={stats.summary} />
  <TopUsersTable data={stats.top_users} />
{/if}
```

### API 클라이언트

```typescript
// src/lib/apis/usage/index.ts

export const getUsageStats = async (
  token: string,
  startDate?: number,
  endDate?: number,
  filters?: UsageFilters
): Promise<UsageStats> => {
  const params = new URLSearchParams();
  if (startDate) params.append('start_date', startDate.toString());
  if (endDate) params.append('end_date', endDate.toString());
  if (filters?.user_id) params.append('user_id', filters.user_id);
  if (filters?.agent_id) params.append('agent_id', filters.agent_id);
  if (filters?.model_id) params.append('model_id', filters.model_id);

  const res = await fetch(`${WEBUI_API_BASE_URL}/usage/stats?${params}`, {
    headers: { authorization: `Bearer ${token}` }
  });
  if (!res.ok) throw await res.json();
  return res.json();
};
```

## 7. 통계 쿼리

### 일별 사용량

```python
def get_daily_usage(start_date: int, end_date: int):
    with get_db() as db:
        return db.query(
            func.date(func.datetime(Usage.created_at, 'unixepoch')).label('date'),
            func.sum(Usage.total_tokens).label('total_tokens'),
            func.count(Usage.id).label('request_count'),
        ).filter(
            Usage.created_at >= start_date,
            Usage.created_at <= end_date,
        ).group_by('date').all()
```

### 사용자별 사용량

```python
def get_usage_by_user(start_date: int, end_date: int):
    with get_db() as db:
        return db.query(
            Usage.user_id,
            func.sum(Usage.total_tokens).label('total_tokens'),
            func.count(Usage.id).label('request_count'),
        ).filter(
            Usage.created_at >= start_date,
            Usage.created_at <= end_date,
        ).group_by(Usage.user_id).all()
```

### 모델별 사용량

```python
def get_usage_by_model(start_date: int, end_date: int):
    with get_db() as db:
        return db.query(
            Usage.model_id,
            func.sum(Usage.total_tokens).label('total_tokens'),
            func.count(Usage.id).label('request_count'),
        ).filter(
            Usage.created_at >= start_date,
            Usage.created_at <= end_date,
        ).group_by(Usage.model_id).all()
```
