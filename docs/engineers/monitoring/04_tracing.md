# 트레이싱 (Tracing)

## 1. 개요

트레이싱은 AI 요청의 전체 처리 과정을 추적하고 기록하는 기능입니다. LangSmith 스타일의 Run 기반 트리 구조를 사용하여 복잡한 체인 실행 흐름을 추적합니다.

### 주요 특징

- **Run 기반 트리 구조**: 각 처리 단계를 Run으로 기록하고 부모-자식 관계로 연결
- **dotted_order**: 계층 순서를 문자열로 표현 (예: "1.2.1")
- **trace_id 공유**: 같은 요청의 모든 Run이 동일한 trace_id 공유
- **다양한 Run 타입**: LLM, Tool, Retrieval, Guardrail 등 지원

## 2. 데이터 모델

### MessageTrace 테이블 구조

```python
# backend/open_webui/models/message_trace.py

class MessageTrace(Base):
    __tablename__ = "message_trace"

    # 핵심 ID 필드
    id = Column(String, primary_key=True)              # UUID (개별 Run ID)
    trace_id = Column(String, nullable=False)          # 같은 요청의 모든 Run 공유
    parent_run_id = Column(String, nullable=True)      # 부모 Run ID (트리 구조)
    dotted_order = Column(String, nullable=False)      # 계층 순서 ("1.2.1")

    # 컨텍스트 필드
    chat_id = Column(String, nullable=True)            # 채팅 ID
    message_id = Column(String, nullable=True)         # 메시지 ID
    user_id = Column(String, nullable=False)           # 사용자 ID

    # Run 정보
    run_type = Column(String, nullable=False)          # llm, tool, retrieval, chain 등
    name = Column(String, nullable=False)              # 실행 이름
    status = Column(String, nullable=False)            # pending, running, success, error

    # 입출력 데이터
    inputs = Column(JSON, nullable=True)               # 입력 데이터
    outputs = Column(JSON, nullable=True)              # 출력 데이터
    error = Column(Text, nullable=True)                # 오류 메시지

    # 타이밍 정보
    start_time = Column(BigInteger, nullable=False)    # 시작 시간 (ms)
    end_time = Column(BigInteger, nullable=True)       # 종료 시간 (ms)
    latency_ms = Column(Integer, nullable=True)        # 지연 시간

    # LLM 관련 정보
    token_usage = Column(JSON, nullable=True)          # {prompt_tokens, completion_tokens, total_tokens}
    model_id = Column(String, nullable=True)           # 모델 ID

    # 메타데이터
    meta = Column(JSON, nullable=True)                 # 추가 메타데이터

    # 타임스탬프
    created_at = Column(BigInteger, nullable=False)    # 생성 시간 (ms)
    updated_at = Column(BigInteger, nullable=False)    # 수정 시간 (ms)
```

### 인덱스

```python
__table_args__ = (
    Index("ix_message_trace_trace_id", "trace_id"),
    Index("ix_message_trace_chat_message", "chat_id", "message_id"),
    Index("ix_message_trace_user_created", "user_id", "created_at"),
    Index("ix_message_trace_status", "status"),
)
```

### RunType Enum

```python
class RunType(str, Enum):
    """Run 타입 정의 (LangSmith 호환)"""

    CHAIN = "chain"          # 복합 작업 (메시지 처리)
    LLM = "llm"              # LLM API 호출
    TOOL = "tool"            # 도구 실행
    RETRIEVAL = "retrieval"  # RAG 문서 검색
    WEB_SEARCH = "web_search"  # 웹 검색
    GUARDRAIL = "guardrail"  # 가드레일 체크
    EMBEDDING = "embedding"  # 임베딩 생성
    FILTER = "filter"        # 필터 함수 실행
    PIPELINE = "pipeline"    # 파이프라인 처리
```

### RunStatus Enum

```python
class RunStatus(str, Enum):
    """Run 상태"""

    PENDING = "pending"    # 대기 중
    RUNNING = "running"    # 실행 중
    SUCCESS = "success"    # 성공
    ERROR = "error"        # 오류
```

### Pydantic 모델

```python
class MessageTraceModel(BaseModel):
    """데이터베이스 레코드 모델"""
    id: str
    trace_id: str
    parent_run_id: Optional[str]
    dotted_order: str
    chat_id: Optional[str]
    message_id: Optional[str]
    user_id: str
    run_type: str
    name: str
    status: str
    inputs: Optional[dict]
    outputs: Optional[dict]
    error: Optional[str]
    start_time: int
    end_time: Optional[int]
    latency_ms: Optional[int]
    token_usage: Optional[dict]
    model_id: Optional[str]
    meta: Optional[dict]
    created_at: int
    updated_at: int


class MessageTraceResponse(MessageTraceModel):
    """API 응답용 모델 (트리 구조)"""
    children: Optional[list["MessageTraceResponse"]] = None


class TraceTreeResponse(BaseModel):
    """트레이스 트리 전체 응답"""
    trace_id: str
    chat_id: Optional[str]
    message_id: Optional[str]
    user_id: str
    total_latency_ms: Optional[int]
    total_tokens: Optional[int]
    status: str
    runs: list[MessageTraceResponse]
```

## 3. 백엔드 구현

### 트레이스 생성 로직

```python
# MessageTraceTable 클래스의 주요 메서드

def create_trace(self, form_data: MessageTraceCreateForm) -> Optional[MessageTraceModel]:
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

        db.add(trace)
        db.commit()
        return MessageTraceModel.model_validate(trace)


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

        db.commit()
        return MessageTraceModel.model_validate(trace)
```

### 트리 구조 조회

```python
def get_trace_tree(self, trace_id: str) -> Optional[TraceTreeResponse]:
    """trace_id로 트리 구조 조회"""
    traces = self.get_traces_by_trace_id(trace_id)
    if not traces:
        return None

    # 트리 구성
    trace_map = {t.id: MessageTraceResponse(**t.model_dump(), children=[]) for t in traces}
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
        elif trace.status == RunStatus.RUNNING.value and overall_status != RunStatus.ERROR.value:
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
```

### API 엔드포인트

```python
# backend/open_webui/routers/traces.py

router = APIRouter()

@router.get("/{trace_id}", response_model=TraceTreeResponse)
async def get_trace_by_id(trace_id: str, user=Depends(get_verified_user)):
    """특정 trace_id의 전체 트레이스 트리 조회"""
    trace_tree = MessageTraces.get_trace_tree(trace_id)

    if not trace_tree:
        raise HTTPException(status_code=404, detail="Trace not found")

    # 사용자 권한 확인 (자신의 트레이스 또는 admin)
    if trace_tree.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    return trace_tree


@router.get("/chat/{chat_id}/message/{message_id}", response_model=TraceTreeResponse)
async def get_trace_by_message(chat_id: str, message_id: str, user=Depends(get_verified_user)):
    """특정 채팅의 특정 메시지에 대한 트레이스 트리 조회"""
    trace_tree = MessageTraces.get_trace_tree_by_message(chat_id, message_id)
    # ...


@router.get("/chat/{chat_id}", response_model=list[MessageTraceModel])
async def list_traces_by_chat(
    chat_id: str,
    limit: int = Query(default=100, le=500),
    user=Depends(get_verified_user),
):
    """특정 채팅의 트레이스 목록 조회 (최상위 Run만)"""
    # ...


@router.get("/", response_model=dict)
async def list_traces(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=100),
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    run_type: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    user=Depends(get_verified_user),
):
    """트레이스 목록 조회 (페이지네이션)"""
    # 일반 사용자: 자신의 트레이스만
    # Admin: 모든 트레이스
    # ...


@router.get("/stats/summary", response_model=dict)
async def get_trace_stats(
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    user_id: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """트레이스 통계 조회"""
    # ...


@router.delete("/cleanup", response_model=dict)
async def cleanup_old_traces(
    before_timestamp_ms: int = Query(...),
    user=Depends(get_admin_user),
):
    """특정 시점 이전의 트레이스 삭제 (Admin 전용)"""
    # ...
```

### API 응답 형식

**GET /api/traces/**

```json
{
  "traces": [
    {
      "id": "uuid",
      "trace_id": "trace-uuid",
      "parent_run_id": null,
      "dotted_order": "1",
      "chat_id": "chat-uuid",
      "message_id": "msg-uuid",
      "user_id": "user-uuid",
      "run_type": "chain",
      "name": "Response",
      "status": "success",
      "inputs": {"user_message": "안녕하세요"},
      "outputs": {"result": "안녕하세요! 무엇을 도와드릴까요?"},
      "start_time": 1704067200000,
      "end_time": 1704067202340,
      "latency_ms": 2340,
      "token_usage": {"prompt_tokens": 150, "completion_tokens": 50, "total_tokens": 200},
      "model_id": "gpt-4",
      "meta": {"task": null},
      "created_at": 1704067200000,
      "updated_at": 1704067202340
    }
  ],
  "total": 100,
  "page": 1,
  "limit": 50,
  "total_pages": 2
}
```

**GET /api/traces/{trace_id}**

```json
{
  "trace_id": "trace-uuid",
  "chat_id": "chat-uuid",
  "message_id": "msg-uuid",
  "user_id": "user-uuid",
  "total_latency_ms": 2340,
  "total_tokens": 200,
  "status": "success",
  "runs": [
    {
      "id": "run-uuid-1",
      "trace_id": "trace-uuid",
      "parent_run_id": null,
      "dotted_order": "1",
      "run_type": "chain",
      "name": "Response",
      "status": "success",
      "latency_ms": 2340,
      "children": [
        {
          "id": "run-uuid-2",
          "trace_id": "trace-uuid",
          "parent_run_id": "run-uuid-1",
          "dotted_order": "1.1",
          "run_type": "llm",
          "name": "GPT-4",
          "status": "success",
          "latency_ms": 1890,
          "children": []
        }
      ]
    }
  ]
}
```

## 4. 프론트엔드 구현

### 컴포넌트 구조

```
src/lib/components/admin/Evaluations/
├── Tracing.svelte          # 메인 트레이싱 컴포넌트
├── RunTreeItem.svelte      # 재귀적 트리 아이템 컴포넌트
└── ...

src/lib/components/common/
└── JsonTreeView.svelte     # JSON 트리 뷰어 컴포넌트
```

### Tracing.svelte 주요 기능

```svelte
<script lang="ts">
  import { getTraces, getTraceById, type TraceRun, type TraceTree } from '$lib/apis/traces';

  // 상태
  let traces: TraceRun[] = [];
  let selectedTrace: TraceTree | null = null;
  let selectedRun: TraceRun | null = null;

  // 검색
  let searchQuery = '';
  let searchType: 'chat_id' | 'message_id' | 'trace_id' = 'chat_id';

  // 필터
  let statusFilter = '';
  let runTypeFilter = '';
  let dateRange = '7d';

  // 뷰 모드
  type ViewMode = 'json' | 'tree' | 'text';
  let inputsViewMode: ViewMode = 'tree';
  let outputsViewMode: ViewMode = 'tree';

  // 출력 검색
  let outputSearchQuery = '';
  let currentMatchIndex = 0;
  let totalMatches = 0;

  // 메시지별 그룹화
  interface TraceGroup {
    messageId: string | null;
    userMessage: string;
    traces: TraceRun[];
    totalLatency: number;
    hasError: boolean;
    latestTime: number;
  }

  // traces를 message_id로 그룹화
  $: groupedTraces = (() => {
    const groups = new Map<string, TraceGroup>();
    // ...그룹화 로직
    return Array.from(groups.values()).sort((a, b) => b.latestTime - a.latestTime);
  })();
</script>
```

### API 클라이언트

```typescript
// src/lib/apis/traces/index.ts

export interface TraceRun {
  id: string;
  trace_id: string;
  parent_run_id: string | null;
  dotted_order: string;
  chat_id: string | null;
  message_id: string | null;
  user_id: string;
  run_type: string;
  name: string;
  status: string;
  inputs: Record<string, any> | null;
  outputs: Record<string, any> | null;
  error: string | null;
  start_time: number;
  end_time: number | null;
  latency_ms: number | null;
  token_usage: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  } | null;
  model_id: string | null;
  meta: Record<string, any> | null;
  created_at: number;
  updated_at: number;
  children?: TraceRun[];
}

export interface TraceTree {
  trace_id: string;
  chat_id: string | null;
  message_id: string | null;
  user_id: string;
  total_latency_ms: number | null;
  total_tokens: number | null;
  status: string;
  runs: TraceRun[];
}

// API 함수들
export const getTraceById = async (token: string, traceId: string): Promise<TraceTree | null>;
export const getTraceByMessage = async (token: string, chatId: string, messageId: string): Promise<TraceTree | null>;
export const getTracesByChat = async (token: string, chatId: string, limit?: number): Promise<TraceRun[]>;
export const getTraces = async (token: string, params: TraceQueryParams): Promise<TraceListResponse>;
export const getTraceStats = async (token: string, params?: TraceStatsParams): Promise<TraceStats>;
export const cleanupTraces = async (token: string, beforeTimestampMs: number): Promise<CleanupResponse>;
```

### RunTreeItem 컴포넌트

재귀적으로 트리 구조를 렌더링합니다.

```svelte
<script lang="ts">
  import type { TraceRun } from '$lib/apis/traces';

  export let run: TraceRun;
  export let depth: number = 0;
  export let selectedRunId: string | null = null;

  const RUN_TYPE_CONFIG: Record<string, { color: string; label: string; shortLabel: string }> = {
    chain: { color: 'bg-purple-500', label: 'CHAIN', shortLabel: 'CH' },
    llm: { color: 'bg-blue-500', label: 'LLM', shortLabel: 'LM' },
    tool: { color: 'bg-green-500', label: 'TOOL', shortLabel: 'TL' },
    retrieval: { color: 'bg-orange-500', label: 'RAG', shortLabel: 'RG' },
    web_search: { color: 'bg-cyan-500', label: 'WEB', shortLabel: 'WB' },
    guardrail: { color: 'bg-red-500', label: 'GUARD', shortLabel: 'GD' },
    embedding: { color: 'bg-yellow-500', label: 'EMBED', shortLabel: 'EM' },
  };

  // 자식이 있는 TOOL인 경우 ACTION으로 그룹화 표시
  $: isAction = run.run_type === 'tool' && run.children && run.children.length > 0;
</script>
```

### JsonTreeView 컴포넌트

JSON 데이터를 계층적 트리 구조로 시각화합니다.

주요 기능:
- 재귀적 트리 렌더링
- 펼침/접힘 상태 관리
- 검색어 하이라이트
- 검색어 매치 시 자동 펼침
- 값 복사 기능
- JSON 문자열 자동 파싱

```svelte
<script lang="ts">
  export let data: any;
  export let depth: number = 0;
  export let maxDepthExpanded: number = 2;
  export let searchQuery: string = '';

  // 검색어 하이라이트
  const highlightSearch = (text: string, query: string): string => {
    if (!query.trim()) return escapeHtml(text);
    const escaped = escapeHtml(text);
    const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return escaped.replace(regex, '<mark class="bg-yellow-300">$1</mark>');
  };

  // 검색어가 있고 매치되면 자동으로 펼침
  $: hasMatch = searchQuery.trim() && containsSearchQuery(normalizedData, searchQuery);
  $: if (hasMatch) expanded = true;
</script>
```

## 5. 환경 변수

현재 트레이싱 관련 별도의 환경 변수는 없습니다. 트레이싱은 기본적으로 활성화되어 있으며, 시스템의 일반 데이터베이스 설정을 따릅니다.

향후 추가 가능한 환경 변수:

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `TRACING_ENABLED` | 트레이싱 활성화 여부 | `true` |
| `TRACE_RETENTION_DAYS` | 트레이스 보존 기간 (일) | `30` |
| `TRACE_MAX_INPUT_SIZE` | 입력 데이터 최대 크기 (bytes) | `1MB` |

## 6. 관련 파일

### 백엔드

| 파일 | 설명 |
|------|------|
| `backend/open_webui/routers/traces.py` | API 라우터 |
| `backend/open_webui/models/message_trace.py` | 데이터 모델 및 테이블 operations |
| `backend/open_webui/main.py` | 라우터 등록 |

### 프론트엔드

| 파일 | 설명 |
|------|------|
| `src/lib/apis/traces/index.ts` | API 클라이언트 |
| `src/lib/components/admin/Evaluations/Tracing.svelte` | 메인 트레이싱 UI |
| `src/lib/components/admin/Evaluations/RunTreeItem.svelte` | 트리 아이템 컴포넌트 |
| `src/lib/components/common/JsonTreeView.svelte` | JSON 트리 뷰어 |

### 데이터베이스

| 테이블 | 설명 |
|--------|------|
| `message_trace` | 트레이스 레코드 저장 |

## 7. 트레이스 생성 예시

### LLM 호출 트레이싱

```python
from open_webui.models.message_trace import MessageTraces, MessageTraceCreateForm, RunType, RunStatus

# 트레이스 시작
trace = MessageTraces.create_trace(
    MessageTraceCreateForm(
        trace_id="trace-123",
        parent_run_id=None,
        dotted_order="1",
        chat_id="chat-456",
        message_id="msg-789",
        user_id="user-001",
        run_type=RunType.LLM.value,
        name="GPT-4 Completion",
        status=RunStatus.RUNNING.value,
        inputs={"messages": [{"role": "user", "content": "Hello"}]},
        model_id="gpt-4",
    )
)

# LLM 호출 수행...

# 트레이스 완료
MessageTraces.complete_trace(
    trace_id=trace.id,
    outputs={"result": "Hello! How can I help you?"},
    token_usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
)
```

### 중첩 트레이스 (Chain + LLM)

```python
# 상위 Chain 트레이스
chain_trace = MessageTraces.create_trace(
    MessageTraceCreateForm(
        trace_id="trace-123",
        parent_run_id=None,
        dotted_order="1",
        run_type=RunType.CHAIN.value,
        name="Response Generation",
        # ...
    )
)

# 하위 LLM 트레이스
llm_trace = MessageTraces.create_trace(
    MessageTraceCreateForm(
        trace_id="trace-123",  # 같은 trace_id 공유
        parent_run_id=chain_trace.id,  # 부모 지정
        dotted_order="1.1",  # 계층 순서
        run_type=RunType.LLM.value,
        name="GPT-4",
        # ...
    )
)
```

## 8. 통계 쿼리

```python
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

        # 필터 적용
        if from_date:
            query = query.filter(MessageTrace.created_at >= from_date)
        if to_date:
            query = query.filter(MessageTrace.created_at <= to_date)
        if user_id:
            query = query.filter(MessageTrace.user_id == user_id)

        # 타입별 카운트
        type_counts = query.with_entities(
            MessageTrace.run_type, func.count(MessageTrace.id)
        ).group_by(MessageTrace.run_type).all()

        # 상태별 카운트
        status_counts = query.with_entities(
            MessageTrace.status, func.count(MessageTrace.id)
        ).group_by(MessageTrace.status).all()

        # 평균 레이턴시
        avg_latency = query.with_entities(
            func.avg(MessageTrace.latency_ms)
        ).filter(MessageTrace.latency_ms != None).scalar()

        return {
            "by_type": {rt: count for rt, count in type_counts},
            "by_status": {status: count for status, count in status_counts},
            "avg_latency_ms": round(avg_latency, 2) if avg_latency else None,
            "total": query.count(),
        }
```
