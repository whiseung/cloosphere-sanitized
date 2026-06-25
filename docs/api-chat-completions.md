# Chat Completions API Guide

Cloosphere의 채팅 API는 OpenAI 호환 형식을 기반으로 하되, 대화 관리를 위한 추가 메타데이터를 지원합니다.

## Endpoint

```
POST /api/chat/completions
```

## Authentication

```
Authorization: Bearer <API_KEY>
```

API Key는 프로필 > Settings > Account > API Keys에서 생성합니다.

---

## 기본 요청 (최소 필드)

가장 간단한 형태입니다. 대화 기록이 저장되지 않습니다.

```json
{
  "model": "gpt-5.1-chat",
  "messages": [
    {"role": "user", "content": "안녕하세요"}
  ]
}
```

---

## 전체 요청 구조

```json
{
  // ── 필수 ──
  "model": "string",                    // 모델 ID
  "messages": [],                        // 메시지 배열 (아래 참조)

  // ── 대화 관리 (권장) ──
  "chat_id": "uuid",                     // 대화 ID (같은 대화면 동일 ID 유지)
  "id": "uuid",                          // 응답 메시지 ID (요청마다 새로 생성)
  "session_id": "uuid",                  // 세션 ID (접속마다 새로 생성)

  // ── 스트리밍 ──
  "stream": false,                       // true: SSE 스트리밍, false: 전체 응답
  "stream_options": {                    // stream: true일 때만
    "include_usage": true                // 토큰 사용량 포함
  },

  // ── 모델 파라미터 ──
  "params": {
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2000,
    "stop": ["<|end|>"],
    "seed": 42
  },

  // ── 기능 플래그 ──
  "features": {
    "image_generation": false,
    "web_search": false
  },

  // ── 도구 ──
  "tool_ids": ["tool_id_1"],            // 사용할 도구 ID 배열

  // ── 파일 첨부 ──
  "files": [
    {
      "type": "doc",
      "name": "report.pdf",
      "url": "/api/v1/files/xxx/content"
    }
  ],

  // ── 변수 ──
  "variables": {
    "user_name": "홍길동"
  },

  // ── 백그라운드 작업 (첫 메시지에만) ──
  "background_tasks": {
    "title_generation": true,            // 대화 제목 자동 생성
    "tags_generation": true              // 태그 자동 생성
  }
}
```

---

## messages 배열 구조

### 텍스트 메시지

```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "안녕하세요"},
  {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"},
  {"role": "user", "content": "오늘 할 일을 정리해줘"}
]
```

### 이미지 포함 (Vision 모델)

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "이 이미지에 대해 설명해줘"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}
  ]
}
```

---

## 대화 관리 필드 상세

### chat_id

- 하나의 대화(채팅방)를 식별하는 UUID
- 같은 대화의 모든 요청에 **동일한 chat_id** 사용
- 새 대화 시작 시 새 UUID 생성
- **없으면**: 대화 기록이 저장되지 않음 (모니터링 대화로그에도 안 남음)

### id (message_id)

- 이번 요청의 **응답 메시지**를 식별하는 UUID
- 요청마다 **새로 생성**
- 백엔드에서 `metadata.message_id`로 사용됨

### session_id

- 현재 접속 세션을 식별하는 UUID
- 같은 세션(앱 접속) 동안 **동일한 session_id** 유지
- Socket.IO 실시간 통신에 사용

---

## 순차 대화 예시 (Python)

```python
import uuid
import requests

API_URL = "https://cloosphere.azurewebsites.net/api/chat/completions"
API_KEY = "sk-xxx"
MODEL = "gpt-5.1-chat"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# 대화 시작
chat_id = str(uuid.uuid4())
session_id = str(uuid.uuid4())
messages = []

questions = [
    "최근 분기 매출 현황을 알려줘",
    "가장 매출이 높은 제품은?",
    "해당 제품의 월별 추이를 보여줘",
]

for i, question in enumerate(questions):
    message_id = str(uuid.uuid4())
    messages.append({"role": "user", "content": question})

    body = {
        "model": MODEL,
        "messages": messages.copy(),
        "stream": False,
        "chat_id": chat_id,
        "id": message_id,
        "session_id": session_id,
        "features": {"image_generation": False, "web_search": False},
        "variables": {"user_name": "API User"},
        "params": {},
    }

    # 첫 메시지에만 제목/태그 자동 생성
    if i == 0:
        body["background_tasks"] = {
            "title_generation": True,
            "tags_generation": True,
        }

    resp = requests.post(API_URL, headers=headers, json=body, timeout=120)
    data = resp.json()

    assistant_content = data["choices"][0]["message"]["content"]
    messages.append({"role": "assistant", "content": assistant_content})

    print(f"Q{i+1}: {question}")
    print(f"A{i+1}: {assistant_content[:100]}...")
    print()
```

---

## 스트리밍 응답 (SSE)

`stream: true`로 요청하면 Server-Sent Events로 응답합니다.

```python
import requests
import json

resp = requests.post(API_URL, headers=headers, json={
    "model": MODEL,
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": True,
    "stream_options": {"include_usage": True},
    "chat_id": str(uuid.uuid4()),
    "id": str(uuid.uuid4()),
    "session_id": str(uuid.uuid4()),
}, stream=True)

for line in resp.iter_lines():
    if line:
        line = line.decode("utf-8")
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            content = chunk["choices"][0]["delta"].get("content", "")
            print(content, end="", flush=True)
```

---

## 응답 형식

### Non-streaming (stream: false)

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1774000000,
  "model": "gpt-5.1-chat",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "안녕하세요! 무엇을 도와드릴까요?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 15,
    "total_tokens": 25
  }
}
```

### Streaming (stream: true)

```
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"안녕"},"index":0}],"model":"gpt-5.1-chat"}

data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"하세요"},"index":0}],"model":"gpt-5.1-chat"}

data: {"id":"chatcmpl-xxx","choices":[{"delta":{},"finish_reason":"stop","index":0}],"model":"gpt-5.1-chat"}

data: [DONE]
```

---

## 에이전트 모델 사용

에이전트 모델(Knowledge Base, DbSphere 등이 연결된 모델)도 동일한 API로 호출합니다.
모델 ID만 에이전트 ID로 변경하면 됩니다.

```json
{
  "model": "my-agent-id",
  "messages": [{"role": "user", "content": "매출 데이터를 분석해줘"}]
}
```

---

## 에러 응답

```json
{
  "detail": "Model not found"
}
```

| Status Code | 원인 |
|-------------|------|
| 400 | 잘못된 요청 (모델 없음, 페이로드 오류) |
| 401 | 인증 실패 (API Key 오류) |
| 403 | 모델 접근 권한 없음 |
| 500 | 서버 내부 오류 |

---

## 필드 요약

| 필드 | 필수 | 대화 기록 저장에 필요 | 설명 |
|------|:----:|:----:|------|
| `model` | O | - | 모델 ID |
| `messages` | O | - | 대화 메시지 배열 |
| `chat_id` | - | O | 대화 ID (UUID) |
| `id` | - | O | 응답 메시지 ID (UUID) |
| `session_id` | - | - | 세션 ID |
| `stream` | - | - | 스트리밍 여부 |
| `params` | - | - | 모델 파라미터 |
| `features` | - | - | 기능 플래그 |
| `variables` | - | - | 프롬프트 변수 |
| `background_tasks` | - | - | 제목/태그 자동 생성 |
| `tool_ids` | - | - | 사용할 도구 |
| `files` | - | - | 첨부 파일 |
