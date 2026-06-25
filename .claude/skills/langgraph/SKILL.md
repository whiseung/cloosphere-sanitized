---
name: langgraph
description: LangGraph 기반 상태 그래프, Command, reducer, 스트리밍, 체크포인트 가이드.
---

# LangGraph 개발 가이드

Cloosphere는 LangGraph 1.0.5를 사용합니다. 상태 그래프 구성, Command 패턴, 스트리밍을 다룹니다.

## 패키지 구조

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `langgraph` | 1.0.5 | StateGraph, 핵심 런타임 |
| `langgraph-prebuilt` | 1.0.5 | create_react_agent (레거시, 하위호환) |
| `langgraph-checkpoint` | 3.0.1 | 체크포인트/메모리 |

## 1. Command (도구에서 상태 업데이트)

도구가 단순 문자열 대신 **상태를 직접 업데이트**할 때 사용:

```python
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import ToolRuntime

async def run_sql(
    sql: str,
    runtime: ToolRuntime[None, DBSphereAgentState],
) -> Command:
    result = await sql_runner.execute(sql)
    return Command(
        update={
            "messages": [ToolMessage(result, tool_call_id=runtime.tool_call_id)],
            "executed_sql": sql,
            "query_result_file": result_file,
            "query_history": [sql],  # Annotated[List, operator.add] → 자동 병합
        }
    )
```

**⚠️ 주의**: `messages`에 `ToolMessage`를 반드시 포함해야 LLM이 도구 호출 결과를 인식

**참조**: `extension_modules/dbsphere/tools/run_sql.py:81-100`, `extension_modules/react/react_base.py:106-119`

## 2. Annotated Reducer (병렬 도구 호출)

여러 도구가 동시에 실행될 때 상태 필드 병합 전략:

```python
from typing import Annotated, List
import operator

def _last_value(a, b):
    """마지막 값으로 덮어쓰기"""
    return b

class CustomAgentState(AgentState):
    # 리스트 병합: 도구 A가 [sql1], 도구 B가 [sql2] → [sql1, sql2]
    query_history: Annotated[List[str], operator.add] = Field(default_factory=list)

    # 마지막 값 사용: 여러 도구가 쓰면 마지막 것만 유지
    executed_sql: Annotated[str, _last_value] = ""

    # 기본 (reducer 없음): 마지막 값으로 덮어쓰기
    language: str = ""
```

**참조**: `extension_modules/agent/unified_state.py:15-67`

## 3. StateGraph (Agent Flow)

복잡한 워크플로우를 노드/엣지 그래프로 구성:

```python
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

class FlowState(TypedDict):
    messages: list
    current_node: str

graph = StateGraph(FlowState)

# 노드 추가
graph.add_node("search", search_function)
graph.add_node("analyze", analyze_function)
graph.add_node("respond", respond_function)

# 엣지 추가
graph.set_entry_point("search")
graph.add_edge("search", "analyze")

# 조건부 엣지
graph.add_conditional_edges(
    "analyze",
    lambda state: "respond" if state["enough_data"] else "search",
    {"respond": "respond", "search": "search"},
)
graph.add_edge("respond", END)

# 컴파일
compiled = graph.compile()
result = await compiled.ainvoke(initial_state)
```

**참조**: `extension_modules/agent_flow/agent_flow_runner.py:234-304`

## 4. 에이전트 실행 (스트리밍)

### astream (값 기반)

```python
# 중간 상태를 캡처하여 구조화 출력 파싱 실패 시 복구
last_state = initial_state
try:
    async for state in agent.astream(initial_state, stream_mode="values"):
        last_state = state
    result = last_state
except Exception as e:
    if "structured output" in str(e).lower():
        result = last_state  # 도구 결과는 보존됨
        result.setdefault("answerable", True)
    else:
        raise
```

**참조**: `extension_modules/agent/unified_agent.py:884-900`

### astream_events (이벤트 기반, 레거시)

```python
async for chunk in agent.astream_events(
    {"messages": messages}, version="v2"
):
    kind = chunk["event"]
    data = chunk["data"]
    if kind == "on_chat_model_stream":
        # LLM 스트리밍 청크
    elif kind == "on_tool_start":
        # 도구 실행 시작
    elif kind == "on_chat_model_end":
        # LLM 완료
```

**참조**: `extension_modules/pipes/base.py:258-327`

## 5. create_react_agent (레거시/하위호환)

`langgraph.prebuilt`에 여전히 존재하지만 **`langchain.agents.create_agent` 사용 권장**:

```python
# ❌ 레거시 (동작하지만 비권장)
from langgraph.prebuilt import create_react_agent
agent = create_react_agent(model, tools, prompt=system_prompt)

# ✅ 권장
from langchain.agents import create_agent
agent = create_agent(model, tools, system_prompt=system_prompt)
```

**차이점**:
- `create_agent`: `system_prompt`, `middleware`, `response_format` 지원
- `create_react_agent`: `prompt` 파라미터, 콜백 기반

## 6. 체크포인트

대화 상태를 영속 저장하여 재개 가능:

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
compiled = graph.compile(checkpointer=checkpointer)

# 실행 (thread_id로 대화 식별)
config = {"configurable": {"thread_id": "user-123"}}
result = await compiled.ainvoke(state, config)

# 재개
result2 = await compiled.ainvoke(new_state, config)  # 이전 상태 이어서
```

## 프로젝트 활용 패턴

### UnifiedAgent 실행 흐름

```
1. create_agent() 호출 → CompiledStateGraph 반환
2. agent.astream(state, stream_mode="values")
   ├── LLM 호출 → 도구 선택
   ├── 도구 실행 → Command로 상태 업데이트
   ├── LLM 재호출 → 추가 도구 또는 종료 판단
   └── 구조화 출력 (UnifiedAgentOutput) 반환
3. 결과에서 sources, tool results 추출
4. final_answer LLM으로 최종 답변 스트리밍
```

### Agent Flow (StateGraph 직접 사용)

```
1. Flow 정의 (노드 + 엣지, 프론트엔드 편집기)
2. agent_flow_runner.py에서 StateGraph 동적 생성
3. 각 노드 = LLM 호출 또는 도구 실행
4. 조건부 엣지 = LLM 판단 기반 분기
5. compile() → ainvoke() 실행
```

## 주요 참조 파일

| 파일 | 내용 |
|------|------|
| `extension_modules/agent/unified_agent.py:884` | astream 실행 + 에러 복구 |
| `extension_modules/agent/unified_state.py` | State + Annotated reducer |
| `extension_modules/dbsphere/tools/run_sql.py` | Command 반환 패턴 |
| `extension_modules/react/react_base.py:106` | Command + ToolMessage |
| `extension_modules/agent_flow/agent_flow_runner.py:234` | StateGraph 동적 생성 |
| `extension_modules/pipes/base.py:258` | astream_events 레거시 |

## 주의사항

- `state_schema`는 **TypedDict만** 허용 (LangChain v1.0 제약)
- `Command.update`에는 `state_schema`에 정의된 필드만 사용 가능
- Annotated reducer 없는 리스트 필드에 `operator.add` 미적용 시 덮어쓰기됨
- `astream(stream_mode="values")`는 매 노드 실행 후 전체 상태를 yield
- `astream_events(version="v2")`는 세밀한 이벤트 제어 (레거시 pipes에서만 사용)
- `graph.compile()` 후에는 도구 리스트 변경 불가 (런타임 교체 안 됨)
