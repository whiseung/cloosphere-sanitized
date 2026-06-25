# Agent Flow 아키텍처

## 데이터 모델

### Models 테이블 활용

Agent Flow는 별도 테이블 없이 기존 `Models` 테이블을 활용합니다.

```python
# Models 테이블 필드 활용
{
    "id": "flow.{uuid}",              # flow. 접두사
    "name": "문서 분석 플로우",
    "base_model_id": None,            # Flow는 base_model 없음
    "meta": {
        "type": "agent_flow",         # Flow 식별자
        "flow_data": {                # 플로우 데이터
            "nodes": [...],
            "edges": [...],
            "variables": {}
        },
        "description": "..."
    },
    "is_active": True
}
```

### flow_data 구조

```json
{
    "nodes": [
        {
            "id": "node_1",
            "type": "flowInput",
            "position": {"x": 100, "y": 100},
            "data": {
                "label": "Input",
                "config": {}
            }
        },
        {
            "id": "node_2",
            "type": "agent",
            "position": {"x": 300, "y": 100},
            "data": {
                "label": "에이전트",
                "resourceId": "agent-uuid",
                "config": {
                    "temperature": 0.7
                }
            }
        },
        {
            "id": "node_3",
            "type": "flowOutput",
            "position": {"x": 500, "y": 100},
            "data": {
                "label": "Output",
                "config": {}
            }
        }
    ],
    "edges": [
        {
            "id": "edge_1",
            "source": "node_1",
            "target": "node_2",
            "sourceHandle": "output",
            "targetHandle": "input"
        },
        {
            "id": "edge_2",
            "source": "node_2",
            "target": "node_3",
            "sourceHandle": "output",
            "targetHandle": "input"
        }
    ],
    "variables": {}
}
```

## 실행 엔진

### LangGraph StateGraph

```python
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

class AgentFlowRunner:
    def _build_graph(self, nodes, edges) -> CompiledStateGraph:
        graph = StateGraph(FlowState)

        # 1. 노드 추가
        for node in nodes:
            node_func = self._create_node_function(node_id, node_type, node_data)
            graph.add_node(node_id, node_func)

        # 2. 엣지 추가
        for edge in edges:
            if is_conditional:
                graph.add_conditional_edges(source, condition_func, mapping)
            else:
                graph.add_edge(source, target)

        # 3. 엔트리 포인트 설정
        graph.set_entry_point(input_node_id)

        # 4. Output → END 연결
        for output_node in output_nodes:
            graph.add_edge(output_node, END)

        return graph.compile()
```

### FlowState Reducers

LangGraph의 Annotated 타입을 사용하여 상태 업데이트 방식 정의:

```python
def replace_value(current: Any, new: Any) -> Any:
    """새 값으로 교체"""
    return new if new is not None else current

def merge_dict(current: Dict, new: Dict) -> Dict:
    """딕셔너리 병합"""
    result = dict(current) if current else {}
    if new:
        result.update(new)
    return result

def append_list(current: List, new: List) -> List:
    """리스트 추가"""
    result = list(current) if current else []
    if new:
        result.extend(new)
    return result

class FlowState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], append_list]
    input_text: Annotated[str, replace_value]
    current_output: Annotated[str, replace_value]
    # ...
```

## 노드 구현

### Agent 노드 (KBSphere 지원)

```python
async def agent_node(state: FlowState) -> Dict[str, Any]:
    # 1. 에이전트 정보 조회
    model = Models.get_model_by_id(resource_id)
    model_params = model.params.model_dump()

    enable_kbsphere = model_params.get("enable_kbsphere", False)
    enable_dbsphere = model_params.get("enable_dbsphere", False)

    # 2. 에이전트 인스턴스 생성
    if enable_kbsphere:
        runner = KBSphereAgent(...)
    elif enable_dbsphere:
        runner = DBSphereAgent(...)
    else:
        return await model_node(state)  # fallback

    # 3. 실행 (KBSphere: run_flow=True)
    if enable_kbsphere:
        result = await runner.run(..., run_flow=True)
        # result = {"messages": [...], "sources": {...}}

        # 4. AIMessage에서 출력 추출
        for msg in reversed(result["messages"]):
            if msg.type == "ai":
                output_text = msg.content
                break

        return {
            "current_output": output_text,
            "node_outputs": {
                node_id: {
                    "text": output_text,
                    "sources": result["sources"],
                    "messages": result["messages"],
                }
            },
        }
```

### Condition 노드

```python
async def condition_node(state: FlowState) -> Dict[str, Any]:
    condition_type = config.get("conditionType", "contains")
    value = config.get("value", "")
    text = state.get("current_output", "")

    result = False
    if condition_type == "contains":
        result = value.lower() in text.lower()
    elif condition_type == "equals":
        result = text.strip() == value.strip()
    elif condition_type == "regex":
        result = bool(re.search(value, text))
    # ...

    return {"node_outputs": {node_id: {"result": result}}}
```

조건 노드의 분기는 `add_conditional_edges`로 처리:

```python
graph.add_conditional_edges(
    source,
    lambda state, t=target, s=source:
        t if state.get("node_outputs", {}).get(s, {}).get("result", False)
        else END,
    {target: target, END: END}
)
```

## 스트리밍 출력

### SSE 포맷

OpenAI Chat Completion 스트리밍 포맷 사용:

```python
def _format_sse_chunk(self, content: str) -> str:
    chunk_data = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "agent-flow",
        "choices": [{
            "index": 0,
            "delta": {"content": content},
            "finish_reason": None,
        }],
    }
    return f"data: {json.dumps(chunk_data)}\n\n"

def _format_sse_done(self) -> str:
    # ...
    return f"data: {json.dumps(done_data)}\n\ndata: [DONE]\n\n"
```

### Sources Emit

KBSphere sources를 프론트엔드에 전달:

```python
# aggregated_sources = {filename: {"source": {...}, "document": [...], ...}}
for source_key, source_data in aggregated_sources.items():
    await self.event_emitter({"type": "source", "data": source_data})
```

## 통합 지점

### openai.py 라우팅

```python
# /api/chat/completions 엔드포인트
async def generate_chat_completion(...):
    model_meta = model_info.get("info", {}).get("meta", {})

    if model_meta.get("type") == "agent_flow":
        return await _handle_agent_flow(
            request=request,
            flow_id=model_id,
            payload=payload,
            metadata=metadata,
            user=user,
        )
```

### models.py 리스팅

```python
# get_all_models()
if custom_model.base_model_id is None:
    is_agent_flow = meta.get("type") == "agent_flow"

    if is_agent_flow and custom_model.is_active:
        models.append({
            "id": custom_model.id,
            "name": custom_model.name,
            "owned_by": "agent_flow",
            # ...
        })
```
