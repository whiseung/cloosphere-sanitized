# Guide 페이지 최신화

`guide/ko/` 및 `guide/en/` 사용자 가이드 문서를 최근 코드 변경사항에 맞게 업데이트합니다.

## 작업 순서

### 1단계: 변경 범위 파악

가이드 마지막 업데이트 이후의 기능 변경 커밋을 확인합니다.

```bash
# 가이드 마지막 수정 시점
git log -1 --format="%H %ai %s" -- guide/

# 이후 기능 변경 커밋 (docs/style/chore 제외)
git log <마지막_가이드_커밋>..HEAD --oneline --no-merges | grep -vE "docs:|style:|chore:"
```

### 2단계: 가이드 파일 매핑

변경된 기능이 어떤 가이드 파일에 해당하는지 매핑합니다.

**가이드 구조:**
```
guide/{ko,en}/
├── admin/
│   ├── settings.md        # 관리자 설정 (연결, 검색, Code Gateway 등)
│   ├── monitoring.md      # 모니터링 (사용량, 로그, 트레이스)
│   ├── notifications.md   # 알림 (이메일, 웹훅)
│   ├── tracing.md         # 트레이스 분석
│   └── users.md           # 사용자/그룹/조직 관리
├── workspace/
│   ├── agents.md          # 에이전트 설정
│   ├── database.md        # DbSphere 데이터베이스 연결
│   ├── knowledge.md       # 지식기반
│   ├── tools.md           # 도구/도구 연결
│   ├── glossary.md        # 용어집
│   ├── guardrails.md      # 가드레일
│   ├── prompts.md         # 프롬프트 라이브러리
│   ├── projects.md        # 프로젝트
│   └── flows.md           # 플로우
├── chat.md                # 채팅 사용법
├── schedules.md           # 예약 작업
└── getting-started.md     # 시작 가이드
```

**매핑 예시:**

| 기능 변경 | 대상 가이드 |
|-----------|------------|
| DbSphere 도구 구조 변경 | workspace/database.md |
| Tool Connection 아키텍처 | workspace/tools.md |
| Code Gateway 새 기능 | admin/settings.md |
| 웹훅 채널 추가 | admin/notifications.md |
| 가드레일 새 전략 | workspace/guardrails.md |
| 검색 설정 변경 | admin/settings.md |

### 3단계: 갭 분석

각 대상 가이드 파일을 읽고, 새 기능이 이미 문서화되어 있는지 확인합니다.

- 이미 반영된 내용은 건너뜁니다
- 누락된 내용만 추가 대상으로 분류합니다

**UI 변경 반영 필수 원칙** (누락 금지):

사용자에게 노출되는 UI 요소가 바뀌었다면 가이드는 **반드시** 동기화되어야 합니다. UI 변경 식별 방법:

```bash
# 프론트엔드 파일 변경 목록
git diff <마지막_가이드_커밋>..HEAD --stat -- src/lib/components/ | head -40
```

다음 변경은 **가이드 누락 금지**:
- 새 탭·새 페이지·새 모달 추가 (예: `NewSettingsTab.svelte`, `SomeModal.svelte`)
- 설정 항목 추가/이름 변경 (관리자 탭의 새 옵션)
- 버튼·메뉴 위치 이동 또는 명칭 변경
- 폼 필드 추가·제거 (사용자가 입력하는 항목 변화)
- 권한 레벨·역할 체계 변화
- 새 지원 대상 추가 (예: 지원 DB 목록, 지원 LLM 프로바이더, OAuth 공급자)

코드 변경이 있었는데 관련 가이드 파일의 스크린샷/섹션/용어가 구버전 그대로라면 **반드시 업데이트 대상**. 누락 여부는 이 질문으로 판단: *"사용자가 가이드만 보고 실제 화면을 찾을 수 있는가?"*

### 4단계: 가이드 업데이트

**한/영 동시 수정**: `guide/ko/`와 `guide/en/` 양쪽을 모두 업데이트합니다.

**작성 원칙:**
- 기존 문서의 톤, 형식, 스타일을 유지합니다
- 기술 용어보다 사용자 관점의 설명을 우선합니다
- 스크린샷 플레이스홀더는 HTML 주석으로 남깁니다:
  ```markdown
  <!-- 스크린샷: 기능 설명
       파일명: images/feature-name.png
  -->
  ```
- 새 섹션은 기존 문서 흐름에 자연스럽게 삽입합니다
- mermaid 다이어그램이 있으면 새 흐름에 맞게 업데이트합니다

### 5단계: 사이드바 확인

새 가이드 파일이 추가된 경우 `_sidebar.md`에 반영합니다.

```bash
cat guide/ko/_sidebar.md
cat guide/en/_sidebar.md
```

## 주의사항

- **커밋하지 않음**: 작성 후 사용자 검토를 기다립니다
- 기존 내용을 삭제하지 않습니다 (추가/수정만)
- 한/영 내용이 구조적으로 대응되는지 확인합니다
