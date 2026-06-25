---
paths:
  - "backend/open_webui/routers/chats.py"
  - "backend/open_webui/routers/openai.py"
  - "backend/open_webui/routers/ollama.py"
  - "backend/open_webui/models/chats.py"
  - "backend/open_webui/models/messages.py"
---

# 채팅/완료 시스템 규칙

## 채팅 CRUD (routers/chats.py)
- `/`: GET 목록 (60건/페이지 페이지네이션), DELETE 전체 삭제
- `/new`: POST 새 채팅 생성
- `/search`: GET 텍스트 검색 (페이지네이션)
- `/pinned`, `/all/archived`: 고정/보관 채팅
- `/{id}`: GET 단일 조회, POST 수정, DELETE 삭제
- `/share/{share_id}`: GET 공유 채팅 (비인증 접근 가능)
- 권한: `chat.delete` permission, 소유자 체크

## Chat 모델 스키마
```python
class Chat(Base):
    __tablename__ = "chat"
    id, user_id, title, chat(JSON), created_at, updated_at
    share_id(unique, nullable), archived(bool), pinned(bool)
    meta(JSON, default={}), folder_id(nullable)
```
- `chat` JSON: `{"title": "...", "history": {"messages": {"msg_id": {...}, ...}}}`

## Message 모델 스키마
```python
class Message(Base):
    __tablename__ = "message"
    id, user_id, channel_id(nullable), parent_id(nullable)
    content(Text), data(JSON), meta(JSON)
    created_at, updated_at  # time_ns (나노초)
```
- 스레드: `parent_id`로 연결
- 리액션: `MessageResponse` + reactions, reply_count

## OpenAI 프록시 (routers/openai.py)
- `POST /chat/completions`: 메인 완료 엔드포인트
- 에이전트 라우팅: `model_info.base_model_id`가 있으면 → UnifiedAgent (리소스 기반 자동 감지, legacy enable_* 플래그 폐기)
- 프로바이더: standard OpenAI, Azure OpenAI (`api-key` 헤더), Vertex AI (Gemini 변환)
- `stream_options: {"include_usage": true}` 자동 주입 (스트리밍 시)

## SSE 스트리밍 패턴
```python
# stream_with_usage_tracking(): 스트림 래핑 + usage 추출
StreamingResponse(
    stream_with_usage_tracking(response, session, user_id, chat_id, message_id, model_id, agent_id, task_type),
    status_code=r.status, headers=dict(r.headers),
)
```

## Usage 기록
- 스트리밍: 마지막 청크 `usage` 필드 → `Usages.insert_new_usage()`
- 비스트리밍: 응답 JSON `usage` 필드
- task_type 시: `effective_message_id = f"task:{task_type}"`

## 참조 파일
- `routers/chats.py` (531줄): 채팅 CRUD
- `routers/openai.py` (1818줄): 완료 프록시, 스트리밍, 에이전트 라우팅
- `models/chats.py`: Chat/ChatModel/ChatForm/ChatResponse
- `models/messages.py` (274줄): Message/MessageModel/MessageResponse
- `utils/payload.py`: apply_model_params_to_body_openai()
