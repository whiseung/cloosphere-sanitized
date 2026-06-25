---
paths:
  - "backend/open_webui/routers/channels.py"
  - "backend/open_webui/models/channels.py"
  - "src/lib/components/channel/**/*.svelte"
  - "src/routes/(app)/channels/**/*"
---

# 채널 메시징 규칙

## 라우터 (routers/channels.py)
- `/`: GET 채널 목록, POST 채널 생성 (admin)
- `/{id}`: GET 단일, POST 수정, DELETE 삭제
- `/{id}/messages`: GET 메시지 목록, POST 메시지 작성
- `/{id}/messages/{message_id}`: POST 수정, DELETE 삭제
- `/{id}/messages/{message_id}/reactions`: POST 리액션 추가/제거
- 스레드: `parent_id`로 연결

## Channel 모델 스키마
```python
class Channel(Base):
    __tablename__ = "channel"
    id, user_id, name, description
    data(JSON), meta(JSON), access_control(JSON)
    created_at, updated_at
```

## Socket.IO 이벤트
- 메시지 CRUD 시 Socket.IO로 실시간 브로드캐스트
- 이벤트: `channel:message`, `channel:message:update`, `channel:message:delete`

## 프론트엔드
- `Channel.svelte`: 채널 메인 뷰
- `MessageInput.svelte`: 메시지 입력
- `Messages.svelte`: 메시지 목록
- `Thread.svelte`: 스레드 뷰
- `ReactionPicker.svelte`: 이모지 리액션

## 참조 파일
- `routers/channels.py`: 채널/메시지 CRUD
- `models/channels.py`: Channel 모델
- `models/messages.py`: Message 모델 (공유)
