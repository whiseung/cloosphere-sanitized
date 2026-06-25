# Guide Screenshot Command

가이드 문서에 삽입할 UI 스크린샷을 Playwright MCP로 촬영하고, 가이드의 `<!-- 스크린샷: ... -->` 자리표시자를 실제 이미지로 교체합니다.

## 사용법

```
/guide_screenshot {기능명}
```

**인자가 없으면** 아래 기능 목록을 보여주고 사용자에게 선택을 요청합니다.

## 기능 매핑 테이블

| 기능명 | 페이지 경로 | 촬영 항목 | 이미지 파일명 | 가이드 파일 |
|--------|------------|----------|-------------|------------|
| `login` | `/auth` | 로그인 폼 | `0131134011883.png` | `getting-started.md` |
| `main` | `/` | 메인 채팅 화면 | `2026-01-31-13-33-59.png` | `README.md`, `getting-started.md`, `chat.md` |
| `chat` | `/` → 채팅 전송 | 모델선택, 채팅응답, 파일첨부, #태그, 설정모달 등 | `0131134403207.png` 외 다수 | `chat.md`, `getting-started.md` |
| `agents` | `/workspace/agents` | 목록, 편집폼, 지식연결, 기능설정 | `agents-list.png`, `agents-edit.png` 등 | `workspace/agents.md` |
| `flows` | `/workspace/flows` | 목록, 캔버스+노드팔레트 | `flows-list.png`, `flows-canvas.png` | `workspace/flows.md` |
| `knowledge` | `/workspace/knowledge` | 목록, 상세(문서목록, 도구설명) | `knowledge-list.png`, `knowledge-detail.png` | `workspace/knowledge.md` |
| `database` | `/workspace/database` | 목록, 상세(연결정보, 테이블) | `database-list.png`, `database-detail.png` | `workspace/database.md` |
| `glossary` | `/workspace/glossary` | 목록, 상세(용어추가, 목록) | `glossary-list.png`, `glossary-detail.png` | `workspace/glossary.md` |
| `guardrails` | `/workspace/guardrails` | 목록, 편집(PII, LLM Judge) | `guardrails-list.png`, `guardrails-detail.png` | `workspace/guardrails.md` |
| `prompts` | `/workspace/prompts` | 목록 | `prompts-list.png` | `workspace/prompts.md` |
| `tools` | `/workspace/tools` | 목록 | `tools-list.png` | `workspace/tools.md` |
| `schedules` | `/schedules` | 목록 | `schedules-list.png` | `schedules.md` |
| `admin-users` | `/admin` | 사용자 목록, 그룹, 조직, 문의 | `0131133819373.png` | `admin/users.md` |
| `admin-settings` | `/admin/settings` | 일반, 연결, 모델 등 탭별 | `admin-settings.png` 외 | `admin/settings.md` |
| `admin-monitoring` | `/admin/monitoring` | 감사로그, 사용량 대시보드 등 탭별 | `admin-monitoring.png` 외 | `admin/monitoring.md` |

## 실행 단계

### 0단계: 환경 확인 및 브라우저 준비

```
1. curl로 localhost:5173, localhost:8080 확인
2. browser_resize(1440, 900)
3. JWT 토큰으로 로그인 (localStorage 주입)
   - 토큰: <REDACTED>
4. 한국어 설정 확인 (설정 → 언어 → Korean)
```

**로그인 코드:**
```js
async (page) => {
  await page.evaluate(() => {
    localStorage.setItem('token', '<REDACTED>');
  });
  await page.goto('http://localhost:5173/');
  await page.waitForTimeout(2000);
}
```

### 1단계: 페이지 네비게이션 및 촬영

기능명에 따라 해당 페이지로 이동하여 스크린샷을 촬영합니다.

#### 촬영 기법

**페이지 로드 후 대기:**
```js
await page.waitForTimeout(2000); // 기본 렌더링 대기
```

**채팅 응답 완료 대기:**
```js
async (page) => {
  await page.waitForFunction(() => {
    const stopBtn = document.querySelector('[aria-label="Stop"]');
    return !stopBtn || stopBtn.offsetParent === null;
  }, { timeout: 120000 });
  await page.waitForTimeout(2000);
}
```

**모달/드로어 오픈 후 대기:**
```
browser_click → 트리거 클릭
browser_wait_for → time: 0.5 (애니메이션 완료)
```

**전체 화면 스크린샷:**
```
browser_take_screenshot(type: "png", filename: "guide/images/{파일명}.png")
```

**특정 요소 크롭:**
```
browser_take_screenshot(type: "png", ref: "{ref}", element: "{설명}", filename: "guide/images/{파일명}.png")
```

**Playwright locator로 크롭:**
```js
async (page) => {
  const element = page.locator('.target-class');
  await element.screenshot({ path: 'guide/images/{파일명}.png' });
}
```

### 2단계: 가이드 문서에 이미지 삽입

촬영한 이미지를 가이드 문서의 자리표시자와 교체합니다.

**자리표시자 형식:**
```markdown
<!-- 스크린샷: {설명}
     파일명: images/{파일명}.png
-->
```

**교체 결과:**
```markdown
![{alt텍스트}]({상대경로})
```

**상대경로 규칙:**
- `guide/ko/*.md` → `../images/{파일명}.png`
- `guide/ko/workspace/*.md`, `guide/ko/admin/*.md` → `../../images/{파일명}.png`
- `guide/en/` 도 동일 구조

**ko/en 동시 반영**: 한국어 가이드에서 교체한 자리표시자를 영어 가이드에서도 동일하게 교체합니다.

### 3단계: Docsify 검증

```
browser_navigate → http://localhost:5173/guide/index.html#/{가이드경로}
browser_evaluate로 이미지 로드 상태 확인:
```
```js
() => {
  const imgs = document.querySelectorAll('article img');
  return Array.from(imgs).map(img => ({
    src: img.src, alt: img.alt,
    naturalWidth: img.naturalWidth,
    displayed: img.offsetWidth > 0
  }));
}
```

### 4단계: 결과 보고

```markdown
## 스크린샷 촬영 결과

| 이미지 | 파일명 | 상태 | Docsify |
|--------|--------|------|---------|
| 에이전트 목록 | agents-list.png | OK | OK |
| 에이전트 편집 | agents-edit.png | OK | OK |
| ... | ... | ... | ... |

**가이드 수정:** {n}개 자리표시자 → 실제 이미지로 교체
**남은 자리표시자:** {m}개
```

## 기능별 촬영 시나리오

### login
1. `/auth` 접속 (로그아웃 상태)
2. 로그인 폼 스크린샷

### main
1. `/` 접속 (로그인 상태)
2. 메인 화면 전체 스크린샷

### chat
1. `/` 접속
2. 모델 드롭다운 열기 → 스크린샷
3. 메시지 전송 → 응답 완료 대기 → 스크린샷
4. + 버튼 (파일 첨부) 클릭 → 스크린샷
5. `#` 입력 → 지식기반 태그 검색 → 스크린샷
6. 응답 하단 버튼 크롭 → 스크린샷
7. 음성 버튼 크롭 → 스크린샷
8. 사이드바 열기 → 스크린샷
9. 설정 모달 열기 → 스크린샷

### agents
1. `/workspace/agents` → 목록 스크린샷
2. 에이전트 편집 클릭 → 상단 폼 스크린샷
3. 스크롤 → 지식/DB/도구/가드레일 섹션 스크린샷
4. 스크롤 → 자동평가/기능 설정 스크린샷

### flows
1. `/workspace/flows` → 목록 스크린샷
2. 플로우 클릭 → 캔버스+노드 팔레트 스크린샷

### knowledge
1. `/workspace/knowledge` → 목록 스크린샷
2. 지식기반 클릭 → 상세(문서목록, 도구설명) 스크린샷

### database
1. `/workspace/database` → 목록 스크린샷
2. DB 클릭 → 상세(연결정보, 테이블) 스크린샷

### glossary
1. `/workspace/glossary` → 목록 스크린샷
2. 용어사전 클릭 → 상세(용어추가, 목록) 스크린샷

### guardrails
1. `/workspace/guardrails` → 목록 스크린샷
2. 가드레일 클릭 → 편집(PII유형, LLM Judge) 스크린샷

### prompts
1. `/workspace/prompts` → 목록 스크린샷

### tools
1. `/workspace/tools` → 목록 스크린샷

### schedules
1. `/schedules` → 목록 스크린샷

### admin-users
1. `/admin` → 사용자 목록 스크린샷
2. 그룹 탭 클릭 → 스크린샷
3. 조직 탭 클릭 → 스크린샷

### admin-settings
1. `/admin/settings` → 일반 탭 스크린샷
2. 연결 탭 클릭 → 스크린샷
3. 모델 탭 클릭 → 스크린샷
4. 문서 탭 클릭 → 스크린샷
5. 필요시 추가 탭 순회

### admin-monitoring
1. `/admin/monitoring` → 감사 로그 탭 스크린샷
2. 사용량 탭 클릭 → 스크린샷
3. 가드레일 로그 탭 클릭 → 스크린샷
4. 대화 로그 탭 클릭 → 스크린샷

## 이미지 저장 규칙

- **저장 위치**: `guide/images/`
- **파일명**: 기능을 알 수 있는 서술적 이름 사용 (예: `agents-list.png`, `flows-canvas.png`)
- **기존 파일명**: getting-started/chat/README에서 참조하는 기존 숫자 파일명(`0131134011883.png` 등)은 덮어쓰기
- **형식**: PNG
- **해상도**: 1440x900 viewport 기준

## 주의사항

1. **한국어 UI**: 반드시 한국어 설정으로 촬영 (설정 → 언어 → Korean)
2. **렌더링 대기**: 페이지 로드 후 최소 2초 대기, 모달/애니메이션은 0.5초 추가
3. **민감정보**: 비밀번호, API키가 보이는 화면은 주의 (DB 상세 등)
4. **촬영 검증**: `browser_take_screenshot` 후 이미지를 시각적으로 확인하여 빈 화면/로딩 중이 아닌지 검증
5. **ko/en 동시 반영**: 자리표시자 교체 시 한국어/영어 가이드 양쪽 모두 수정
6. **Docsify 경로**: 절대경로(`/guide/images/`) 사용 금지, 반드시 상대경로(`../images/`, `../../images/`) 사용
