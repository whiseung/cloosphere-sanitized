---
paths:
  - "src/routes/**/*.svelte"
---

# 라우트/페이지 작성 규칙

## 라우트 구조
```
src/routes/
├── auth/              # 인증 페이지
├── (app)/             # 인증된 사용자 영역 (그룹)
│   ├── home/          # 메인 채팅
│   ├── c/[id]/        # 개별 채팅
│   ├── workspace/     # 워크스페이스 (agents, knowledge, database...)
│   ├── admin/         # 관리자 패널
│   ├── channels/[id]/ # 채널
│   └── playground/    # 모델 테스팅
└── s/[id]/            # 공개 공유 채팅
```

## 페이지 기본 패턴
```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { user } from '$lib/stores';

  let loaded = false;

  onMount(async () => {
    if (!$user) {
      await goto('/auth');
      return;
    }
    // 데이터 로드
    loaded = true;
  });
</script>

{#if loaded}
  <MainComponent />
{:else}
  <Spinner />
{/if}
```

## 동적 라우트
- `[id]`: 필수 파라미터 — `$page.params.id`
- `[[id]]`: 선택적 파라미터

## 네비게이션
- `goto('/path')`: 프로그래매틱 이동
- `$page.url.searchParams`: 쿼리 파라미터

## 관리자 레이아웃
- `isMenuVisible(tab.id)`: 권한 기반 탭 필터링
- `$userPermissions?.admin?.[permissionKey]`: 권한 체크
- 첫 접근 가능 탭으로 자동 리다이렉트

## 워크스페이스 구조
- 경로: `/workspace/agents`, `/workspace/knowledge`, `/workspace/database` 등
- 패턴: 목록 → 상세/편집 컴포넌트 래퍼

## 참조 파일
- `routes/(app)/admin/+page.svelte`: 관리자 탭 구조
- `routes/(app)/workspace/`: 워크스페이스 페이지
- `routes/+layout.svelte`: 루트 레이아웃 (Socket.IO, i18n)
