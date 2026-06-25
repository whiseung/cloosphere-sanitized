---
paths:
  - "src/lib/utils/**/*.ts"
  - "src/lib/utils/**/*.js"
---

# 프론트엔드 유틸리티 규칙

## 메인 유틸리티 (src/lib/utils/index.ts, 1360줄)

### 문자열/콘텐츠 처리
- `replaceTokens()`: 코드 블록 외부에서 `{{char}}`, `{{user}}`, `{{VIDEO_FILE_ID_*}}` 등 토큰 치환
- `sanitizeResponseContent()`: 특수 토큰 제거 + HTML 엔티티 이스케이프
- `processResponseContent()`: 공백 트림
- `removeDetails()`: `<details type="reasoning|code_interpreter|tool_calls">` 태그 제거
- `getCodeBlockContents()`: 마크다운 코드 블록에서 HTML/CSS/JS 추출

### 메시지/채팅 관리
- `convertMessagesToHistory()`: 플랫 메시지 배열 → parentId/childrenIds 트리 구조
- `createMessagesList()`: 히스토리 트리에서 특정 messageId까지 메시지 리스트 재귀 생성
- `convertOpenAIMessages()` / `convertOpenAIChats()`: OpenAI 채팅 포맷 임포트
- `validateChat()`: 채팅 구조 검증 (메시지 배열, 부모-자식 관계)
- `getImportOrigin()`: 임포트 소스 감지 (OpenAI vs WebUI — `mapping` 필드 유무)

### 템플릿 처리
- `promptTemplate()`: `{{CURRENT_DATETIME}}`, `{{USER_NAME}}`, `{{USER_LANGUAGE}}` 등 치환
- `titleGenerationTemplate()`: `{{prompt:start:N}}`, `{{prompt:end:N}}`, `{{prompt:middletruncate:N}}`
- `extractCurlyBraceWords()`: `{{word}}` 패턴 추출 (위치 정보 포함)

### 클립보드
- `copyToClipboard(text, formatted)`: Clipboard API + 폴백(execCommand)
  - `formatted=true`: 마크다운→HTML 변환 후 text/html + text/plain 동시 복사

### 날짜/시간
- dayjs + 플러그인 (relativeTime, isToday, isYesterday, localizedFormat)
- `formatDate()`: "Today at HH:MM" / "Yesterday at HH:MM" / "MM/DD/YYYY at HH:MM"
- `getTimeRange()`: 타임스탬프 분류 ("Today", "Yesterday", "Previous 7/30 days", 월, 년)

### 이미지/파일
- `compressImage(url, maxW, maxH)`: Canvas 기반 리사이즈
- `generateInitialsImage(name)`: 100x100px 이니셜 아바타 생성
- `calculateSHA256(file)`: Web Crypto API SHA-256
- `formatFileSize(size)`: 바이트 → "X.Y KB/MB/GB"

### 스트리밍
- `splitStream(splitOn)`: ReadableStream을 구분자로 분할하는 TransformStream (SSE 파싱용)

### OpenAPI 변환
- `convertOpenApiToToolPayload(spec)`: OpenAPI 3.x → LLM 도구 정의 변환
- `resolveSchema()`: `$ref` 재귀 해결 (순환 참조 처리)

## 코드 블록 처리 패턴
텍스트 가공 시 코드 블록을 플레이스홀더(`\u0000{index}\u0000`)로 치환 → 처리 → 복원

## 마크다운 확장 (src/lib/utils/marked/)

### extension.ts (94줄)
- `<details>` 커스텀 블록 파싱 (중첩 지원)
- `findMatchingClosingTag()`: 깊이 추적으로 정확한 닫기 태그 찾기

### katex-extension.ts (158줄)
- 수식 구분자: `$$...$$`, `\[...\]`, `$...$`, `\(...\)`, `\pu{...}`, `\ce{...}`
- `inlineKatex()` + `blockKatex()` 두 개의 marked 확장

## 클라우드 통합

### google-drive-picker.ts (212줄)
- OAuth2 (gsi/client) → Google Picker API → 파일 다운로드
- 설정: `/api/config` → `google_drive.{api_key, client_id}`
- Google Docs→text/plain, Sheets→text/csv, Presentations→text/plain 자동 변환

### onedrive-file-picker.ts (284줄)
- MSAL (`@azure/msal-browser`) → OneDrive 팝업 Picker → MessagePort 통신
- `openOneDrivePicker()` → `pickAndDownloadFile()` 편의 래퍼

### sharepoint-client.ts (349줄)
- Microsoft Graph API (Sites.Read.All, Files.Read.All 스코프)
- `getSites()` → `getDrives()` → `getItems()` → `downloadFile()` 계층 탐색
- 설정: `/api/config` → `sharepoint.{client_id, tenant_id, site_url}`

## 캐릭터 파서 (src/lib/utils/characters/index.ts, 197줄)
- `parseFile(file)`: JSON/PNG AI 캐릭터 파일 파싱
- PNG: tEXt 청크에서 "chara" 키워드 → base64 JSON 디코드 + CRC32 검증
- 4가지 포맷 지원: Text Generation, TavernAI, CharacterAI, CharacterAI History

## 트랜지션 (src/lib/utils/transitions/index.ts, 48줄)
- `flyAndScale(node, params)`: 수직 이동 + 스케일 결합 트랜지션
- 기본값: `{ y: -8, start: 0.95, duration: 200 }`, cubicOut 이징

## 인증 패턴 (클라우드 통합 공통)
- Silent 토큰 획득 시도 → 실패 시 팝업 폴백
- 토큰은 메모리에 캐시 (localStorage 아님)
- 설정은 `/api/config` 엔드포인트에서 로드 후 캐시

## 주요 의존성
```
dayjs, marked, highlight.js, katex, js-sha256, uuid(v4),
crc-32, @azure/msal-browser, svelte/easing
```

## 참조 파일
- `src/lib/utils/index.ts`: 메인 유틸리티 (1360줄)
- `src/lib/utils/marked/extension.ts`: details 블록 확장
- `src/lib/utils/marked/katex-extension.ts`: KaTeX 수식 확장
- `src/lib/utils/characters/index.ts`: AI 캐릭터 파일 파서
- `src/lib/utils/transitions/index.ts`: 커스텀 트랜지션
- `src/lib/utils/google-drive-picker.ts`: Google Drive 통합
- `src/lib/utils/onedrive-file-picker.ts`: OneDrive 통합
- `src/lib/utils/sharepoint-client.ts`: SharePoint 통합
