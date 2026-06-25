---
paths:
  - "backend/open_webui/routers/agent_flows.py"
  - "backend/extension_modules/agent_flow/**/*.py"
  - "src/lib/components/workspace/AgentFlows/**/*.svelte"
  - "src/lib/components/workspace/Flows/**/*.svelte"
  - "src/lib/apis/agent-flows/**/*.ts"
  - "src/routes/(app)/workspace/flows/**/*"
---

# 에이전트 플로우 빌더 규칙

## 라우터 (routers/agent_flows.py)
- CRUD 표준 패턴
- `/{id}/execute`: POST 플로우 실행 (스트리밍)
- `/{id}/test`: POST 플로우 테스트

## 플로우 구조
- 비주얼 플로우 빌더 (노드 + 엣지 DAG)
- 19종 노드 타입: input, output, llm, condition, transform, api, tool, knowledge,
  dbsphere, glossary, switch, loop, parallel, merge, delay, code, template, variable, human

## 실행 엔진 (extension_modules/agent_flow/)
- 노드 그래프를 LangGraph 상태 머신으로 변환
- 각 노드 타입별 실행기 구현
- 스트리밍 출력: SSE 형식

## 프론트엔드
- `FlowBuilder.svelte`: 메인 빌더 캔버스
- `NodeConfigPanel.svelte`: 노드 설정 패널
- `FlowToolbar.svelte`: 도구 모음
- 경로: `/workspace/flows`

## 참조 파일
- `routers/agent_flows.py`: CRUD + 실행
- `extension_modules/agent_flow/`: 실행 엔진
- `src/lib/components/workspace/Flows/`: 빌더 UI
