---
paths:
  - "src/lib/i18n/**/*"
  - "src/lib/i18n/locales/**/*.json"
---

# 국제화(i18n) 시스템 규칙

## 설정 (src/lib/i18n/index.ts)
- i18next + i18next-resources-to-backend + i18next-browser-languagedetector
- 동적 로딩: `import(\`./locales/${language}/${namespace}.json\`)`
- 기본 namespace: 'translation'
- Svelte 스토어 래퍼: `createI18nStore(i18next)` → writable

## 사용법
```svelte
<script lang="ts">
  import { getContext } from 'svelte';
  const i18n = getContext('i18n');
</script>

{$i18n.t('Save')}
{$i18n.t('Hello, {{name}}', { name: userName })}
```

## 언어 감지 순서
1. querystring (`?lng=ko`)
2. localStorage
3. navigator (브라우저)

## 언어 변경
```typescript
changeLanguage(lang)  // → document.documentElement.setAttribute('lang', lang)
```

## 번역 파일 구조
- 위치: `src/lib/i18n/locales/{lang}/translation.json`
- 50+ 지원 언어
- 주요: `en-US` (기본), `ko-KR`
- 키: 영어 원문 그대로 사용 (`"Save": "저장"`)

## 새 키 추가
1. 컴포넌트에서 `$i18n.t('New Key')` 사용
2. `en-US/translation.json`에 키 추가 (값 = 키와 동일)
3. `ko-KR/translation.json`에 번역 추가
4. **`npm run i18n:parse` 실행 금지** — 다른 로케일 파일들이 꼬임
5. Python으로 JSON 수정 시: `json.dump(ensure_ascii=False, indent='\t')` + `\n` 로 저장

## 참조 파일
- `i18n/index.ts`: i18next 설정, createI18nStore
- `i18n/locales/en-US/translation.json`: 영어 번역
- `i18n/locales/ko-KR/translation.json`: 한국어 번역
