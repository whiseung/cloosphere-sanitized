---
paths:
  - "src/lib/components/channel/**/*.svelte"
  - "src/routes/(app)/channels/**/*"
---

# 채널 UI 규칙

## 컴포넌트 계층
```
Channel.svelte (메인 컨테이너)
├── Navbar.svelte (상단 헤더 — sticky + gradient)
├── Messages.svelte (메시지 리스트 — 역순 표시)
│   └── Message.svelte (개별 메시지)
│       ├── ProfilePreview.svelte (프로필 미리보기 드롭다운)
│       └── ReactionPicker.svelte (이모지 선택 — VirtualList)
├── MessageInput.svelte (입력 박스)
│   └── InputMenu.svelte (캡처/업로드 드롭다운)
└── Thread.svelte (스레드 뷰 — 별도 패널)
```

## Channel.svelte 핵심 기능
- **Socket.IO 실시간 이벤트**: `message`, `message:update`, `message:delete`, `message:reply`, `message:reaction`
- **스레드**: 모바일=모달, 데스크탑=사이드 패널 (반응형)
- **타이핑 인디케이터**: 5초 타임아웃 디바운스
- **드래그 앤 드롭**: 파일 지원
- **자동 스크롤**: 하단 근처일 때만 + 수동 scroll-to-bottom 버튼

## 메시지 표시 (Message.svelte)
- **프로필**: 아바타 클릭 → ProfilePreview (온라인 상태 표시, 녹색 ping 애니메이션)
- **인라인 편집**: textarea + Cmd+Enter 저장
- **파일/이미지**: Image, FileItem 컴포넌트
- **마크다운 렌더링**: Markdown 컴포넌트
- **이모지 리액션**: `{name, user_ids[], count}` 배열 + 내 리액션 하이라이팅
- **스레드**: "View Replies" 버튼 (reply count 표시)
- **호버 액션**: 리액션 추가, 답글, 편집, 삭제

## ReactionPicker.svelte
- 이모지 검색 (VirtualList from `@sveltejs/svelte-virtual-list`)
- 그룹별 정리 (size-5 SVG, `/assets/emojis/`)
- 키보드 네비게이션 + Escape 닫기
- `shortCodesToEmojis` 스토어 매핑 (`:heart:` → SVG)

## MessageInput.svelte
- **RichTextInput** 기반 입력
- 파일 업로드 (진행률 추적)
- 이미지 압축 지원
- 화면 캡처 기능
- 음성 녹음 (VoiceRecording)
- **키보드**: Enter=전송, Shift+Enter=줄바꿈
- **타이핑 인디케이터 발행**: Socket.IO 이벤트

## Thread.svelte
- `threadId`로 부모 메시지 + 답글 로드
- Messages 컴포넌트 재사용 (`thread={true}` 플래그)
- "Thread" 헤더 + 닫기 버튼
- 별도 이벤트 핸들링 (메인 채널과 분리)

## 라우트 구조
```svelte
<!-- src/routes/(app)/channels/[id]/+page.svelte -->
<Channel id={$page.params.id} />
```

## 참조 파일
- `src/lib/components/channel/Channel.svelte`: 메인 채널 컨테이너
- `src/lib/components/channel/Messages.svelte`: 메시지 리스트
- `src/lib/components/channel/Messages/Message.svelte`: 개별 메시지
- `src/lib/components/channel/MessageInput.svelte`: 입력 박스
- `src/lib/components/channel/Thread.svelte`: 스레드 뷰
- `src/lib/components/channel/Messages/Message/ReactionPicker.svelte`: 이모지 선택
