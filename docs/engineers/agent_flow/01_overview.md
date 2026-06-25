# Agent Flow 개요

## 소개

Agent Flow는 n8n, Dify와 유사한 비주얼 워크플로우 빌더입니다. 워크스페이스의 리소스(에이전트, 지식베이스, 가드레일, 도구 등)를 시각적으로 연결하여 멀티 에이전트 오케스트레이션을 구현합니다.

## 설계 원칙

### 1. 기존 인프라 활용

- **Models 테이블 재사용**: 별도 테이블 대신 `meta.type = "agent_flow"` 활용
- **openai.py 라우팅**: 기존 chat/completions 엔드포인트에서 Flow 실행
- **KBSphere/DBSphere 연동**: 기존 에이전트를 노드로 활용

### 2. 실시간 피드백

- SSE 스트리밍으로 실행 상태 전달
- sources emit으로 출처 정보 전달
- 노드별 실행 상태 로깅

### 3. 확장 가능한 노드 시스템

```python
node_type_map = {
    "input": input_node,
    "flowInput": input_node,
    "output": output_node,
    "flowOutput": output_node,
    "agent": agent_node,
    "model": model_node,
    "knowledge": knowledge_node,
    "guardrail": guardrail_node,
    "condition": condition_node,
    "transform": transform_node,
}
```

## 노드 타입

### 기본 노드

| 노드 | 역할 | 입력 | 출력 |
|------|------|------|------|
| Input / flowInput | 플로우 시작점 | - | input_text |
| Output / flowOutput | 플로우 종료점 | current_output | - |

### 처리 노드

| 노드 | 역할 | 설정 |
|------|------|------|
| Agent | KBSphere/DBSphere 에이전트 실행 | resourceId, temperature |
| Model | 직접 LLM 호출 | resourceId, systemPrompt, temperature, maxTokens |
| Knowledge | 지식베이스 검색 | resourceId, rerankerThreshold |
| Tool | 외부 도구 실행 | resourceId |

### 제어 노드

| 노드 | 역할 | 설정 |
|------|------|------|
| Condition | 조건 분기 | conditionType, value |
| Transform | Jinja2 변환 | template |
| Guardrail | 가드레일 적용 | resourceId |

## 데이터 흐름

### FlowState (LangGraph 상태)

```python
class FlowState(TypedDict, total=False):
    messages: Annotated[List[BaseMessage], append_list]
    input_text: Annotated[str, replace_value]
    current_output: Annotated[str, replace_value]
    context: Annotated[List[Dict], append_list]
    documents: Annotated[List[Dict], append_list]
    variables: Annotated[Dict, merge_dict]
    node_outputs: Annotated[Dict, merge_dict]
    error: Annotated[Optional[str], replace_value]
```

### 노드 간 데이터 전달

1. **input_text**: 사용자 입력 (Input 노드에서 설정)
2. **current_output**: 현재 처리 결과 (각 노드에서 업데이트)
3. **documents**: 검색된 문서 (Knowledge 노드에서 추가)
4. **node_outputs**: 각 노드별 상세 출력 (디버깅용)

## KBSphere 연동

### run_flow 모드

KBSphere 에이전트를 Flow에서 호출할 때 `run_flow=True`로 실행:

```python
result = await runner.run(
    request=self.request,
    payload=payload,
    metadata=metadata,
    user=user,
    run_flow=True,  # 스트리밍 대신 dict 반환
)

# 반환값
# {
#     "messages": [HumanMessage, ToolMessage, AIMessage, ...],
#     "sources": {filename: {"source": {...}, "document": [...], ...}}
# }
```

### 최종 답변 생성

Flow Runner가 KBSphere sources를 받아 최종 답변 생성:

```python
async def _generate_final_answer(self, initial_state, final_state, aggregated_sources):
    # 1. Source context 빌드
    source_ctx = "\\n".join([f"[{idx}] {name}\\n- {doc}" for ...])

    # 2. get_final_answer_system_prompt 호출
    messages = get_final_answer_system_prompt(
        user_question=user_question,
        sources_context=source_ctx,
        ...
    )

    # 3. LLM 스트리밍
    async for chunk in llm.astream(messages):
        yield self._format_sse_chunk(chunk.content)
```

## 실행 파이프라인

```
1. POST /api/chat/completions
   └─ model = "flow.{uuid}"

2. openai.py: _handle_agent_flow()
   └─ Models.get_model_by_id(model_id)
   └─ flow_data = model.meta.flow_data

3. AgentFlowRunner.run()
   └─ _build_graph(): LangGraph StateGraph 구성
   └─ _stream_execution(): 그래프 실행 및 스트리밍

4. 노드 실행
   └─ input_node → agent_node/model_node → output_node
   └─ agent_node: KBSphere run_flow=True
   └─ sources emit → 프론트엔드

5. 최종 응답
   └─ _generate_final_answer() (KBSphere인 경우)
   └─ SSE 스트리밍
```
