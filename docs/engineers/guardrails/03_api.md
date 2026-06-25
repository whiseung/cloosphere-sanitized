> Last Updated: 2026-04-08

# Guardrails API

Guardrails는 **두 개의 라우터**로 분리되어 있다:
1. **`/api/v1/guardrails/*`** — 가드레일 CRUD (정의 관리). `require_feature("guardrail")` 게이트 적용.
2. **`/api/v1/guardrail-logs/*`** — 가드레일 감지 로그 조회 (admin 모니터링). `get_admin_monitoring_read_access` 의존성.

## 1. Guardrails CRUD API (`/api/v1/guardrails`)

### 라우터 등록

```python
# backend/open_webui/main.py
from open_webui.routers import guardrails
app.include_router(guardrails.router, prefix="/api/v1/guardrails", tags=["guardrails"])
```

### 엔드포인트 목록

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | 전체 가드레일 목록 조회 |
| GET | `/list` | 편집 가능한 가드레일 목록 |
| POST | `/create` | 새 가드레일 생성 |
| GET | `/{id}` | 특정 가드레일 조회 |
| POST | `/{id}/update` | 가드레일 수정 |
| DELETE | `/{id}/delete` | 가드레일 삭제 |
| POST | `/test` | 가드레일 테스트 |

## 1-B. Guardrail Logs API (`/api/v1/guardrail-logs`)

**라우터**: `backend/open_webui/routers/guardrail_logs.py` (신규, 2026-03 추가)
**Auth**: `get_admin_monitoring_read_access` (admin monitoring 읽기 권한)

### 엔드포인트 목록 (4개)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | 가드레일 로그 목록 조회 (페이지네이션 + 다중 필터) |
| GET | `/actions` | 실제 데이터에 존재하는 action 목록 (cascading filter용) |
| GET | `/detection-sources` | 실제 데이터에 존재하는 detection_source 목록 |
| GET | `/{guardrail_log_id}` | 특정 로그 상세 조회 |

### `GET /` 쿼리 파라미터

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `page` | int (기본 1) | 페이지 번호 |
| `limit` | int (1-100, 기본 50) | 페이지당 항목 |
| `action` | str? | 액션 필터, 콤마 구분 (`block,redact,mask`) |
| `detection_source` | str? | 감지 소스 필터, 콤마 구분 (`pii,blocked_words,llm_judge`) |
| `user_search` | str? | 사용자 검색 (ID, 이메일, 이름) |
| `chat_id` | str? | 특정 채팅의 로그만 |
| `source` | str? | `meta.source` 필터 (예: `code_gateway`) |
| `from_date` | int? | 시작 날짜 (Unix timestamp) |
| `to_date` | int? | 종료 날짜 (Unix timestamp) |

### `GuardrailLogListResponse`

```python
class GuardrailLogListResponse(BaseModel):
    items: list[GuardrailLogModel]
    total: int
    page: int
    limit: int
    total_pages: int
```

### `GuardrailLogModel` 주요 필드

`backend/open_webui/models/guardrail_log.py`:

| 필드 | 설명 |
|---|---|
| `id` | UUID |
| `user_id` / `user_name` / `user_email` | 위반 사용자 정보 (user_name/email은 lookup cache) |
| `chat_id` / `message_id` | 관련 채팅/메시지 |
| `guardrail_id` | 적용된 가드레일 ID |
| `action` | `block` / `redact` / `mask` / `hash` |
| `detection_source` | `pii` / `blocked_words` / `custom_pattern` / `llm_judge` |
| `detected_content` | 감지된 원본 콘텐츠 (masked) |
| `meta` | 추가 메타 (source=code_gateway 등) |
| `created_at` | epoch timestamp |

### Migration

- `d4e5f6a7b8c9_add_guardrail_table.py` — `guardrail` 테이블 (정의)
- `g8a9b0c1d2e3_add_guardrail_log_table.py` — `guardrail_log` 테이블 (감지 로그)

### User info auto-resolve

`GET /` 응답에서 `user_name` / `user_email`이 비어있는 경우, 라우터가 `Users.get_user_by_id(user_id)`로 조회하여 자동 보강. 최초 로그 생성 시 snapshot이 없거나 사용자 정보가 변경된 경우에도 최신 정보를 반환.

## 2. 요청/응답 스키마

### GuardrailForm (생성/수정 요청)

```python
class GuardrailForm(BaseModel):
    name: str
    description: Optional[str] = None

    # 규칙 기반 설정
    pii_types: List[str] = []           # ["email", "credit_card", "ip", ...]
    pii_strategy: str = "redact"        # block, redact, mask, hash
    custom_patterns: List[dict] = []    # [{"name": "api_key", "pattern": "sk-..."}]
    blocked_words: List[str] = []       # ["password", "secret", ...]

    # 적용 범위
    apply_to_input: bool = True
    apply_to_output: bool = False

    # LLM Judge 설정
    llm_judge_enabled: bool = False
    llm_judge_model: Optional[str] = None
    llm_judge_prompt: Optional[str] = None
    llm_judge_pass_examples: List[str] = []
    llm_judge_block_examples: List[str] = []
    llm_judge_apply_to_input: bool = True
    llm_judge_apply_to_output: bool = False

    # 접근 제어
    access_control: Optional[dict] = None
```

### GuardrailTestForm (테스트 요청)

```python
class GuardrailTestForm(BaseModel):
    guardrail_id: Optional[str] = None    # 기존 가드레일 ID로 테스트
    config: Optional[GuardrailForm] = None # 또는 설정값으로 직접 테스트
    text: str                              # 테스트할 텍스트
```

### GuardrailTestResponse (테스트 응답)

```python
class GuardrailTestResponse(BaseModel):
    processed_text: str       # 처리된 텍스트
    violations: List[dict]    # 탐지된 위반 목록
    blocked: bool             # 차단 여부
    message: Optional[str]    # 차단 사유 (차단된 경우)
```

## 3. API 사용 예시

### 가드레일 생성

```bash
POST /api/v1/guardrails/create

{
  "name": "개인정보 보호",
  "description": "이메일, 전화번호 등 개인정보 보호",
  "pii_types": ["email", "credit_card"],
  "pii_strategy": "redact",
  "blocked_words": ["password", "비밀번호"],
  "apply_to_input": true,
  "apply_to_output": false
}
```

### 가드레일 테스트

```bash
POST /api/v1/guardrails/test

{
  "guardrail_id": "abc123",
  "text": "내 이메일은 user@example.com이고 카드번호는 4532-1234-5678-9012입니다."
}

# 응답
{
  "processed_text": "내 이메일은 [REDACTED_EMAIL]이고 카드번호는 [REDACTED_CREDIT_CARD]입니다.",
  "violations": [
    {"type": "pii", "pii_type": "email", "matched": "user@example.com"},
    {"type": "pii", "pii_type": "credit_card", "matched": "4532-1234-5678-9012"}
  ],
  "blocked": false,
  "message": null
}
```

### LLM Judge 설정 예시

```bash
POST /api/v1/guardrails/create

{
  "name": "콘텐츠 심사",
  "llm_judge_enabled": true,
  "llm_judge_model": "gpt-4",
  "llm_judge_prompt": "다음 콘텐츠가 업무에 적합한지 판단하세요.",
  "llm_judge_pass_examples": [
    "프로젝트 일정에 대해 논의하겠습니다.",
    "분기 보고서를 검토해 주세요."
  ],
  "llm_judge_block_examples": [
    "이 주식 지금 당장 사세요!",
    "경쟁사 비밀 정보를 알려드립니다."
  ]
}
```

## 4. 프론트엔드 API 클라이언트

```typescript
// src/lib/apis/guardrails/index.ts

export const getGuardrails = async (token: string): Promise<Guardrail[]> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/`, {
    headers: { authorization: `Bearer ${token}` }
  });
  return res.json();
};

export const createGuardrail = async (
  token: string,
  form: GuardrailForm
): Promise<Guardrail> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/create`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      authorization: `Bearer ${token}`
    },
    body: JSON.stringify(form)
  });
  return res.json();
};

export const testGuardrail = async (
  token: string,
  form: GuardrailTestForm
): Promise<GuardrailTestResponse> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/test`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      authorization: `Bearer ${token}`
    },
    body: JSON.stringify(form)
  });
  return res.json();
};
```

## 5. 접근 제어

```python
# access_control 필드 값에 따른 접근 권한

# None: 공개 (모든 user 역할 이상 접근 가능)
access_control = None

# {}: 비공개 (소유자만 접근 가능)
access_control = {}

# 커스텀: 특정 그룹/사용자에게 권한 부여
access_control = {
    "read": {
        "group_ids": ["group1", "group2"],
        "user_ids": ["user1"]
    },
    "write": {
        "group_ids": ["admin-group"],
        "user_ids": []
    }
}
```
