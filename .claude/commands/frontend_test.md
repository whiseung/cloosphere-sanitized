# Frontend E2E Test Command

Playwright MCP를 사용하여 프론트엔드 UI를 브라우저로 직접 테스트합니다.

## 테스트 환경

- **Frontend**: `http://localhost:5173` (`npm run dev`)
- **Backend**: `http://localhost:8080`
- **Playwright MCP**: headless Chrome (no-sandbox)

### 테스트 계정

| 이름 | Email | Password | 용도 |
|------|-------|----------|------|
| FrontAdmin | front_test@cloocus.com | Zmffnzjtm12#$ | 프론트엔드 E2E 테스트 전용 |

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

### 1단계: 브라우저 접속 및 로그인

```
1. browser_navigate → http://localhost:5173
2. viewport 크기 설정: browser_resize → 1440 x 900
3. browser_snapshot으로 로그인 폼 확인
4. browser_fill_form으로 이메일/비밀번호 입력
   - Email: front_test@cloocus.com
   - Password: Zmffnzjtm12#$
5. Sign in 버튼이 viewport 밖일 수 있음 → browser_run_code로 클릭:
   async (page) => {
     await page.evaluate(() => {
       document.querySelector('button[type="submit"]').click();
     });
     await page.waitForTimeout(3000);
     return page.url();
   }
6. URL이 /auth가 아닌 / 로 이동했는지 확인
```

**주의사항:**
- headless + no-sandbox 환경에서 Sign in 버튼이 viewport 밖에 위치할 수 있음
- `browser_click`이 "outside of viewport" 에러를 내면 `browser_run_code`의 `page.evaluate`로 우회
- 로그인 후 3~5초 대기 필요 (SvelteKit 라우팅 + Socket.IO 연결)

### 2단계: 세션 작업 분석

현재 대화에서 작업한 프론트엔드 변경 내용을 분석하여 테스트 대상을 파악합니다.

- 어떤 페이지/컴포넌트가 변경되었는지
- 어떤 UI 동작이 추가/수정되었는지
- 관련 API 연동이 있는지

### 3단계: 테스트 시나리오 실행

변경 내용에 따라 적절한 테스트를 수행합니다.

#### 페이지 네비게이션

```
browser_navigate → http://localhost:5173/{path}
browser_snapshot → 페이지 구조 확인
browser_take_screenshot → 시각적 확인
```

#### 주요 페이지 경로

| 페이지 | 경로 | 설명 |
|--------|------|------|
| 메인 채팅 | `/` | 채팅 입력, 모델 선택 |
| 워크스페이스 | `/workspace` | Agents, Knowledge, Database 등 |
| 관리자 설정 | `/admin/settings` | 14개 탭 설정 |
| 관리자 사용자 | `/admin` | 사용자 관리 |
| 채널 | `/channels` | 메시징 |

#### 폼 입력 및 버튼 클릭

```
1. browser_snapshot → ref 값 확인
2. browser_fill_form → 폼 필드 입력
3. browser_click → 버튼 클릭 (ref 사용)
4. browser_snapshot → 결과 확인
```

#### 모달/드로어 확인

```
1. 트리거 버튼 클릭
2. browser_snapshot → 모달 내용 확인
3. 필요시 browser_take_screenshot → 시각적 확인
4. 닫기 또는 제출
```

#### JavaScript 실행

```
browser_evaluate → DOM 상태 확인, 데이터 추출
browser_run_code → 복잡한 시나리오 (여러 단계 조합)
```

### 4단계: 스크린샷 캡처

테스트 결과를 시각적으로 확인합니다.

```
# 현재 viewport 스크린샷
browser_take_screenshot → type: png, filename: test-{페이지명}.png

# 전체 페이지 스크린샷
browser_take_screenshot → type: png, fullPage: true, filename: test-{페이지명}-full.png

# 특정 요소 스크린샷
browser_take_screenshot → type: png, ref: {요소ref}, element: "{설명}", filename: test-{요소명}.png
```

### 5단계: 에러 및 콘솔 확인

```
# 콘솔 에러 확인
browser_console_messages → level: error

# 네트워크 요청 확인 (API 호출 실패 등)
browser_network_requests
```

### 6단계: 정리 및 결과 보고

```
# 브라우저 종료
browser_close
```

```markdown
## Frontend E2E 테스트 결과

| 테스트 | 결과 | 스크린샷 | 비고 |
|--------|------|----------|------|
| 로그인 | OK/FAIL | login.png | |
| 페이지 렌더링 | OK/FAIL | page.png | |
| 폼 동작 | OK/FAIL | form.png | |
| API 연동 | OK/FAIL | - | |
| 콘솔 에러 | 없음/있음 | - | |

**발견된 이슈:** (있으면 기술)
```

## Playwright MCP 도구 요약

| 도구 | 용도 | 비고 |
|------|------|------|
| `browser_navigate` | URL 이동 | |
| `browser_snapshot` | 접근성 스냅샷 (요소 ref 확인) | 액션 전 필수 |
| `browser_take_screenshot` | 시각적 스크린샷 | png/jpeg |
| `browser_click` | 요소 클릭 | ref 필요 |
| `browser_fill_form` | 폼 입력 | 여러 필드 동시 |
| `browser_type` | 텍스트 입력 | 단일 필드 |
| `browser_hover` | 마우스 호버 | 툴팁, 드롭다운 |
| `browser_select_option` | 셀렉트박스 선택 | |
| `browser_press_key` | 키보드 입력 | Enter, Escape 등 |
| `browser_evaluate` | JS 실행 | DOM 확인 |
| `browser_run_code` | Playwright 코드 실행 | 복잡한 시나리오 |
| `browser_console_messages` | 콘솔 로그 확인 | error/warning/info |
| `browser_network_requests` | 네트워크 요청 확인 | API 호출 검증 |
| `browser_resize` | viewport 크기 변경 | 반응형 테스트 |
| `browser_close` | 브라우저 종료 | 테스트 종료 시 |

## 주의사항

1. **viewport 크기**: 기본 viewport가 작을 수 있음 → 테스트 시작 시 `browser_resize(1440, 900)` 필수
2. **viewport 밖 요소**: `browser_click`이 실패하면 `browser_run_code`의 `page.evaluate`로 우회
3. **로딩 대기**: SPA이므로 페이지 전환 후 `waitForTimeout(3000)` 또는 특정 요소 대기 필요
4. **다크모드**: 다크모드 테스트 시 시스템 설정 또는 UI 토글로 전환
5. **i18n**: 한국어/영어 전환 테스트 가능 (로그인 페이지에서 언어 버튼 클릭)
6. **스크린샷 정리**: 테스트 완료 후 생성된 .png 파일 정리 필요
7. **headless 제약**: 파일 업로드, 클립보드 등 일부 브라우저 기능 제한 있음
