---
paths:
  - "src/**/*.svelte"
  - "tailwind.config.js"
---

# Tailwind CSS/다크모드 규칙

## 디자인 시스템 (--cloo-* CSS 변수)

공통 컴포넌트(Button, Input, Selector 등)는 CSS 변수를 사용하므로 `dark:` 접두사가 불필요합니다.
커스텀 영역에서도 가능하면 CSS 변수를 사용하세요:

```html
<!-- 공통 컴포넌트: dark: 불필요 -->
<Input label="Name" size="md" />
<Button kind="filled">Save</Button>

<!-- 커스텀 영역: CSS 변수 사용 가능 -->
<div class="bg-[var(--cloo-bg-surface)] text-[var(--cloo-text-default)]">...</div>

<!-- 커스텀 영역: 기존 dark: 패턴도 허용 -->
<div class="bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300">...</div>
```

### 주요 CSS 변수
- 배경: `--cloo-bg-default`, `--cloo-bg-surface`, `--cloo-bg-neutral-hovered`, `--cloo-bg-disabled`
- 텍스트: `--cloo-text-default`, `--cloo-text-primary`, `--cloo-text-muted`
- 테두리: `--cloo-border-default`, `--cloo-border-subtle`, `--cloo-surface-border`
- 색상: `--cloo-color-primary`, `--cloo-color-info`, `--cloo-danger-solid`
- 간격: `--cloo-space-1`(4px) ~ `--cloo-space-4`(16px)
- 라운딩: `--cloo-radius-default` (4px)

## 다크모드
- `darkMode: 'class'` — `dark:` 접두사 사용
- 공통 컴포넌트 외부의 커스텀 영역: 모든 색상에 `dark:` 변형 필수

## Gray 스케일 (CSS 변수)
- 11단계: 50, 100, 200, 300, 400, 500, 600, 700, 800, 850, 900, 950
- 사용: `text-gray-700 dark:text-gray-300`, `bg-gray-50 dark:bg-gray-850`

## BEM CSS 클래스 네이밍 (컴포넌트 내부 <style>)
```css
.cloo-{component}              /* 래퍼: .cloo-input */
.cloo-{component}__{element}   /* 자식: .cloo-input__field */
.is-{state}                    /* 상태: .is-sm, .is-error */
```

## 모달
- 오버레이: `bg-black/50 z-50`
- 컨테이너: `bg-white dark:bg-gray-900 rounded-2xl shadow-3xl max-w-md w-full`

## z-index 계층
- 10: 드롭다운
- 50: 모달
- 9999: 최상위 오버레이

## 참조 파일
- `tailwind.config.js`: 색상, 다크모드, 플러그인 설정
- `src/app.css`: `--cloo-*` 디자인 토큰 정의
