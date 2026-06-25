---
name: langchain
description: LangChain 기반 에이전트, 도구, 미들웨어, LLM 생성 가이드.
---

# LangChain 에이전트 개발 가이드

Cloosphere는 LangChain 1.2.0을 사용합니다. v1.0에서 에이전트 생성이 LangGraph에서 LangChain으로 이동했습니다.

## v0.3 → v1.0 핵심 변경사항

| 항목 | 이전 (v0.3) | 현재 (v1.0+) |
|------|------------|-------------|
| 에이전트 생성 | `langgraph.prebuilt.create_react_agent` | **`langchain.agents.create_agent`** |
| 도구 런타임 | `InjectedState`, `InjectedStore` | **`ToolRuntime`** (통합) |
| 상태 스키마 | Pydantic/TypedDict | **TypedDict 전용** |
| 구조화 출력 | `with_structured_output` | **`response_format`** (ToolStrategy/ProviderStrategy) |
| 콜백 | Callback 기반 | **미들웨어 시스템** |
| Pydantic | v1/v2 혼용 | **v2 전용** |
| 레거시 기능 | `langchain` 내 포함 | **`langchain-classic`으로 분리** |

## 1. 에이전트 생성 (`create_agent`)

```python
from langchain.agents import create_agent, AgentState

agent = create_agent(
    llm,                              # BaseChatModel 인스턴스
    tools,                            # List[StructuredTool]
    system_prompt=system_prompt,      # str (⚠️ prompt → system_prompt 변경됨)
    state_schema=CustomAgentState,    # TypedDict 기반만 허용
    middleware=[...],                 # AgentMiddleware 리스트
    response_format=OutputModel,      # Pydantic model (구조화 출력)
)
```

**참조**: `extension_modules/agent/unified_agent.py:854-867`

## 2. State Schema 정의

**반드시 TypedDict 기반** (AgentState 상속):

```python
from langchain.agents import AgentState

class CustomAgentState(AgentState):
    # AgentState에서 상속: messages
    normalized_question: str = ""
    language: str = ""
```

**참조**: `extension_modules/react/react_base.py:46-52`

## 3. StructuredTool 생성

```python
from langchain_core.tools import StructuredTool
from langchain.tools import ToolRuntime
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    query: str = Field(..., description="검색 질의")

async def my_tool(
    query: str,
    runtime: ToolRuntime[None, CustomAgentState],
) -> str:
    return await do_something(query)

tool = StructuredTool.from_function(
    coroutine=my_tool,
    name="my_tool",
    description="도구 설명",
    args_schema=MyToolInput,
)
```

**참조**: `extension_modules/dbsphere/tools/run_sql.py:61-138`, `extension_modules/agent/tool_connection_tools.py`

## 4. ToolRuntime

`InjectedState`, `InjectedStore`를 통합한 도구 런타임 인터페이스:

```python
from langchain.tools import ToolRuntime

runtime: ToolRuntime[ContextType, StateType]
runtime.state           # 현재 대화 상태 (messages, custom fields)
runtime.context         # 불변 설정 (user_id, session)
runtime.store           # 장기 영속 메모리
runtime.stream_writer   # 실시간 업데이트 전송
runtime.config          # RunnableConfig (콜백, 태그)
runtime.tool_call_id    # 현재 도구 호출 ID
```

**예약어**: `config`, `runtime`은 도구 함수 파라미터로 사용 시 자동 주입됨

## 5. 미들웨어 시스템

콜백을 대체하는 v1.0 미들웨어 아키텍처:

```python
from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest

class CustomMiddleware(AgentMiddleware):
    async def abefore_agent(self, state, config):
        """에이전트 시작 전"""

    async def aafter_agent(self, state, config):
        """에이전트 완료 후"""

    async def abefore_model(self, messages, config):
        """LLM 호출 전 (메시지 수정 가능)"""
        return messages

    async def aafter_model(self, response, config):
        """LLM 호출 후"""
        return response

    async def awrap_tool_call(self, request: ToolCallRequest, config):
        """도구 실행 래핑"""
        result = await request()
        return result
```

**내장 미들웨어**:
- `ToolCallLimitMiddleware(run_limit=10)`: 도구 호출 횟수 제한

**참조**: `extension_modules/react/react_middleware_base.py:21-150`

## 6. 구조화 출력 (`response_format`)

```python
from pydantic import BaseModel, Field

class AgentOutput(BaseModel):
    answerable: bool = Field(default=True, description="충분한 정보 수집 여부")
    language: str = Field(default="Korean", description="응답 언어")

agent = create_agent(llm, tools, response_format=AgentOutput)
```

**전략**:
- `ToolStrategy(Model)`: 모든 모델 지원, 도구 호출 방식
- `ProviderStrategy(Model)`: OpenAI/Anthropic 네이티브 지원
- `Model` 직접 전달: 자동 선택 (Gemini → ToolStrategy 전환)

**결과 접근**: `result["structured_response"]`

**참조**: `extension_modules/agent/unified_state.py:69-88`

## 7. LLM 생성 (멀티 프로바이더)

```python
from extension_modules.utils.llm import create_llm

llm = create_llm({
    "model_id": "gpt-5.2",
    "api_key": key,
    "base_url": url,
    "api_config": api_config,
}, streaming=True)
```

**지원 프로바이더**: Azure OpenAI, OpenAI, Vertex Gemini, Vertex AI, Ollama

**참조**: `extension_modules/utils/llm.py:36-217`

## 8. 메시지 타입

```python
from langchain_core.messages import (
    AIMessage,      # LLM 응답
    HumanMessage,   # 사용자 입력
    SystemMessage,  # 시스템 프롬프트
    ToolMessage,    # 도구 실행 결과
    BaseMessage,    # 기본 타입
)
```

## 프로젝트 에이전트 계층 구조

```
ReactToolsBase (react/react_base.py)
  ├── 메시지 변환, LLM 생성, 소스 집계
  ├── KbSphere 도구 (knowledge_handler)
  └── 공통 도구 (rewrite_question, web_search)
      │
      ├── UnifiedAgent (agent/unified_agent.py)
      │   ├── 모든 도구 통합 (KB+DB+Glossary+Image+ToolConnections)
      │   ├── 2단계 실행: react_agent → final_answer
      │   └── agent_config 기반 도구 자동 감지
      │
      ├── KbSphereAgent (kbsphere/kbsphere_agent.py)
      └── DbSphereAgent (dbsphere/dbsphere_agent.py)
```

## 주요 참조 파일

| 파일 | 내용 |
|------|------|
| `extension_modules/agent/unified_agent.py` | UnifiedAgent (통합 에이전트) |
| `extension_modules/react/react_base.py` | ReactToolsBase (공통 베이스) |
| `extension_modules/react/react_middleware_base.py` | MiddlewareBase (트레이싱) |
| `extension_modules/utils/llm.py` | LLM 생성 팩토리 |
| `extension_modules/dbsphere/tools/run_sql.py` | SQL 도구 (ToolRuntime 패턴) |
| `extension_modules/glossary/tools.py` | 용어집 도구 |
| `extension_modules/agent/tool_connection_tools.py` | MCP/OpenAPI 메타 도구 |

## 주의사항

- `state_schema`는 **TypedDict만** 허용 (Pydantic model 사용 불가)
- 도구 이름은 **snake_case** 권장 (프로바이더 호환성)
- `config`, `runtime`은 **예약된 파라미터명**
- `langchain-classic==1.0.0`에 레거시 기능 분리됨
- `langgraph.prebuilt.create_react_agent`는 하위 호환이지만 비권장
