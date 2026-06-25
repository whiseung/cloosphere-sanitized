---
paths:
  - "src/lib/components/chat/**/*.svelte"
  - "src/routes/(app)/c/**/*"
  - "src/routes/(app)/home/**/*"
---

# 채팅 UI 컴포넌트 규칙

## 컴포넌트 계층
```
Chat.svelte (56KB, 메인 오케스트레이션)
├── Messages.svelte (13KB, 메시지 트리)
│   └── Message.svelte (2.8KB, 라우터)
│       ├── UserMessage.svelte (17KB)
│       ├── ResponseMessage.svelte (59KB)
│       │   └── ContentRenderer.svelte (4.9KB)
│       │       ├── Markdown.svelte (1.5KB)
│       │       └── FloatingButtons.svelte (8.7KB)
│       └── MultiResponseMessages.svelte (11KB)
├── MessageInput.svelte (46KB, 입력 시스템)
│   ├── RichTextInput, VoiceRecording.svelte
│   ├── Commands/ (Knowledge, Models, Prompts 자동완성)
│   └── InputMenu.svelte
└── ChatControls.svelte (6.8KB, 제어판)
```

## 메시지 트리 구조
```typescript
history = {
  currentId: string,
  messages: {
    [id]: {
      id, role, content, model,
      parentId, childrenIds,    // 트리 관계
      timestamp, files, status,
      annotation, sources, error,
      code_executions, statusHistory
    }
  }
}
```
- 메시지 추가/삭제 시 `parentId`/`childrenIds` 반드시 동기화
- 삭제 시 손자 노드를 부모에 재연결 (트리 힐링)

## 마크다운 렌더링 파이프라인
```
content → processResponseContent() → replaceTokens()
→ marked.lexer() → tokens
→ MarkdownTokens.svelte (블록 레벨)
→ MarkdownInlineTokens.svelte (인라인 레벨)
```
- `MarkdownTokens.svelte` (11KB): heading, code, table(CSV 내보내기), list(체크박스), blockquote(alert), details, HTML(DOMPurify)
- `MarkdownInlineTokens.svelte` (2.7KB): strong, em, link, image, code(클릭 복사), del, katex, Source(인용)

## 코드 블록 (CodeBlock.svelte, 14KB)
- 언어별 처리: Mermaid(SVG), Python(Pyodide WebWorker), HTML/SVG(iframe), 기타(highlight.js)
- 실행: Python은 Pyodide, 서버는 `POST /api/v1/utils/code`
- Props: `lang`, `code`, `run`, `collapsed`, `save`

## SSE 스트리밍 패턴
```typescript
const [res, controller] = await chatCompletion(..., stream: true);
const stream = await createOpenAITextStream(res.body, splitLargeDeltas);

for await (const update of stream) {
  if (update.done) break;
  if (update.sources) history.messages[id].sources = update.sources;
  history.messages[id].content += update.value;
  messages = messages;  // 반응성 트리거
  triggerScroll();       // 자동 스크롤
}
```
- `createOpenAITextStream`: EventSourceParserStream으로 SSE 파싱
- 큰 델타 청킹 (1-3자씩), 탭 활성 시 5ms sleep으로 부드러운 UI

## 인용/소스 (Citations.svelte, 4.2KB)
- 소스 집계 및 중복 제거 (source ID 기반)
- 유사도 점수 표시 (cosine similarity → 백분율)
- 모달 미리보기 (CitationsModal)

## 텍스트 선택 (FloatingButtons.svelte, 8.7KB)
- mouseup 이벤트로 선택 감지
- 부모 컨테이너 기준 위치 계산 (좌/우 공간 판단)
- 액션: 복사, 질문, 요약 등

## ResponseMessage 특수 기능
- DbSphere 차트: `[[dbsphere:chart]]` 정규식 감지 → Plotly.js JSON 또는 HTML iframe
- 메시지 상태: `status.action` (web search, code execution 등), `statusHistory[]`
- 피드백: `annotation` (rating/comment via RateComment.svelte)

## 멀티 모델 응답 (MultiResponseMessages.svelte, 11KB)
- 모델별 응답 그룹핑 → 이전/다음 네비게이션
- 응답 병합 기능 (`mergeResponses`)

## MessageInput 핵심 Props
```typescript
export let prompt = '';
export let files = [];
export let selectedModels: string[] = [];
export let webSearchEnabled = false;
export let imageGenerationEnabled = false;
export let codeInterpreterEnabled = false;
export let selectedToolIds = [];
```

## 자동 스크롤
- 하단 50px 버퍼 내에 있을 때만 자동 스크롤
- 사용자가 위로 스크롤 시 자동 스크롤 비활성화

## 참조 파일
- `src/lib/components/chat/Chat.svelte`: 메인 채팅 오케스트레이션
- `src/lib/components/chat/Messages.svelte`: 메시지 리스트 렌더러
- `src/lib/components/chat/MessageInput.svelte`: 입력 시스템
- `src/lib/components/chat/Messages/ResponseMessage.svelte`: AI 응답 표시
- `src/lib/components/chat/Messages/Markdown/MarkdownTokens.svelte`: 블록 렌더링
- `src/lib/apis/streaming/index.ts`: SSE 스트리밍 유틸리티
