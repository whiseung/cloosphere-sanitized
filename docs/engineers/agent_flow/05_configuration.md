> Last Updated: 2026-04-08

# 05. Agent Flow 설정

## 1. License Feature Gate

| 설정 | 값 |
|---|---|
| **Feature key** | `agent_flow` (`FeatureModule.AGENT_FLOW`) |
| **Tier** | **PROFESSIONAL** 이상 |
| **Enforcement** | `require_feature("agent_flow")` — 라우터 전체 적용 |

자세한 내용: [`docs/engineers/license/`](../license/README.md)

## 2. 워크스페이스 권한

| Permission | 동작 |
|---|---|
| `workspace.agent_flows` (read) | 플로우 조회 (`GET /`, `GET /{id}`) |
| `workspace.agent_flows` (write) | 생성/수정/삭제 |
| `USER_PERMISSIONS_WORKSPACE_AGENT_FLOWS_ACCESS` | 전역 활성화 플래그 (config.py PersistentConfig) |

**환경 변수**:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `USER_PERMISSIONS_WORKSPACE_AGENT_FLOWS_ACCESS` | (default_permissions 참조) | Agent Flow 워크스페이스 접근 권한 기본값 |

## 3. Per-Flow Access Control

다른 워크스페이스 리소스와 동일하게 `access_control` JSON 필드로 관리:

```json
{
  "read": {"group_ids": ["engineering"], "user_ids": []},
  "write": {"group_ids": [], "user_ids": ["OWNER_ID"]}
}
```

## 4. LLM 자동 빌더 (`flow_builder_agent.py`)

`POST /auto-build/chat`와 `POST /auto-build`는 `backend/extension_modules/agent_flow/flow_builder_agent.py`에서 구현된 LLM 기반 자동 빌더를 호출한다.

### 동작 흐름

```
사용자 자연어 입력: "고객 문의를 분류하고 적절한 팀에 라우팅하는 플로우 만들어줘"
    │
    ▼
flow_builder_agent.generate(query)
    │
    ├─▶ System prompt에 노드 타입 카탈로그 제공 (flowInput, flowOutput, agent, model, condition, router, ...)
    ├─▶ LLM이 노드 및 엣지 리스트 생성
    ├─▶ FlowGraph 검증 (cycle, disconnected nodes, 포트 매칭)
    └─▶ flow_data JSON 반환 → /create 또는 /{id}/update로 저장
```

### 설정

자동 빌더는 Task Model 또는 Chat Model을 사용한다. 별도 환경 변수 없음 — LLM 설정은 Agent 설정과 공유.

## 5. Flow Data 구조

`flow_data` JSON은 `@xyflow/svelte`와 호환되는 포맷:

```json
{
  "nodes": [
    {
      "id": "node_1",
      "type": "flowInput",
      "position": {"x": 100, "y": 100},
      "data": {"label": "User Query"}
    },
    {
      "id": "node_2",
      "type": "agent",
      "position": {"x": 300, "y": 100},
      "data": {"agent_id": "agent-uuid", "prompt": "..."}
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "node_1",
      "target": "node_2",
      "sourceHandle": "output",
      "targetHandle": "input"
    }
  ]
}
```

### 지원 노드 타입

`src/lib/components/workspace/AgentFlows/nodes/`에 정의:

| Type | 역할 |
|---|---|
| `flowInput` | 플로우 입력 |
| `flowOutput` | 플로우 출력 |
| `agent` | Agent 호출 |
| `model` | LLM 직접 호출 |
| `condition` | 조건 분기 |
| `transform` | 데이터 변환 |
| `router` | 다중 라우팅 |
| `aggregator` | 여러 입력 합치기 |
| `humanInput` | 사용자 입력 대기 |
| `subflow` | 서브 플로우 호출 |
| `guardrail` | 가드레일 체크 |
| `errorHandler` | 에러 처리 |
| `notification` | 알림 전송 |
| `glossary` | Glossary 검색 |

## 6. 의존성

- `@xyflow/svelte` (프론트엔드 플로우 빌더)
- `extension_modules/react` (에이전트 실행 기반)
- `extension_modules/agent_flow/agent_flow_runner.py` (런타임 플로우 실행기)
- `extension_modules/agent_flow/flow_builder_agent.py` (자동 빌더)

## 7. Migration

- `f6a7b8c9d0e1_remove_agent_flow_tables.py` — **기존 `agent_flow` 별도 테이블을 제거**하고 공용 `models` 테이블에 `type: "agent_flow"` meta 필드로 저장하도록 변경. Flow는 이제 Agent Model과 동일한 테이블을 공유.

## 8. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 403 on all agent-flows endpoints | License feature `agent_flow` 비활성 | PROFESSIONAL 이상 tier의 license 등록 |
| Flow 저장 후 모델 ID에 `flow.` prefix | 클라이언트가 구 prefix 사용 | 신 prefix `flow_` 사용 권장 (dual 지원이나 점진적 마이그레이션) |
| `/auto-build/chat` 응답 시간 초과 | LLM 호출 느림 + 복잡한 graph 생성 | Task Model을 더 빠른 모델로 변경. 또는 `/auto-build` 배치 모드 사용 |
| Import JSON 검증 실패 | 노드 타입 버전 불일치 또는 포트 매칭 오류 | 먼저 `POST /validate`로 검증 후 import. 필요시 수동 수정 |
| Flow 실행 시 "node not found" | Flow에 참조된 `agent_id`가 삭제됨 | Flow 편집기에서 해당 노드 재구성 또는 노드 삭제 |
