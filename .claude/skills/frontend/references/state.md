# 상태 관리 가이드

## 스토어 위치

- **메인 스토어**: `src/lib/stores/index.ts`
- 모든 전역 상태는 이 파일에 정의

## 컴포넌트에서 사용

```svelte
<script lang="ts">
  import { user, settings, showSidebar } from '$lib/stores';

  // 자동 구독 ($ 문법)
  $: userName = $user?.name ?? 'Guest';
  $: isAdmin = $user?.role === 'admin';
</script>

<button on:click={() => $showSidebar = !$showSidebar}>Toggle</button>
```

## 스토어 업데이트

```svelte
<script lang="ts">
  import { chats } from '$lib/stores';

  // set - 전체 값 교체
  chats.set(newChats);

  // update - 현재 값 기반
  chats.update(current => [...(current ?? []), newChat]);

  // $ 문법으로 직접 할당
  $settings = { ...$settings, darkMode: true };
</script>
```

## 주요 스토어

```typescript
// 사용자/인증
export const user: Writable<SessionUser | undefined> = writable(undefined);
export const config: Writable<Config | undefined> = writable(undefined);
export const settings: Writable<Settings> = writable({});

// 채팅
export const chatId = writable('');
export const chats = writable(null);

// 모델/도구
export const models: Writable<Model[]> = writable([]);
export const knowledge: Writable<null | Document[]> = writable(null);

// UI 상태
export const showSidebar = writable(false);
export const mobile = writable(false);

// 실시간
export const socket: Writable<null | Socket> = writable(null);
```

## Context API

```svelte
<!-- i18n (가장 흔한 사용) -->
<script lang="ts">
  import { getContext } from 'svelte';
  const i18n = getContext('i18n');
</script>
<span>{$i18n.t('Save')}</span>
```

## 배열/객체 반응성

Svelte는 **재할당**으로 반응성 감지. `push()` 등 뮤테이션은 감지 불가.

```svelte
<!-- BAD -->
items.push('c');

<!-- GOOD -->
items = [...items, 'c'];
items = items.filter(i => i.id !== targetId);
```

## 참조 파일

- `src/lib/stores/index.ts` - 모든 스토어 정의
- `src/routes/(app)/+layout.svelte` - 스토어 초기화 예시
