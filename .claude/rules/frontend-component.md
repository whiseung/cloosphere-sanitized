---
paths:
  - "src/lib/components/**/*.svelte"
---

# Svelte 컴포넌트 작성 규칙

## 기본 구조
```svelte
<script lang="ts">
  import { getContext, createEventDispatcher } from 'svelte';
  const i18n = getContext('i18n');
  const dispatch = createEventDispatcher();

  export let value: string = '';
</script>
```

## 필수 사항
- `<script lang="ts">` TypeScript 필수
- `const i18n = getContext('i18n');` → `$i18n.t('key')` 사용 (하드코딩 금지)
- 공통 컴포넌트 우선 사용 (Button, Input, Selector, Switch, Tabs 등)

## ⚠️ 템플릿 인라인 표현식은 TypeScript가 아님
`<script lang="ts">`는 스크립트 블록에만 적용됨. 템플릿 내부의 인라인 JS 표현식
(`on:click={...}`, `on:input={...}`, `{#if expr}`, `class:name={cond}`, `{@const}`,
`bind:value={...}` 등)은 Svelte 컴파일러가 **순수 JavaScript로 파싱**하므로
다음 TS 문법이 전부 `Unexpected token` 파싱 에러:
- 타입 단언: `foo as HTMLInputElement`, `<T>foo`
- Non-null 단언: `foo!.value`
- `satisfies` 연산자
- 타입 파라미터: `fn<T>(...)`
- 타입 선언: `const x: number = ...`

**해결**: 로직을 `<script lang="ts">` 안의 named 함수로 빼고, 템플릿에서는
호출만 할 것. 한 줄이라도 타입 구문이 필요하면 즉시 스크립트로 옮긴다.

```svelte
<!-- ❌ 파싱 에러 -->
<button on:click={() => {
  const el = document.getElementById('x') as HTMLInputElement | null;
  el?.click();
}}>Click</button>

<!-- ✅ 스크립트로 분리 -->
<script lang="ts">
  const handleClick = () => {
    const el = document.getElementById('x') as HTMLInputElement | null;
    el?.click();
  };
</script>
<button on:click={handleClick}>Click</button>
```

## 공통 컴포넌트 우선 사용
raw HTML 대신 `src/lib/components/common/`의 공통 컴포넌트를 사용할 것:
- `<input>` → `<Input label="..." size="md" />`
- `<select>` → `<Selector items={...} />`
- `<button>` → `<Button kind="filled" size="md">`
- 수동 토글 → `<Switch bind:state={v} />`
- 수동 탭 → `<Tabs items={...} />`

## 스타일링
- 공통 컴포넌트는 `--cloo-*` CSS 변수 자동 적용 (dark: 불필요)
- 커스텀 영역은 기존 방식 유지: `dark:` 변형 모든 색상에 적용
- BEM 네이밍: `.cloo-{component}__{element}`, `.is-{state}`

## Props 패턴
```svelte
export let prop: Type = default;
export let className: string = '';  // CSS 클래스 오버라이드
```

## 이벤트 패턴
```svelte
const dispatch = createEventDispatcher();
dispatch('change', value);
// 사용 측: <Component on:change={handler} />
```

## UI 라이브러리
- **bits-ui**: DropdownMenu, Dialog (저수준) — Selector가 bits-ui Select 래핑
- **tippy.js**: Tooltip (DOMPurify 포함)
- **svelte-sonner**: `toast.success()`, `toast.error()`

## 아이콘
```svelte
import PencilSquare from '$lib/components/icons/PencilSquare.svelte';
<PencilSquare className="size-5" strokeWidth="2" />
```

## 참조 파일
- `components/common/Button.svelte`: 버튼 컴포넌트
- `components/common/Input.svelte`: 입력 컴포넌트 (LabelBase 통합)
- `components/common/Selector.svelte`: 드롭다운 선택
- `components/common/Modal.svelte`: 모달 패턴
- `components/workspace/Agents/AgentEditor.svelte`: 공통 컴포넌트 조합 예시
