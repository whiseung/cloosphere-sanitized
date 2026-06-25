> Last Updated: 2026-04-08

# Agent Flow API

**License gate**: `require_feature("agent_flow")` (전체 라우터)
**Router**: `backend/open_webui/routers/agent_flows.py` (12 endpoints)

## 엔드포인트 목록 (12개)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/agent-flows/` | 플로우 목록 조회 (모든 사용자가 읽기 가능한 flow) |
| GET | `/api/v1/agent-flows/list` | 편집 가능한 플로우 목록 (에이전트 편집기용, write 권한) |
| GET | `/api/v1/agent-flows/check/{flow_id}` | 플로우 가용성 체크 (존재 + 권한 확인) |
| POST | `/api/v1/agent-flows/create` | 플로우 생성 |
| GET | `/api/v1/agent-flows/{id}` | 플로우 상세 조회 |
| POST | `/api/v1/agent-flows/{id}/update` | 플로우 수정 |
| DELETE | `/api/v1/agent-flows/{id}/delete` | 플로우 삭제 |
| POST | `/api/v1/agent-flows/validate` | 플로우 유효성 검사 (저장 전 graph 검증) |
| GET | `/api/v1/agent-flows/{id}/export` | 플로우 내보내기 (JSON 다운로드) |
| POST | `/api/v1/agent-flows/import` | 플로우 가져오기 (JSON 업로드) |
| POST | `/api/v1/agent-flows/auto-build/chat` | **LLM이 자연어로 플로우 자동 생성 (챗 인터페이스)** |
| POST | `/api/v1/agent-flows/auto-build` | **배치 자동 생성 (여러 플로우 한꺼번에)** |

> **신규 엔드포인트 (2026-03)**: `/list`, `/check/{flow_id}`, `/auto-build/chat`, `/auto-build`, `/{id}/export`, `/import`은 2026-03 이후 추가되었습니다. `auto-build`는 `flow_builder_agent.py` (extension_modules/agent_flow/)에서 구현된 LLM 기반 자동 빌더 에이전트를 사용합니다.

## 모델 ID Prefix 변경 (2026-03)

- **구 prefix**: `flow.` (예: `flow.abc123`)
- **신 prefix**: `flow_` (예: `flow_abc123`)
- **Dual-prefix 지원**: 라우터는 두 prefix 모두 허용 (레거시 호환). 신규 생성은 `flow_` 사용.

## 플로우 목록 조회

### Request

```http
GET /api/v1/agent-flows
Authorization: Bearer {token}
```

### Response

```json
[
    {
        "id": "flow.abc123",
        "name": "문서 분석 플로우",
        "description": "문서를 요약하고 핵심 내용을 추출합니다",
        "user_id": "user-uuid",
        "is_active": true,
        "created_at": 1706745600,
        "updated_at": 1706745600,
        "meta": {
            "type": "agent_flow",
            "flow_data": {...}
        }
    }
]
```

## 플로우 생성

### Request

```http
POST /api/v1/agent-flows/create
Authorization: Bearer {token}
Content-Type: application/json

{
    "name": "새 플로우",
    "description": "플로우 설명",
    "flow_data": {
        "nodes": [
            {
                "id": "node_1",
                "type": "flowInput",
                "position": {"x": 100, "y": 100},
                "data": {"label": "Input"}
            },
            {
                "id": "node_2",
                "type": "flowOutput",
                "position": {"x": 300, "y": 100},
                "data": {"label": "Output"}
            }
        ],
        "edges": [
            {
                "id": "edge_1",
                "source": "node_1",
                "target": "node_2"
            }
        ]
    }
}
```

### Response

```json
{
    "id": "flow.new-uuid",
    "name": "새 플로우",
    "description": "플로우 설명",
    "user_id": "user-uuid",
    "is_active": true,
    "created_at": 1706745600,
    "updated_at": 1706745600,
    "meta": {
        "type": "agent_flow",
        "flow_data": {...}
    }
}
```

## 플로우 수정

### Request

```http
POST /api/v1/agent-flows/{id}/update
Authorization: Bearer {token}
Content-Type: application/json

{
    "name": "수정된 플로우",
    "description": "수정된 설명",
    "flow_data": {...},
    "is_active": true
}
```

## 플로우 삭제

### Request

```http
DELETE /api/v1/agent-flows/{id}/delete
Authorization: Bearer {token}
```

### Response

```json
{
    "success": true
}
```

## 플로우 유효성 검사

### Request

```http
POST /api/v1/agent-flows/validate
Authorization: Bearer {token}
Content-Type: application/json

{
    "flow_data": {
        "nodes": [...],
        "edges": [...]
    }
}
```

### Response

```json
{
    "valid": true,
    "errors": [],
    "warnings": [
        "노드 'node_3'에 연결된 출력이 없습니다"
    ]
}
```

## 플로우 실행 (Chat Completions)

플로우 실행은 기존 `/api/chat/completions` 엔드포인트를 통해 이루어집니다.

### Request

```http
POST /api/chat/completions
Authorization: Bearer {token}
Content-Type: application/json

{
    "model": "flow.abc123",
    "messages": [
        {"role": "user", "content": "문서를 분석해주세요"}
    ],
    "stream": true
}
```

### Response (SSE Stream)

```
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":"분석"},"index":0}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":" 결과"},"index":0}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop","index":0}]}

data: [DONE]
```

## 에러 코드

| 코드 | 설명 |
|------|------|
| 400 | 잘못된 요청 (flow_data 형식 오류) |
| 401 | 인증 실패 |
| 403 | 권한 없음 |
| 404 | 플로우를 찾을 수 없음 |
| 500 | 서버 오류 |

## 라우터 구현

### 파일 위치

`backend/open_webui/routers/agent_flows.py`

### 주요 함수

```python
@router.get("/")
async def get_agent_flows(user=Depends(get_verified_user)):
    """사용자의 플로우 목록 조회"""
    flows = Models.get_models_by_user_id(user.id, type="agent_flow")
    return [flow_to_response(f) for f in flows]

@router.post("/create")
async def create_agent_flow(
    form_data: AgentFlowForm,
    user=Depends(get_verified_user)
):
    """새 플로우 생성"""
    flow_id = f"flow.{uuid.uuid4()}"
    model = ModelModel(
        id=flow_id,
        user_id=user.id,
        name=form_data.name,
        meta=ModelMeta(
            type="agent_flow",
            description=form_data.description,
            flow_data=form_data.flow_data,
        ),
    )
    return Models.insert_new_model(user.id, model)

@router.post("/{id}/update")
async def update_agent_flow(
    id: str,
    form_data: AgentFlowUpdateForm,
    user=Depends(get_verified_user)
):
    """플로우 수정"""
    return Models.update_model_by_id(id, form_data.model_dump())
```

## 프론트엔드 API 클라이언트

### 파일 위치

`src/lib/apis/agent-flows/index.ts`

### 주요 함수

```typescript
export const getAgentFlows = async (token: string) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows`, {
        method: 'GET',
        headers: {
            Accept: 'application/json',
            authorization: `Bearer ${token}`
        }
    });
    // ...
};

export const createAgentFlow = async (
    token: string,
    name: string,
    description: string,
    flowData: FlowData
) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/create`, {
        method: 'POST',
        headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
            name,
            description,
            flow_data: flowData
        })
    });
    // ...
};
```
