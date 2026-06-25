---
paths:
  - "src/lib/stores/**/*.ts"
---

# Svelte 스토어 사용 규칙

## 스토어 정의
```typescript
import { writable, type Writable } from 'svelte/store';

export const user: Writable<SessionUser | undefined> = writable(undefined);
export const config: Writable<Config | undefined> = writable(undefined);
export const settings: Writable<Settings> = writable({});
```

## 자동 구독 (`$` 문법)
```svelte
$: userName = $user?.name;
$user = newUser;           // set
$settings = { ...$settings, key: value };  // update
```

## 주요 스토어 (30+)
- **인증**: user, config, settings
- **채팅**: chatId, chats, messages, pinnedChats, tags
- **모델**: models (OpenAI, Ollama, Arena)
- **지식**: knowledge
- **UI**: showSidebar, showSettings, theme, mobile
- **실시간**: socket, activeUserIds
- **권한**: userPermissions

## UserPermissions 타입
```typescript
{
  admin: { users, settings, evaluations, functions, monitoring },
  workspace: { knowledge, agents, prompts, tools, glossary, guardrails, flows },
  sharing: { public_chats, public_models, public_prompts, public_tools, public_knowledge, public_glossary },
  chat: { delete, edit, copy, archive, pin, tag, search, temporary, file_upload, code_execution },
  features: { web_search, image_generation, direct_tool_servers, arena_model }
}
```

## 반응성 주의
- 배열/객체: 뮤테이션 대신 재할당 필요
- Set: 새 Set 할당 (`$set = new Set([...$set, item])`)
- `onDestroy`에서 unsubscribe (수동 구독 시)

## 참조 파일
- `stores/index.ts`: 모든 스토어 정의
