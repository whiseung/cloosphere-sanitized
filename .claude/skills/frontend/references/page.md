# 페이지/라우트 생성 가이드

## 라우트 구조

```
src/routes/
├── +layout.svelte      # 루트 레이아웃
├── auth/               # 인증 (로그인, 회원가입)
├── (app)/              # 인증된 사용자 영역
│   ├── +layout.svelte  # 앱 레이아웃 (사이드바, 인증)
│   ├── home/           # 메인 채팅
│   ├── c/[id]/         # 개별 채팅
│   ├── workspace/      # 작업 공간
│   ├── playground/     # 모델 테스트
│   ├── channels/[id]/  # 채널
│   └── admin/          # 관리자 패널
└── s/[id]/             # 공유 채팅 (공개)
```

## 기본 페이지 템플릿

```svelte
<script lang="ts">
  import { onMount, getContext } from 'svelte';
  import { goto } from '$app/navigation';
  import { user } from '$lib/stores';
  import Spinner from '$lib/components/common/Spinner.svelte';

  const i18n = getContext('i18n');

  let loading = true;
  let data = null;

  onMount(async () => {
    if (!$user) {
      await goto('/auth');
      return;
    }
    await loadData();
  });

  const loadData = async () => {
    loading = true;
    try {
      // API 호출
    } finally {
      loading = false;
    }
  };
</script>

<svelte:head>
  <title>{$i18n.t('Page Title')} | Cloosphere</title>
</svelte:head>

{#if loading}
  <div class="flex items-center justify-center h-full">
    <Spinner />
  </div>
{:else}
  <div class="p-4">
    <!-- 페이지 콘텐츠 -->
  </div>
{/if}
```

## 동적 라우트

```svelte
<script lang="ts">
  import { page } from '$app/stores';

  // URL 파라미터
  $: itemId = $page.params.id;

  // 쿼리 파라미터
  $: query = $page.url.searchParams.get('q') ?? '';
</script>
```

## 네비게이션

```svelte
<script lang="ts">
  import { goto } from '$app/navigation';

  goto(`/c/${chatId}`);
  goto('/', { replaceState: true }); // 뒤로가기 불가
</script>
```

## 권한 체크

```svelte
<script lang="ts">
  import { user, userPermissions } from '$lib/stores';

  $: isAdmin = $user?.role === 'admin';
  $: hasUsersAccess = isAdmin || $userPermissions?.admin?.users;
</script>

{#if hasUsersAccess}
  <!-- 권한 있는 콘텐츠 -->
{/if}
```

## 관리자 패널 구조

```
src/routes/(app)/admin/
├── +layout.svelte        # 관리자 레이아웃 (탭, 권한)
├── users/+page.svelte    # 사용자 관리
├── evaluations/          # 평가
├── functions/            # 함수
├── settings/             # 설정
├── monitoring/           # 모니터링
└── developer/            # 개발자
```

## 워크스페이스 구조

```
src/routes/(app)/workspace/
├── +layout.svelte           # 탭 네비게이션
├── models/                  # Agents
├── knowledge/               # 지식 기반
│   ├── +page.svelte        # 목록
│   ├── create/+page.svelte # 생성
│   └── [id]/+page.svelte   # 상세/편집
├── database/                # DbSphere
├── glossary/                # 용어집
├── prompts/                 # 프롬프트
└── tools/                   # 도구
```

## 참조 파일

- `src/routes/(app)/+layout.svelte` - 앱 레이아웃
- `src/routes/(app)/workspace/+layout.svelte` - 워크스페이스 레이아웃
- `src/routes/(app)/admin/+layout.svelte` - 관리자 레이아웃
