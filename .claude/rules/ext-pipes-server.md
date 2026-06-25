---
paths:
  - "backend/extension_modules/pipes/**/*.py"
  - "backend/extension_modules/server/**/*.py"
  - "backend/extension_modules/tools/**/*.py"
---

# Pipes/Server/Tools 확장 프레임워크 규칙

## Pipe 기본 클래스
```python
class ReactAgentBasePipe(ABC):
    async def pipe(self, body: dict, __user__: dict, __event_emitter__, __event_call__):
        # 스트림 이벤트 패턴
        # on_chat_model_stream: 텍스트 스트리밍
        # on_tool_start: 도구 호출 시작
        # on_chat_model_end: 모델 응답 완료
```
- 비동기 callable 파이프라인
- OpenAI 호환 스트리밍 출력

## Server 기본 클래스
```python
class ServerConnector(ABC):
    async def connect(self) -> bool
    async def list_tools(self) -> list[ToolSpec]
    async def call_tool(self, name: str, arguments: dict) -> Any
    def to_langchain_tools(self) -> list[StructuredTool]
```
- OpenAPI/MCP 커넥터
- 외부 서버 도구 자동 등록

## Tool 기본 클래스
```python
class CSToolBase(ABC):
    def get_tool(self) -> List[ToolList]
```
- LangChain StructuredTool 래퍼
- `ToolSpec`: name, description, parameters (JSON Schema)

## MCP 프로토콜 지원
- Model Context Protocol 서버 연결
- 도구 목록 자동 동기화
- LangChain 어댑터 통합

## 참조 파일
- `pipes/`: Pipe 구현체
- `server/`: ServerConnector 구현체
- `tools/`: CSToolBase 구현체
