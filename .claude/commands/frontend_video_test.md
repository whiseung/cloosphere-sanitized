# Frontend E2E Video Test Command

Playwright Video MCP를 사용하여 프론트엔드 UI를 **스크린샷으로 검증한 후 동영상으로 녹화**합니다.

## 테스트 환경

- **Frontend**: `http://localhost:5173` (`npm run dev`)
- **Backend**: `http://localhost:8080`
- **Playwright Video MCP**: headless Chrome (no-sandbox), WebM 녹화
- **비디오 저장 경로**: `/tmp/playwright-videos/`

### 테스트 계정

| 이름 | Email | Password | 용도 |
|------|-------|----------|------|
| FrontAdmin | front_test@cloocus.com | Zmffnzjtm12#$ | 프론트엔드 E2E 테스트 전용 |

## 핵심 전략: 2-Pass 방식

이 스킬은 **2-Pass 방식**으로 동작합니다:

1. **Pass 1 (검증)**: `video_start` → 스크린샷/스냅샷으로 각 단계의 화면 상태를 확인하며 시나리오 검증
2. **Pass 2 (녹화)**: 검증된 시나리오를 `video_stop` → `video_start`로 새 세션을 시작하여 깔끔하게 녹화

> Pass 1에서 모든 화면 상태를 확인하고, 모달/팝업/에러 등을 처리하는 방법을 파악한 후,
> Pass 2에서는 검증된 액션만 빠르게 실행하여 자연스러운 비디오를 생성합니다.

## 실행 단계

### 0단계: 환경 확인

프론트엔드와 백엔드가 실행 중인지 확인합니다.

```bash
# 백엔드 확인
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health

# 프론트엔드 확인
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
```

- **200**: 정상 → 다음 단계 진행
- **그 외**: 사용자에게 서버 시작 요청

---

## Pass 1: 스크린샷 검증

### 1단계: 브라우저 시작 및 로그인

```
1. video_start → url: http://localhost:5173, width: 1440, height: 900
2. video_screenshot → 로그인 폼 확인
3. video_action으로 로그인
4. video_screenshot → 로그인 결과 확인
```

**로그인 video_action 코드:**
```javascript
await page.waitForSelector('input[type="email"], input[autocomplete="email"]', { timeout: 10000 });
await page.fill('input[type="email"], input[autocomplete="email"]', 'front_test@cloocus.com');
await page.fill('input[type="password"]', 'Zmffnzjtm12#$');
await page.evaluate(() => {
  document.querySelector('button[type="submit"]').click();
});
await page.waitForTimeout(5000);
```

### 2단계: 모달/팝업 확인 및 정리

로그인 후 반드시 `video_screenshot`으로 현재 화면 상태를 확인합니다.

```
1. video_screenshot → 현재 화면 확인
2. 모달/팝업이 있으면 → video_snapshot으로 DOM 구조 파악
3. video_action으로 닫기
4. video_screenshot → 정리 완료 확인
```

**팝업 닫기 전략:**
```javascript
// 방법 1: X 버튼 찾기
const closeBtn = await page.$('button[aria-label="Close"], button[aria-label="닫기"], dialog button:first-child');
if (closeBtn) {
  await closeBtn.click();
  await page.waitForTimeout(1000);
}

// 방법 2: ESC 키
await page.keyboard.press('Escape');
await page.waitForTimeout(500);

// 방법 3: 배경 클릭 (모달 backdrop)
await page.evaluate(() => {
  const backdrop = document.querySelector('.modal-backdrop, [data-modal-backdrop]');
  if (backdrop) backdrop.click();
});
```

### 3단계: 테스트 시나리오 검증

각 페이지/기능별로 스크린샷과 스냅샷을 활용하여 시나리오를 검증합니다.

```
매 단계마다:
1. video_action → 액션 수행
2. video_screenshot → 결과 시각적 확인
3. 문제 있으면 → video_snapshot으로 DOM 구조 확인 → 수정
4. 문제 없으면 → 다음 단계
```

#### 세션 작업 분석

현재 대화에서 작업한 프론트엔드 변경 내용을 분석하여 테스트 대상을 파악합니다.
인자로 특정 테스트 시나리오가 전달되면 그에 따라 테스트합니다.

#### 주요 페이지 경로

| 페이지 | 경로 | 설명 |
|--------|------|------|
| 메인 채팅 | `/` | 채팅 입력, 모델 선택 |
| 워크스페이스 | `/workspace` | Agents, Knowledge, Database 등 |
| 관리자 설정 | `/admin/settings` | 14개 탭 설정 |
| 관리자 사용자 | `/admin` | 사용자 관리 |
| 채널 | `/channels` | 메시징 |

### 4단계: Pass 1 종료 및 검증 결과 정리

```
video_stop → Pass 1 비디오 종료 (이 비디오는 참고용, 최종 산출물 아님)
```

검증된 시나리오를 정리합니다:
- 각 단계별 어떤 액션이 필요한지
- 모달/팝업 처리가 필요한 위치
- 페이지 로딩 대기 시간
- 발견된 이슈 및 우회 방법

---

## Pass 2: 최종 비디오 녹화

### 5단계: 새 녹화 세션 시작

```
video_start → url: http://localhost:5173, width: 1440, height: 900
```

### 6단계: 검증된 시나리오 실행

Pass 1에서 검증된 액션만 순서대로 실행합니다. 각 액션 사이에 적절한 대기 시간을 넣어 비디오가 자연스럽게 녹화되도록 합니다.

**핵심 원칙:**
- 매 액션마다 `video_screenshot`으로 확인 — **보면서 녹화**
- 예상과 다른 화면이 나오면 즉시 대응 (모달 닫기, 대기 시간 추가 등)
- `wait_after`를 2000~3000ms로 넉넉히 설정하여 장면이 자연스럽게 전환

**로그인:**
```javascript
await page.waitForSelector('input[type="email"], input[autocomplete="email"]', { timeout: 10000 });
await page.fill('input[type="email"], input[autocomplete="email"]', 'front_test@cloocus.com');
await page.fill('input[type="password"]', 'Zmffnzjtm12#$');
await page.evaluate(() => {
  document.querySelector('button[type="submit"]').click();
});
await page.waitForTimeout(5000);
```

**모달 정리 (Pass 1에서 파악한 방법 적용):**
```javascript
// Pass 1에서 확인한 셀렉터로 모달 닫기
await page.keyboard.press('Escape');
await page.waitForTimeout(1000);
```

**페이지 네비게이션:**
```
video_navigate → 대상 페이지
video_screenshot → 화면 확인
video_action → 필요한 인터랙션 수행 (wait_after: 2000~3000)
video_screenshot → 결과 확인
```

### 7단계: 녹화 종료

```
video_stop → 최종 비디오 파일 경로 반환
```

### 8단계: 결과 보고

```bash
# 비디오 파일 확인
ls -lh /tmp/playwright-videos/*.webm
```

```markdown
## Frontend E2E 비디오 테스트 결과

| 항목 | 값 |
|------|-----|
| 비디오 파일 | `/tmp/playwright-videos/{filename}.webm` |
| 포맷 | WebM |
| 해상도 | 1440x900 |
| 녹화 내용 | (시나리오 요약) |

### 녹화된 시나리오
1. 로그인
2. (테스트한 페이지/기능 목록)

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

## 기존 MCP와의 관계

- `playwright` MCP (기존): 스크린샷, 스냅샷, DOM 검사 등 **정적 테스트**용 (`/frontend_test`)
- `playwright-video` MCP (신규): **스크린샷 검증 + 동영상 녹화** (`/frontend_video_test`)
- 두 MCP는 독립적으로 동작하며 동시 사용 가능

## 주의사항

1. **2-Pass 필수**: Pass 1(검증) 없이 바로 녹화하면 blind 상태가 되어 모달/에러를 놓칠 수 있음
2. **보면서 녹화**: Pass 2에서도 매 단계 `video_screenshot`으로 화면 확인하며 진행
3. **모달/팝업 정리**: 로그인 후 반드시 스크린샷으로 확인하고 팝업을 닫은 후 진행
4. **wait_after**: 각 `video_action` 호출 시 `wait_after`를 적절히 설정 (기본 1000ms, 녹화 시 2000~3000ms 권장)
5. **자연스러운 대기**: 페이지 전환, 폼 입력, 버튼 클릭 사이에 충분한 대기 시간
6. **viewport 밖 요소**: `page.evaluate`로 직접 DOM 클릭하여 우회
7. **로딩 대기**: SPA이므로 페이지 전환 후 `waitForTimeout(3000)` 또는 특정 요소 대기 필요
8. **비디오 정리**: 테스트 완료 후 `/tmp/playwright-videos/` 내 .webm 파일 정리 필요
9. **headless 제약**: 파일 업로드, 클립보드 등 일부 브라우저 기능 제한 있음
10. **비디오 포맷**: WebM 형식으로 저장됨 (브라우저, VLC 등에서 재생 가능)
