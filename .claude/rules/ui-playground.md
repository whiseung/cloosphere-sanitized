---
paths:
  - "src/lib/components/playground/**/*.svelte"
  - "src/routes/(app)/playground/**/*"
---

# 플레이그라운드 UI 규칙

## 용도
- 관리자 전용 모델 직접 테스트 인터페이스
- 프로덕션 채팅과 분리된 환경

## 컴포넌트 구조
```
playground/
├── Chat.svelte (메인 인터페이스)
├── Chat/
│   ├── Messages.svelte (메시지 리스트)
│   └── Message.svelte (개별 메시지)
```

## Chat.svelte 핵심 기능
- **모델 선택 드롭다운**: 스토어에서 모델 목록 로드
- **시스템 인스트럭션**: Collapsible 패널 + 자동 리사이즈 textarea
- **설정 사이드바 토글**: 파라미터 조정
- **메시지 영역**: user/assistant 역할 교대
- **역할 토글**: 메시지 추가 시 자동 역할 전환
- **Run/Cancel**: SSE 스트리밍 응답 + 중단 지원

## Message.svelte
- Props: `message`, `idx`, `onDelete`
- 읽기 전용 메시지 표시
- 역할 라벨 (USER/ASSISTANT 대문자)
- 자동 확장 textarea
- 삭제 버튼 (X 아이콘)

## 라우트
```svelte
<!-- src/routes/(app)/playground/+page.svelte -->
<Chat />
```

## 참조 파일
- `src/lib/components/playground/Chat.svelte`: 플레이그라운드 메인
- `src/lib/components/playground/Chat/Messages.svelte`: 메시지 리스트
- `src/lib/components/playground/Chat/Message.svelte`: 개별 메시지
