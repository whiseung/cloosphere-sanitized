---
paths:
  - "backend/open_webui/utils/middleware.py"
  - "backend/open_webui/utils/chat.py"
---

# 미들웨어 수정 규칙

## 주의: 93KB 대형 파일
- `middleware.py`는 93KB — 수정 전 전체 구조 이해 필수
- 요청/응답 변환, RAG 주입, 스트리밍 처리의 중심 파일

## 핵심 함수
- `chat_completion_tools_handler()`: 도구 함수 호출 핸들러 → (modified_body, {"sources": list})
- `chat_web_search_handler()`: 웹 검색 통합
- `chat_image_generation_handler()`: 이미지 생성
- `chat_completion_files_handler()`: 파일/문서 검색 (RAG 소스 추출)
- `process_chat_payload()`: 메인 오케스트레이터 → (form_data, metadata, events)
- `process_chat_response()`: 후처리 (배경 작업)
- `get_content_from_response()`: 스트리밍/일반 응답에서 콘텐츠 추출

## RAG 주입 흐름
1. `chat_completion_files_handler()`: 파일에서 문서 청크 검색
2. 소스 수집 → `context_string` 빌드 (`<source id="N">...</source>` 형식)
3. `rag_template(config.RAG_TEMPLATE, context_string, prompt)` 포맷팅
4. Ollama: `prepend_to_first_user_message_content()` / 기타: `add_or_update_system_message()`

## 스트리밍 변환 패턴
- SSE 형식: `data: {json}\n\n`, 종료: `data: [DONE]\n\n`
- `stream_options: {"include_usage": true}` 추가로 usage 추적
- 청크별 처리 → 실시간 UI 업데이트

## 주요 유틸리티 (chat_utils에서 임포트)
- `add_or_update_system_message(content, messages)`: 시스템 메시지 추가/갱신
- `prepend_to_first_user_message_content(content, messages)`: Ollama 2.0+ 대응
- `rag_template(template, context, prompt)`: RAG 템플릿 포맷팅
- `get_last_user_message(messages)`: 마지막 사용자 메시지 추출

## 메시지 추적 (Tracing)
- `ENABLE_MESSAGE_TRACING`: boolean 활성화
- `create_trace_context()` → `set_trace_context(request, trace_ctx)`

## 수정 시 주의사항
- 기존 함수 시그니처 변경 금지
- 새 기능은 기존 흐름에 플러그인 방식으로 추가
- 스트리밍 응답 수정 시 SSE 형식 유지 필수
- multi-part content 블록 처리 항상 고려

## 참조 파일
- `utils/middleware.py`: 요청/응답 변환 (93KB)
- `utils/chat.py`: 채팅 완료 생성 (14KB)
- `utils/chat_utils.py`: 메시지 조작 유틸리티
- `routers/openai.py`: OpenAI 프록시, 스트리밍
