> Last Updated: 2026-04-08

# Agent Flow (에이전트 플로우)

Agent Flow는 비주얼 워크플로우 빌더로, 여러 에이전트와 리소스를 노드 기반으로 연결하여 멀티 에이전트 오케스트레이션을 구현합니다. **LLM 기반 자동 빌더** (`flow_builder_agent.py`)로 자연어로부터 플로우를 자동 생성할 수도 있습니다.

## 문서 목록

1. [개요](./01_overview.md) - Agent Flow 시스템 소개
2. [아키텍처](./02_architecture.md) - 데이터 모델 및 실행 엔진
3. [API](./03_api.md) - REST API 엔드포인트 (12개, auto-build 포함)
4. [프론트엔드](./04_frontend.md) - UI 컴포넌트 및 XYFlow 통합
5. [설정](./05_configuration.md) - 라이선스, 권한, flow_builder_agent, migrations

## 빠른 시작

### 1. 마이그레이션 확인

Agent Flow는 기존 Models 테이블을 활용합니다 (별도 테이블 불필요).

```bash
cd backend
alembic upgrade head
```

### 2. 플로우 생성

워크스페이스 > 플로우 > 새로 만들기

### 3. 채팅에서 실행

모델 선택기에서 생성한 플로우 선택 후 메시지 전송

## 주요 기능

- **비주얼 빌더**: XYFlow 기반 드래그 앤 드롭 캔버스
- **노드 타입**: Input, Output, Agent, Model, Knowledge, Condition, Transform 등
- **KBSphere 연동**: run_flow 모드로 sources와 messages 캡처
- **실시간 스트리밍**: SSE 기반 응답 스트리밍
- **최종 답변 생성**: get_final_answer_system_prompt 활용

## 파일 구조

```
backend/
├── extension_modules/agent_flow/
│   ├── __init__.py
│   └── agent_flow_runner.py    # Flow 실행 엔진 (LangGraph)
├── open_webui/
│   ├── routers/
│   │   ├── agent_flows.py      # Flow CRUD API
│   │   └── openai.py           # Flow 실행 라우팅 (agent_flow 타입)
│   └── utils/models.py         # Flow 모델 리스팅

src/lib/
├── apis/agent-flows/           # API 클라이언트
├── components/workspace/
│   ├── AgentFlows/             # 비주얼 빌더 컴포넌트
│   │   ├── FlowBuilder.svelte
│   │   ├── FlowToolbar.svelte
│   │   ├── NodePalette.svelte
│   │   ├── NodeConfigPanel.svelte
│   │   └── nodes/              # 노드 컴포넌트들
│   └── Flows/                  # 플로우 목록/편집
└── routes/(app)/workspace/flows/   # 페이지 라우팅
```

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 프론트엔드 캔버스 | @xyflow/svelte |
| 백엔드 실행 | LangGraph StateGraph |
| 데이터 저장 | Models 테이블 (meta.type = "agent_flow") |
| 스트리밍 | SSE (Server-Sent Events) |

## 핵심 흐름

```
[프론트엔드]
    │
    ▼ POST /api/chat/completions (model=flow.xxx)
    │
[openai.py]
    │ meta.type == "agent_flow" 확인
    ▼
[AgentFlowRunner]
    │ LangGraph 빌드 및 실행
    │ - Input → Agent/Model → Output
    │ - KBSphere: run_flow=True로 호출
    ▼
[_stream_execution]
    │ - sources emit
    │ - _generate_final_answer (KBSphere인 경우)
    ▼
[SSE 스트리밍 응답]
```

## 관련 문서

- [KBSphere](../search_engine/README.md) - 향상된 RAG 에이전트
- [DBSphere](../dbsphere_v2/README.md) - 데이터베이스 에이전트
