# Demo Video Recording Command

사용자가 제공한 시나리오에 따라 Cloosphere 프론트엔드 데모 영상을 녹화합니다.

## 사용법

```
/demo_video 가드레일에서 이메일 PII를 감지하고 Redact하는 시나리오
/demo_video 에이전트 생성 후 채팅에서 사용하는 전체 흐름
/demo_video Knowledge에 문서 업로드 후 RAG 채팅
```

인자로 시나리오 설명을 전달하면, 해당 시나리오대로 데모 영상을 녹화합니다.

## 테스트 환경

- **Frontend**: `http://localhost:5173` (`npm run dev`)
- **Backend**: `http://localhost:8080`
- **Playwright Video MCP**: headless Chrome (no-sandbox), WebM 녹화
- **비디오 저장 경로**: `/tmp/playwright-videos/`

### 테스트 계정

| 이름 | Email | Password | 용도 |
|------|-------|----------|------|
| FrontAdmin | front_test@cloocus.com | Zmffnzjtm12#$ | 프론트엔드 E2E 테스트 전용 |

## 주요 페이지 경로

| 페이지 | 경로 | 설명 |
|--------|------|------|
| 메인 채팅 | `/` | 채팅 입력, 모델 선택 |
| 워크스페이스 - Agents | `/workspace/agents` | 에이전트 목록/생성/편집 |
| 워크스페이스 - Knowledge | `/workspace/knowledge` | Knowledge Base 관리 |
| 워크스페이스 - Database | `/workspace/database` | DbSphere 연결 관리 |
| 워크스페이스 - Flows | `/workspace/flows` | 플로우 자동화 |
| 워크스페이스 - Guardrails | `/workspace/guardrails` | 가드레일 설정 |
| 워크스페이스 - Glossary | `/workspace/glossary` | 용어집 |
| 워크스페이스 - Prompts | `/workspace/prompts` | 프롬프트 템플릿 |
| 워크스페이스 - Tools | `/workspace/tools` | 도구 관리 |
| 관리자 설정 | `/admin/settings` | 14개 탭 설정 |
| 관리자 사용자 | `/admin` | 사용자 관리 |
| 평가 | `/admin/evaluations` | 평가/트레이싱/리더보드 |
| 모니터링 | `/admin/monitoring` | 사용량 모니터링 |
| 채널 | `/channels` | 메시징 |
| 플레이그라운드 | `/playground` | 모델 테스트 |

## 핵심 전략: 2-Pass 방식

### Pass 1 (검증) → Pass 2 (녹화)

1. **Pass 1**: 로그인 후 시나리오를 스크린샷으로 검증하며 실행. 모달/팝업 처리 방법, 셀렉터, 대기 시간 등을 파악.
2. **Pass 2**: 검증된 시나리오를 새 세션에서 깔끔하게 녹화. 로그인은 빠르게 처리하고, 시나리오 시작점부터 본격 녹화.

## 실행 단계

### 0단계: 환경 확인

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
```

- **200**: 정상 → 다음 단계 진행
- **그 외**: 사용자에게 서버 시작 요청

### 1단계: 시나리오 분석

인자로 전달된 시나리오를 분석하여 실행 계획을 세웁니다:
- 어떤 페이지에 방문해야 하는지
- 어떤 UI 인터랙션이 필요한지 (클릭, 입력, 선택 등)
- 어떤 순서로 진행해야 하는지
- 데이터 생성/수정이 필요한지 (원래 상태 복원 필요 여부)

---

### Pass 1: 스크린샷 검증

### 2단계: 브라우저 시작 및 로그인

```
1. video_start → url: http://localhost:5173, width: 1440, height: 900
2. video_action으로 로그인 + 모달 닫기
```

**로그인 + 모달 정리 코드:**
```javascript
// Get started 클릭 (랜딩 페이지인 경우)
const getStarted = await page.$('text=Get started');
if (getStarted) {
  await getStarted.click();
  await page.waitForTimeout(1000);
}

// 로그인
await page.waitForSelector('input[type="email"], input[autocomplete="email"]', { timeout: 10000 });
await page.fill('input[type="email"], input[autocomplete="email"]', 'front_test@cloocus.com');
await page.fill('input[type="password"]', 'Zmffnzjtm12#$');
await page.evaluate(() => document.querySelector('button[type="submit"]').click());
await page.waitForTimeout(5000);

// What's New 모달 닫기
const okBtn = await page.$('text=Okay, Let\'s Go!');
if (okBtn) {
  await okBtn.click();
  await page.waitForTimeout(1000);
}
```

### 3단계: 시나리오 검증

시나리오의 각 단계를 실행하면서 스크린샷으로 화면 상태를 확인합니다.

```
매 단계마다:
1. video_action 또는 video_navigate → 액션 수행
2. video_screenshot → 결과 시각적 확인
3. 문제 있으면 → video_snapshot으로 DOM 구조 확인 → 해결 방법 파악
4. 문제 없으면 → 다음 단계
```

**중요 확인 사항:**
- 모달/팝업이 떠있는지
- 버튼/입력 필드의 정확한 셀렉터
- 페이지 로딩 완료 여부
- API 호출 결과 (성공/실패)

### 4단계: Pass 1 종료

```
video_stop → Pass 1 비디오 종료 (참고용, 삭제 가능)
```

검증 결과를 정리:
- 각 단계별 필요한 액션과 셀렉터
- 모달/팝업 처리 위치와 방법
- 적절한 대기 시간
- 발견된 이슈 및 우회 방법

---

### Pass 2: 최종 비디오 녹화

### 5단계: 새 녹화 세션

```
video_start → url: http://localhost:5173, width: 1440, height: 900
```

### 6단계: 로그인 (빠르게 처리)

로그인과 모달 닫기를 하나의 `video_action`에서 빠르게 처리합니다.
비디오 앞부분에 로그인이 잠깐 포함되지만, 핵심 시나리오가 메인이 됩니다.

```javascript
// 빠르게 로그인
const getStarted = await page.$('text=Get started');
if (getStarted) {
  await getStarted.click();
  await page.waitForTimeout(1000);
}
await page.waitForSelector('input[type="email"], input[autocomplete="email"]', { timeout: 10000 });
await page.fill('input[type="email"], input[autocomplete="email"]', 'front_test@cloocus.com');
await page.fill('input[type="password"]', 'Zmffnzjtm12#$');
await page.evaluate(() => document.querySelector('button[type="submit"]').click());
await page.waitForTimeout(5000);

// What's New 모달 닫기
const okBtn = await page.$('text=Okay, Let\'s Go!');
if (okBtn) {
  await okBtn.click();
  await page.waitForTimeout(1000);
}

// 시나리오 시작 페이지로 이동
await page.goto('http://localhost:5173/{시나리오_시작_경로}', { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
```

### 7단계: 시나리오 실행 (본격 녹화)

Pass 1에서 검증된 액션을 순서대로 실행합니다.

**녹화 원칙:**
- 매 단계 `video_screenshot`으로 화면 확인 — **보면서 녹화**
- 예상과 다른 화면이면 즉시 대응
- 각 액션의 `wait_after`를 2000~3000ms로 넉넉히 설정
- 타이핑은 `{ delay: 50 }` 옵션으로 자연스럽게
- 결과 화면은 3~4초 충분히 보여주기

**인터랙션 패턴:**

```javascript
// 페이지 이동 후
await page.waitForTimeout(2500);  // 페이지 충분히 보여주기

// 버튼 클릭
await page.click('셀렉터');
await page.waitForTimeout(2000);  // 결과 대기

// 폼 입력 (타이핑 효과)
await page.click('input셀렉터');
await page.waitForTimeout(500);
await page.keyboard.type('입력 텍스트', { delay: 50 });
await page.waitForTimeout(1500);

// 채팅 입력 (TipTap contenteditable — textarea 아님!)
await page.click('#chat-input');
await page.waitForTimeout(500);
await page.keyboard.type('질문 텍스트', { delay: 80 });
await page.waitForTimeout(1000);
await page.keyboard.press('Enter');  // 전송

// <select> 네이티브 요소 (Base Model, DB Type 등)
const selects = await page.$$('select');
await selects[0].selectOption('gpt-5.2');

// 모델 셀렉터에서 에이전트 선택 (하나만)
await page.evaluate(() => {  // 상단 모델명 버튼 클릭
  const buttons = document.querySelectorAll('button');
  for (const b of buttons) {
    const rect = b.getBoundingClientRect();
    if (rect.y < 40 && rect.x < 200 && rect.x > 60 && rect.width > 50) { b.click(); break; }
  }
});
await page.waitForTimeout(1500);
await page.keyboard.type('에이전트명', { delay: 80 });
await page.waitForTimeout(1000);
await page.click('text=에이전트명');
await page.waitForTimeout(2000);
// ⚠️ 기본 모델(Cloosphere)이 자동 추가됨 → 반드시 제거
const removeBtn = await page.$('button[aria-label="Remove Model"]');
if (removeBtn) { await removeBtn.click(); await page.waitForTimeout(2000); }

// 파일 업로드 (headless 전용 — filechooser 이벤트 사용)
const [fileChooser] = await Promise.all([
  page.waitForEvent('filechooser', { timeout: 5000 }),
  page.click('text=Upload files')
]);
await fileChooser.setFiles(['/path/to/file1.pdf', '/path/to/file2.pdf']);

// 스크롤 — window.scrollTo는 워크스페이스에서 안 먹힘, scrollIntoView 사용
await page.evaluate(() => {
  const elements = document.querySelectorAll('div, h3, h4, span');
  for (const el of elements) {
    if (el.textContent.trim() === 'Knowledge' && el.getBoundingClientRect().y > 800) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      break;
    }
  }
});

// 결과 화면
await page.waitForTimeout(4000);  // 결과를 충분히 보여줌
```

**주요 셀렉터 레퍼런스:**

| 요소 | 셀렉터 | 비고 |
|------|--------|------|
| 채팅 입력 | `#chat-input` | TipTap contenteditable div |
| KB 생성 | `button[aria-label="Create Knowledge"]` | |
| KB 이름 | `input[placeholder="Name your knowledge base"]` | |
| KB 파일 추가 | `div[aria-label="Add Content"] button` | 드롭다운 열림 |
| 에이전트 생성 | `/workspace/agents/create` | `<a>` 태그, 직접 navigate 추천 |
| 에이전트 이름 | `input[placeholder="Model Name"]` | |
| 에이전트 설명 | `textarea[placeholder="Add a short description about what this model does"]` | |
| Base Model | 첫 번째 `<select>` | `selectOption()` 사용 |
| 모델 검색 | `input[placeholder="Search a model"]` | |
| 두 번째 모델 제거 | `button[aria-label="Remove Model"]` | 에이전트 선택 시 자동 추가됨 |
| Save & Create | `button:has-text("Save & Create")` | scrollIntoView 필요 |

### 7.5단계: 액션별 상태 검증 (Pass 2 필수)

Pass 2 녹화 중 **모든 주요 액션 후** 아래 검증을 수행합니다. 검증 실패 시 즉시 대응하여 재녹화를 방지합니다.

**검증 방법 — `video_action`으로 DOM 상태 확인:**
```javascript
// 페이지 이동 후 — 올바른 페이지에 도착했는지 확인
const url = page.url();
const title = await page.evaluate(() => document.title);
const hasError = await page.$('text=Backend Required');
if (hasError) throw new Error('Backend 연결 끊김!');

// 모달/토스트 확인 — 예상치 못한 팝업이 떠있는지
const modal = await page.$('[role="dialog"], .modal');
if (modal) {
  // 모달 닫기 시도
  const closeBtn = await page.$('button[aria-label="Close"], text=OK, text=Cancel');
  if (closeBtn) await closeBtn.click();
}

// 로딩 완료 확인 — 스피너가 사라졌는지
await page.waitForSelector('.spinner, [class*="loading"]', { state: 'hidden', timeout: 10000 }).catch(() => {});
```

**주요 검증 체크포인트:**

| 시점 | 검증 내용 | 실패 시 대응 |
|------|----------|-------------|
| 로그인 후 | URL이 `/`이고 모델 셀렉터 보이는지 | 재로그인 |
| 페이지 이동 후 | "Backend Required" 에러 없는지 | video_stop 후 사용자에게 서버 확인 요청 |
| 폼 입력 후 | 입력값이 실제로 들어갔는지 (`page.inputValue()`) | 재입력 |
| 버튼 클릭 후 | 토스트/모달/페이지 전환 등 예상 결과 발생했는지 | 재클릭 또는 다른 셀렉터 시도 |
| 에이전트 선택 후 | 상단에 에이전트 이름 표시 + Cloosphere 자동 추가 확인 | Remove Model 실행 |
| 채팅 전송 후 | "Generating...", "Starting Agent..." 등 응답 시작 확인 | 재전송 |
| 응답 완료 후 | 응답 텍스트 존재 + "Send a Message" 입력창 활성화 확인 | 추가 대기 |

**응답 완료 대기 — 타임아웃 기반이 아닌 상태 기반:**
```javascript
// BAD: 고정 시간 대기 (응답이 일찍/늦게 끝나면 문제)
await page.waitForTimeout(50000);

// GOOD: 응답 완료 상태를 폴링하여 확인
for (let i = 0; i < 120; i++) {  // 최대 2분
  await page.waitForTimeout(1000);
  const isGenerating = await page.$('text=Generating final answer');
  const isPreparing = await page.$('text=Preparing context');
  const isStarting = await page.$('text=Starting Agent');
  if (!isGenerating && !isPreparing && !isStarting) {
    // 응답 완료 확인
    await page.waitForTimeout(2000);  // 렌더링 여유
    break;
  }
}
```

### 8단계: 원래 상태 복원 (필요 시)

시나리오에서 데이터를 생성/수정/삭제했다면, 원래 상태로 복원합니다.
- 생성한 항목 삭제
- 변경한 설정 원복
- 녹화 종료 후 API로 정리 (리소스 정리 API 참고)

### 9단계: 녹화 종료

```
video_stop → 최종 비디오 파일 경로 반환
```

### 10단계: 녹화 결과 검증

녹화가 끝난 직후, 영상 품질을 자동 검증합니다.

**10.1: 1초 간격 프레임 추출 + 이상 감지**
```
1. video_info로 총 길이 확인
2. 1초 간격으로 전체 프레임 추출 (video_frame × N)
3. 모든 프레임을 Read tool로 시각 확인
4. 아래 이상 패턴을 감지:
```

| 이상 패턴 | 감지 방법 | 의미 |
|-----------|----------|------|
| 빈 화면 / 흰 화면 | 프레임이 전부 흰색 또는 로딩 스피너만 보임 | 페이지 로드 실패 |
| "Backend Required" | 에러 페이지 텍스트 | 서버 연결 끊김 — 재녹화 필요 |
| 로그인 화면 잔존 | 이메일/비밀번호 입력 폼 | 로그인 트림 필요 |
| 사이드바 열림 | 좌측에 채팅 히스토리 노출 | 사이드바 닫기 누락 |
| 모델 2개 선택됨 | 상단에 두 줄로 모델명 표시 | Cloosphere 제거 누락 |
| 응답 미완료 | "Generating...", 스피너 아이콘 | 대기 시간 부족 — 추가 대기 후 재녹화 |
| 의미 없는 반복 구간 | 연속 3+초 동일 화면 | 편집 시 제거 대상 |

**10.2: 검증 판정**
- **PASS**: 이상 패턴 없음 → 편집 단계로 진행
- **WARN**: 트림/편집으로 해결 가능한 이슈 → 편집 시 처리
- **FAIL**: 서버 에러, 응답 미완료 등 → 재녹화 필요

### 11단계: 결과 보고

```bash
ls -lh /tmp/playwright-videos/{파일명}.webm
```

```markdown
## 데모 비디오 결과

| 항목 | 값 |
|------|-----|
| 비디오 파일 | `/tmp/playwright-videos/{filename}.webm` |
| 포맷 | WebM |
| 크기 | {size} |
| 해상도 | 1440x900 |

### 녹화된 시나리오
1. (시나리오 단계 요약)

**발견된 이슈:** (있으면 기술)
```

---

## Playwright Video MCP 도구 요약

| 도구 | 용도 | 비고 |
|------|------|------|
| `video_start` | 녹화 시작 + URL 이동 | url, width, height 파라미터 |
| `video_navigate` | 녹화 중 URL 이동 | |
| `video_action` | 녹화 중 Playwright 코드 실행 | `page` 변수 사용, wait_after로 대기 |
| `video_screenshot` | 현재 화면 스크린샷 (이미지 반환) | full_page 옵션 지원 |
| `video_snapshot` | 접근성 스냅샷 (텍스트 반환) | DOM 구조 파악용 |
| `video_stop` | 녹화 종료 + .webm 저장 | 파일 경로 반환 |

## 주의사항

1. **2-Pass 필수**: Pass 1(검증) 없이 바로 녹화하면 blind 상태가 되어 모달/에러를 놓칠 수 있음
2. **보면서 녹화**: Pass 2에서도 매 단계 `video_screenshot`으로 화면 확인하며 진행
3. **모달/팝업 정리**: 로그인 후 "What's New" 등 모달이 뜰 수 있음 → 반드시 확인 후 닫기
4. **로그인 포함**: `video_start`가 매번 새 브라우저를 띄우므로 로그인이 필수. 빠르게 처리하여 비디오 앞부분에만 포함
5. **자연스러운 대기**: 페이지 전환/폼 입력/버튼 클릭 사이에 2~3초 대기
6. **타이핑 효과**: `page.keyboard.type(text, { delay: 50 })` 사용
7. **viewport 밖 요소**: `page.evaluate`로 직접 DOM 클릭하거나 `scrollIntoView()` 사용
8. **원래 상태 복원**: 데이터 변경 시나리오는 녹화 끝에 API로 정리 (아래 정리 API 참고)
9. **비디오 정리**: `/tmp/playwright-videos/` 내 불필요한 .webm 파일 정리 필요
10. **headless 파일 업로드**: `page.click('text=Upload files')` 대신 `filechooser` 이벤트 + `setInputFiles` 사용
11. **비디오 포맷**: WebM 형식 (브라우저, VLC 등에서 재생 가능)
12. **멀티모델 자동 추가**: 에이전트 선택 시 Cloosphere가 두 번째 모델로 자동 추가됨 → `button[aria-label="Remove Model"]`로 제거 필수
13. **채팅 입력은 TipTap**: `#chat-input`은 contenteditable div (textarea 아님). `page.click('#chat-input')` + `page.keyboard.type()` 사용
14. **워크스페이스 생성 버튼**: Agents/Knowledge 등의 `+` 버튼이 `<a>` 태그인 경우 있음 → 직접 URL navigate 추천 (예: `/workspace/agents/create`)
15. **<select> 요소**: Base Model, DB Type 등은 네이티브 `<select>` → `selectOption('value')` 사용
16. **스크롤**: 워크스페이스 페이지에서 `window.scrollTo`가 안 먹히는 경우 있음 → `el.scrollIntoView({ behavior: 'smooth', block: 'center' })` 사용

## 리소스 정리 API

녹화 후 생성된 에이전트/KB/채팅을 API로 정리합니다:

```bash
TOKEN="eyJhbGci..."

# 에이전트 삭제
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/models/model/delete?id={model_id}"

# Knowledge Base 삭제
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/knowledge/{kb_id}/delete"

# 채팅 삭제
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/chats/{chat_id}"
```
