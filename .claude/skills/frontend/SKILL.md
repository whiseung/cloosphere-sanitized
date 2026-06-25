---
name: frontend
description: |
  Cloosphere 프론트엔드 개발 컨벤션 및 디자인 시스템 가이드. Svelte 컴포넌트, 공통 UI 컴포넌트(Button, Input, Selector, Tabs, Switch 등), CSS 디자인 토큰(--cloo-*), API 클라이언트, 상태 관리, 페이지 생성, 기존 페이지 디자인 마이그레이션 시 사용.
  프론트엔드 컴포넌트를 수정하거나 새로 만들 때, Svelte 파일을 편집할 때, UI 디자인을 적용할 때, 피그마 디자인을 코드로 변환할 때 반드시 이 스킬을 사용할 것.
---

# Frontend Development Guide

Cloosphere 프론트엔드는 **컴포넌트 기반 디자인 시스템**을 사용합니다.
코딩 규칙은 `.claude/rules/frontend-*.md`, `.claude/rules/ui-*.md`에서 해당 파일 작업 시 자동 로드됩니다.

---

## 핵심 원칙: 공통 컴포넌트 우선

새 UI를 작성하거나 기존 UI를 수정할 때, **반드시 공통 컴포넌트를 사용**하세요.
raw HTML (`<input>`, `<select>`, `<button>`) 직접 사용은 피하세요.

| 하지 말 것 | 해야 할 것 |
|-----------|-----------|
| `<input class="...">` | `<Input bind:value={v} label="..." />` |
| `<select class="...">` | `<Selector value={v} items={items} />` |
| `<button class="px-4 py-2 bg-black ...">` | `<Button kind="filled" size="md">` |
| `dark:bg-gray-900` | `var(--cloo-bg-surface)` |
| 수동 `<label>` + `<input>` | `<Input label="..." caption="..." />` |
| 커스텀 토글 | `<Switch bind:state={v} />` |
| 커스텀 탭 | `<Tabs items={tabItems} />` |

---

## 공통 UI 컴포넌트 카탈로그

모든 컴포넌트는 `src/lib/components/common/`에 위치합니다.

### Button

```svelte
import Button from '$lib/components/common/Button.svelte';

<Button kind="filled" size="md" on:click={save}>
  <svelte:fragment slot="prefix"><Plus className="size-3.5" /></svelte:fragment>
  {$i18n.t('Create')}
</Button>

<Button kind="outlined" size="sm" loading={saving}>{$i18n.t('Save')}</Button>
<Button kind="text" size="sm" status="error" on:click={remove}>{$i18n.t('Delete')}</Button>
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `kind` | `'filled'\|'outlined'\|'text'` | `'filled'` | 버튼 스타일 |
| `size` | `'sm'\|'md'\|'lg'` | `'sm'` | 크기 |
| `status` | `'default'\|'error'` | `'default'` | 위험 동작용 |
| `disabled` | `boolean` | `false` | |
| `loading` | `boolean` | `false` | Spinner 표시 |
| `type` | `'button'\|'submit'\|'reset'` | `'button'` | |
| Slots | `prefix`, `default`, `suffix` | | 아이콘/텍스트 |

### Input

```svelte
import Input from '$lib/components/common/Input.svelte';

<Input
  bind:value={name}
  label={$i18n.t('Name')}
  caption={$i18n.t('Enter a unique name')}
  placeholder={$i18n.t('Name')}
  size="md"
  required
/>
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `value` | `string` | `''` | |
| `label` | `string` | `''` | LabelBase 연동 |
| `caption` | `string` | `''` | 설명 텍스트 |
| `size` | `'sm'\|'md'` | `'sm'` | |
| `type` | `text\|email\|password\|search\|number\|url\|tel` | `'text'` | |
| `required`, `disabled`, `loading`, `error`, `readOnly` | `boolean` | `false` | 상태 |
| Slots | `prefix`, `suffix`, `right` | | 아이콘/액션 |
| Events | `input`, `change`, `focus`, `blur`, `keydown` | | |

### Textarea

```svelte
import Textarea from '$lib/components/common/Textarea.svelte';

<Textarea
  bind:value={description}
  label={$i18n.t('Description')}
  placeholder={$i18n.t('Enter description')}
  size="md"
  autoResize
/>
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `value` | `string` | `''` | |
| `label`, `caption` | `string` | `''` | LabelBase 연동 |
| `size` | `'sm'\|'md'` | `'sm'` | |
| `rows` | `number` | `3` | |
| `autoResize` | `boolean` | `false` | CSS field-sizing |

### LabelBase (복합 레이블)

```svelte
import LabelBase from '$lib/components/common/LabelBase.svelte';

<LabelBase label={$i18n.t('Feature')} caption={$i18n.t('Enable this feature')} size="md">
  <svelte:fragment slot="right">
    <Switch bind:state={enabled} />
  </svelte:fragment>
</LabelBase>
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `label` | `string` | `''` | 레이블 텍스트 |
| `caption` | `string` | `''` | 보조 설명 |
| `required` | `boolean` | `false` | `*` 표시 |
| `size` | `'sm'\|'md'\|'lg'` | `'sm'` | |
| Slot | `right` | | 오른쪽 정렬 (Switch, Selector 등) |

### Selector (드롭다운)

```svelte
import Selector from '$lib/components/common/Selector.svelte';

<Selector
  value={selectedModel}
  items={models.map(m => ({ value: m.id, label: m.name }))}
  placeholder={$i18n.t('Select a model')}
  searchEnabled
  size="md"
  on:change={(e) => { selectedModel = e.detail.value; }}
/>
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `value` | `string` | `''` | 선택된 값 |
| `items` | `{ value, label, disabled? }[]` | `[]` | 옵션 목록 |
| `searchEnabled` | `boolean` | `false` | 검색 활성화 |
| `size` | `'sm'\|'md'` | `'sm'` | |
| `placeholder` | `string` | `''` | |
| `portal` | `string \| HTMLElement \| null` | `undefined` | 드롭다운 포탈 대상 |
| `contentClassName` | `string` | `''` | 드롭다운 콘텐츠 CSS 클래스 |
| Events | `change` ({ value, item }) | | |

> **Modal 안에서 Selector 사용 시 필수:**
> Modal은 `z-9999`로 body에 포탈됩니다. Selector 드롭다운이 Modal 뒤로 가려지지 않으려면
> 반드시 `portal="body"` + `contentClassName="z-[10000]"` 을 함께 지정해야 합니다.
>
> ```svelte
> <!-- Modal 내부에서 Selector 사용 -->
> <Selector
>   items={items}
>   value={selected}
>   portal="body"
>   contentClassName="z-[10000]"
>   on:change={(e) => { selected = e.detail.value; }}
> />
> ```

### Tabs (탭 네비게이션)

```svelte
import Tabs, { type TabItem } from '$lib/components/common/Tabs.svelte';

<Tabs items={[
  { id: 'general', labelKey: 'General', href: '#general', state: activeTab === 'general' ? 'selected' : 'default' },
  { id: 'advanced', labelKey: 'Advanced', href: '#advanced', state: activeTab === 'advanced' ? 'selected' : 'default' },
]} />
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `items` | `TabItem[]` | `[]` | 탭 목록 |
| `ariaLabel` | `string` | `'Tabs'` | |

TabItem: `{ id, label?, labelKey?, href, state?: 'default'\|'selected'\|'disabled'\|'loading'\|'error' }`

### Switch

```svelte
import Switch from '$lib/components/common/Switch.svelte';

<Switch bind:state={enabled} on:change={(e) => handleToggle(e.detail)} />
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `state` | `boolean` | `false` | 토글 상태 |
| `disabled`, `loading`, `error` | `boolean` | `false` | |
| Events | `change` (boolean) | | |

### Checkbox

```svelte
import Checkbox from '$lib/components/common/Checkbox.svelte';

<Checkbox
  state={isChecked ? 'checked' : 'unchecked'}
  on:change={(e) => { isChecked = e.detail === 'checked'; }}
/>
```

| Prop | Type | Default | 설명 |
|------|------|---------|------|
| `state` | `'unchecked'\|'checked'` | `'unchecked'` | |
| `indeterminate` | `boolean` | `false` | 3상태 |
| `disabled` | `boolean` | `false` | |
| Events | `change` (state) | | |

### RadioGroup

```svelte
import RadioGroup from '$lib/components/common/RadioGroup.svelte';

<RadioGroup
  value={selectedOption}
  options={[
    { label: $i18n.t('Option A'), value: 'a' },
    { label: $i18n.t('Option B'), value: 'b' },
  ]}
  orientation="horizontal"
  on:change={(e) => { selectedOption = e.detail.value; }}
/>
```

### Form (Switch 목록 컨테이너)

```svelte
import Form, { type FormItem } from '$lib/components/common/Form.svelte';

<Form
  label={$i18n.t('Capabilities')}
  caption={$i18n.t('Configure agent capabilities')}
  items={[
    { id: 'search', label: $i18n.t('Web Search'), state: capabilities.search },
    { id: 'code', label: $i18n.t('Code Execution'), caption: $i18n.t('Run code'), state: capabilities.code },
  ]}
  on:change={(e) => {
    const { index, nextState, items } = e.detail;
    capabilities = { ...capabilities, [items[index].id]: nextState };
  }}
/>
```

### Badge

```svelte
import Badge from '$lib/components/common/Badge.svelte';

<Badge status="info" size="sm">Active</Badge>
<Badge status="success" size="sm" content={$i18n.t('Collection')} />
<Badge status="danger" size="sm">Error</Badge>
```

| status | 색상 |
|--------|------|
| `default` | 회색 |
| `info` | 파란색 |
| `success` | 녹색 |
| `warning` | 노란색 |
| `danger` | 빨간색 |

---

## CSS 디자인 토큰 시스템

모든 색상은 `--cloo-*` CSS 변수를 사용합니다. `html.dark`에서 자동 오버라이드되므로
**컴포넌트에서 `dark:` Tailwind 접두사가 불필요**합니다.

### 주요 색상 변수

```css
/* 배경 */
var(--cloo-bg-default)          /* 페이지 배경 */
var(--cloo-bg-surface)          /* 카드/패널 배경 */
var(--cloo-bg-neutral-hovered)  /* 호버 배경 */
var(--cloo-bg-disabled)         /* 비활성 배경 */

/* 텍스트 */
var(--cloo-text-default)        /* 기본 텍스트 */
var(--cloo-text-primary)        /* 강조 텍스트 */
var(--cloo-text-muted)          /* 보조 텍스트 */
var(--cloo-color-on-primary)    /* primary 배경 위 텍스트 */

/* 테두리 */
var(--cloo-border-default)      /* 기본 테두리 */
var(--cloo-border-subtle)       /* 약한 테두리 */
var(--cloo-surface-border)      /* 컴포넌트 테두리 */

/* 주요 색상 */
var(--cloo-color-primary)       /* 주요 액션 */
var(--cloo-color-info)          /* 정보/선택 (파란색) */
var(--cloo-color-success)       /* 성공 (녹색) */
var(--cloo-color-warning)       /* 경고 (노란색) */
var(--cloo-danger-solid)        /* 위험 (빨간색) */

/* 간격 */
var(--cloo-space-1)   /* 4px */
var(--cloo-space-2)   /* 8px */
var(--cloo-space-3)   /* 12px */
var(--cloo-space-4)   /* 16px */

/* 라운딩 */
var(--cloo-radius-default)      /* 4px */

/* 포커스 */
var(--cloo-focus-ring)          /* 포커스 링 색상 */
```

### CSS 클래스 네이밍 (BEM 스타일)

컴포넌트 내부 `<style>` 블록에서 사용:

```css
.cloo-{component}              /* 래퍼: .cloo-input */
.cloo-{component}__{element}   /* 자식: .cloo-input__field */
.is-{state}                    /* 상태: .is-sm, .is-error, .is-disabled */
```

### 새 컴포넌트의 스타일링 방식

```svelte
<!-- 공통 컴포넌트 사용 시: CSS 변수가 자동 적용됨 -->
<Input label="Name" size="md" />

<!-- 커스텀 레이아웃에서: Tailwind + CSS 변수 혼합 -->
<div class="flex gap-4 p-[var(--cloo-space-3)] bg-[var(--cloo-bg-surface)] rounded-[var(--cloo-radius-default)]">
  ...
</div>

<!-- 주의: 공통 컴포넌트가 없는 영역만 이전 방식 사용 -->
<div class="text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-900">
  <!-- 공통 컴포넌트 없는 커스텀 영역은 기존 dark: 패턴 유지 -->
</div>
```

---

## 개발 워크플로우

### 신규 기능 개발

1. **기존 코드 참조**: 유사한 컴포넌트 찾아 패턴 확인
   - 워크스페이스: `AgentEditor.svelte`, `KnowledgeBase.svelte`
   - 관리자 설정: `admin/Settings/` 내 컴포넌트들
   - 모달: `common/Modal.svelte`, `ConfirmDialog.svelte`

2. **API 클라이언트**: `src/lib/apis/{resource}/index.ts`
   - 상세: [references/api-client.md](references/api-client.md)

3. **스토어 업데이트**: `src/lib/stores/index.ts`
   - 상세: [references/state.md](references/state.md)

4. **컴포넌트 작성**: 공통 컴포넌트 조합으로 구성
   - `<script lang="ts">` + `const i18n = getContext('i18n');`
   - 공통 컴포넌트 import + 조합
   - 커스텀 레이아웃만 직접 스타일링

5. **페이지 생성**: `src/routes/(app)/{path}/+page.svelte`
   - 상세: [references/page.md](references/page.md)

6. **i18n 키 추가**
   - `en-US/translation.json`과 `ko-KR/translation.json`만 수동 수정
   - **`npm run i18n:parse` 실행 금지** (다른 로케일 꼬임)

### 기존 페이지 마이그레이션

피그마 디자인 적용 시:

1. **대상 파일 읽기** — 현재 사용 중인 패턴 파악
2. **공통 컴포넌트로 교체**
   - `<select>` → `<Selector>`
   - `<input>` → `<Input>` (label/caption 포함)
   - 커스텀 버튼 → `<Button kind="..." size="...">`
   - 수동 토글 → `<Switch>`
   - 수동 탭 → `<Tabs>`
3. **색상 토큰 교체** (공통 컴포넌트 외부 영역)
   - `dark:bg-gray-*` → `bg-[var(--cloo-bg-*)]` (가능한 경우)
   - 공통 컴포넌트 내부는 자동으로 CSS 변수 사용

---

## 컴포넌트 조합 패턴

### LabelBase + Switch (설정 토글)

```svelte
<LabelBase
  label={$i18n.t('Enable Feature')}
  caption={$i18n.t('Turn on this feature')}
  size="md"
>
  <svelte:fragment slot="right">
    <Switch bind:state={config.enableFeature} />
  </svelte:fragment>
</LabelBase>
```

### LabelBase + Selector (설정 드롭다운)

```svelte
<LabelBase
  label={$i18n.t('Default Model')}
  caption={$i18n.t('Choose default model for new chats')}
  size="md"
>
  <svelte:fragment slot="right">
    <Selector
      value={config.defaultModel}
      items={modelOptions}
      size="sm"
      on:change={(e) => { config.defaultModel = e.detail.value; }}
    />
  </svelte:fragment>
</LabelBase>
```

### Form (설정 그룹)

```svelte
<Form
  label={$i18n.t('Chat Settings')}
  caption={$i18n.t('Configure chat behavior')}
  items={chatItems}
  on:change={handleChatSettingsChange}
/>
```

### 폼 레이아웃 (입력 필드)

```svelte
<div class="flex flex-col gap-[var(--cloo-space-3)]">
  <Input bind:value={name} label={$i18n.t('Name')} size="md" required />
  <Textarea bind:value={description} label={$i18n.t('Description')} size="md" />
  <Selector
    value={category}
    items={categoryOptions}
    placeholder={$i18n.t('Select category')}
    size="md"
  />
</div>
```

### 모달 내 폼

```svelte
<Modal bind:show={showCreateModal} size="sm">
  <div class="px-5 py-4">
    <div class="text-lg font-semibold mb-4">{$i18n.t('Create Item')}</div>
    <div class="flex flex-col gap-3">
      <Input bind:value={form.name} label={$i18n.t('Name')} size="md" required />
      <Textarea bind:value={form.description} label={$i18n.t('Description')} size="md" />
    </div>
    <div class="flex justify-end gap-2 mt-4">
      <Button kind="outlined" size="md" on:click={() => showCreateModal = false}>
        {$i18n.t('Cancel')}
      </Button>
      <Button kind="filled" size="md" loading={saving} on:click={handleCreate}>
        {$i18n.t('Create')}
      </Button>
    </div>
  </div>
</Modal>
```

---

## 워크스페이스 기능 추가

### 새 워크스페이스 항목 (Knowledge, DbSphere 등과 유사)

1. API 클라이언트: `src/lib/apis/{resource}/index.ts`
2. 리스트 컴포넌트: `src/lib/components/workspace/{Resource}s.svelte`
3. 상세/편집: `src/lib/components/workspace/{Resource}/{Resource}Detail.svelte`
4. 생성: `src/lib/components/workspace/{Resource}/Create{Resource}.svelte`
5. 페이지: `src/routes/(app)/workspace/{resource}/+page.svelte`

### 관리자 설정 탭 추가

1. 설정 컴포넌트: `src/lib/components/admin/Settings/{TabName}.svelte`
2. `Settings.svelte`에 탭 등록 (allTabs 배열)
3. 아이콘 SVG 추가 (icons 객체)

---

## 체크리스트

- [ ] 공통 컴포넌트(Button, Input, Selector, Switch, Tabs 등) 사용 확인
- [ ] raw HTML `<input>`, `<select>`, `<button>` 대신 공통 컴포넌트 사용
- [ ] `--cloo-*` CSS 변수 사용 (공통 컴포넌트 외부 커스텀 영역)
- [ ] 다크모드: 공통 컴포넌트는 자동, 커스텀 영역은 `dark:` 또는 CSS 변수
- [ ] i18n 키가 en-US, ko-KR에 추가됨
- [ ] API 에러 처리에 `toast.error()` 적용
- [ ] 유사 기존 컴포넌트와 패턴 일치 확인

---

## 참조 문서

| 주제 | 파일 | 설명 |
|------|------|------|
| API 클라이언트 | [references/api-client.md](references/api-client.md) | fetch, 에러 처리, 타입 정의 |
| 상태 관리 | [references/state.md](references/state.md) | writable, derived, Context API |
| 페이지 작성 | [references/page.md](references/page.md) | 라우트, 인증, 동적 파라미터 |

## 주요 라이브러리

| 라이브러리 | 용도 |
|-----------|------|
| svelte-sonner | 토스트 알림 (`toast.success()`, `toast.error()`) |
| bits-ui | 저수준 UI (Dropdown, Dialog) — Selector가 bits-ui Select 래핑 |
| tippy.js | 고급 툴팁 (DOMPurify 새니타이징) |
| @xyflow/svelte | 플로우 빌더 (AgentFlows) |
| Fuse.js | 퍼지 검색 |
| dayjs | 날짜/시간 처리 |
| marked | 마크다운 렌더링 |
