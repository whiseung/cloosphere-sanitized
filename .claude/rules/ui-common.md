---
paths:
  - "src/lib/components/common/**/*.svelte"
---

# 공용 UI 컴포넌트 규칙

## 디자인 시스템 컴포넌트 (--cloo-* CSS 변수 기반)

raw HTML 대신 반드시 이 컴포넌트들을 사용할 것.

### Button.svelte
- Props: `kind` (filled|outlined|text), `size` (sm|md|lg), `status` (default|error), `disabled`, `loading`, `type`
- Slots: `prefix`, `default`, `suffix`
- Events: `on:click`, `on:mousedown`, `on:keydown`
- 로딩 시 Spinner 자동 표시

### Input.svelte
- Props: `value`, `label`, `caption`, `placeholder`, `size` (sm|md), `type`, `required`, `disabled`, `loading`, `error`, `readOnly`
- Slots: `prefix`, `suffix`, `right`
- Events: `input`, `change`, `focus`, `blur`, `keydown`
- LabelBase 자동 통합 (label/caption 제공 시)

### Textarea.svelte
- Props: `value`, `label`, `caption`, `placeholder`, `rows`, `size` (sm|md), `autoResize`, `required`, `disabled`, `loading`, `error`, `readOnly`
- LabelBase 자동 통합

### LabelBase.svelte (복합 레이블)
- Props: `label`, `caption`, `required`, `size` (sm|md|lg), `disabled`, `loading`, `error`
- Slot: `right` (Switch, Selector 등 배치)
- Input, Textarea, Form에서 내부적으로 사용됨

### Selector.svelte (bits-ui Select 래퍼)
- Props: `value`, `items` ({ value, label, disabled? }[]), `placeholder`, `searchEnabled`, `size` (sm|md), `disabled`, `loading`, `error`
- Events: `change` ({ value, item }), `openChange`
- 내장 검색 필터링, 체크 아이콘

### Tabs.svelte
- Exports: `TabState`, `TabItem` 타입
- Props: `items` (TabItem[]), `ariaLabel`, `className`
- TabItem: `{ id, label?, labelKey?, href, state?: 'default'|'selected'|'disabled'|'loading'|'error' }`
- i18n 지원 (labelKey), 라운드 필 디자인

### Switch.svelte
- Props: `state` (boolean), `disabled`, `loading`, `error`
- Events: `change` (boolean)
- 체크/해제 SVG 아이콘, info 파란색

### Checkbox.svelte
- Props: `state` ('unchecked'|'checked'), `indeterminate`, `disabled`
- Events: `change` (state)
- 3상태 지원, SVG 체크마크

### Radio.svelte / RadioGroup.svelte
- RadioGroup Props: `value`, `options` ({ label, value, disabled? }[]), `name`, `orientation` (horizontal|vertical), `disabled`
- RadioGroup Events: `change` ({ value, option })

### Form.svelte (Switch 목록 컨테이너)
- Exports: `FormItem` 타입
- Props: `label`, `caption`, `required`, `items` (FormItem[]), `disabled`, `loading`, `error`
- FormItem: `{ id, label, caption?, required?, state: boolean, disabled?, loading?, error? }`
- Events: `change` ({ index, nextState, item, items })

### Badge.svelte
- Props: `status` (default|secondary|info|success|warning|danger|accent), `size` (sm|md|lg), `content`, `loading`
- Slots: `default`
- Legacy: `type` (info|success|warning|error|muted) → 자동 매핑

### WorkspaceCard.svelte
- 워크스페이스 항목 카드 컴포넌트

## CSS 클래스 네이밍 규칙
- BEM: `.cloo-{component}`, `.cloo-{component}__{element}`, `.is-{state}`
- 컴포넌트 내부 `<style>` 블록에서 `var(--cloo-*)` CSS 변수 사용
- `dark:` Tailwind 접두사 불필요 (CSS 변수가 자동 처리)

## 기존 컴포넌트 (레이아웃/오버레이)

### Modal.svelte
- Props: `show`, `size` (xs=16rem, sm=30rem, md=42rem, lg=56rem), `containerClassName`, `className`
- Escape 키 닫기, 바디 스크롤 방지, `flyAndScale` 애니메이션

### Drawer.svelte
- Props: `show`, `className`
- 모바일용 하단 시트 모달

### Tooltip.svelte
- Props: `placement`, `content`, `touch`, `className`, `theme`, `offset`, `allowHTML`
- tippy.js + DOMPurify 새니타이징

### ConfirmDialog.svelte
- Props: `title`, `message`, `cancelLabel`, `confirmLabel`, `onConfirm`, `input`, `show`
- 키보드: Escape(취소), Enter(확인)

### Collapsible.svelte
- Props: `open`, `title`, `chevron`, `grow`, `disabled`, `hide`
- slide 트랜지션 (quintOut 이징)

### Spinner.svelte
- Props: `className` (기본: size-5)
- SVG 기반 회전 스피너

## 기타 유틸리티 컴포넌트
- `Pagination.svelte`: 페이지 네비게이션
- `Tags.svelte` / `TagInput.svelte`: 태그 관리
- `WorkspaceTagSelector.svelte`: 워크스페이스 공용 태그 선택기
- `CodeEditor.svelte`: 코드 구문 강조
- `SensitiveInput.svelte` / `SensitiveTextarea.svelte`: 비밀번호/API 키 마스킹 입력
- `TokenInput.svelte`: 액세스 토큰/API 키 전용 입력
- `SharePointBrowser.svelte`: SharePoint 파일 브라우저
- `JsonTreeView.svelte`: JSON 탐색기
- `Sidebar.svelte`: 사이드 패널 (left|right)
- `VerticalTabs.svelte`: 수직 탭 네비게이션 (설정/관리 페이지용)
- `Banner.svelte`: 상단 공지/경고 배너
- `GuidePanel.svelte`: 인라인 가이드/도움말 패널
- `SRModal.svelte`: 시스템 요약/공지 모달
- `SlideShow.svelte`: 이미지 슬라이드쇼
- `UserSearchSelect.svelte`: 사용자 검색 셀렉터 (access_control, 조직 배정 등에서 공통 사용)
- `ShareModal.svelte`: 공유/초대 모달
- `Dropdown.svelte`: bits-ui DropdownMenu 래퍼
- `Loader.svelte` / `Marquee.svelte`: 로딩/회전 텍스트 표시
- `Valves.svelte`: Functions/Tools valves 편집 UI
- `InquiryModal.svelte`: 문의 제출 모달
- `ImagePreview.svelte` / `Image.svelte` / `SVGPanZoom.svelte`: 이미지·SVG 뷰어
- `FileItem.svelte` / `FileItemModal.svelte`: 파일 리스트 항목 (dismissible)
- `Folder.svelte`: 폴더 트리 노드

## 아이콘 (src/lib/components/icons/)
- 150+ SVG 아이콘 컴포넌트
- Props: `className="size-5"`, `strokeWidth="2"`

## 트랜지션/애니메이션
- `flyAndScale`: scale(0.95→1) + translateY(-8→0), 200ms, cubicOut
- `slide`: 접기/펼치기
- `fade`: 투명도

## 참조 파일
- `src/lib/components/common/Button.svelte`: 버튼
- `src/lib/components/common/Input.svelte`: 입력 (LabelBase 통합)
- `src/lib/components/common/Selector.svelte`: 드롭다운 선택
- `src/lib/components/common/Tabs.svelte`: 탭 네비게이션
- `src/lib/components/common/Form.svelte`: Switch 목록 컨테이너
- `src/lib/components/common/Modal.svelte`: 기본 모달
