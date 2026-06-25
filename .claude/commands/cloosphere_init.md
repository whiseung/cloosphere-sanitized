# Cloosphere Context 구조 초기화

프로젝트의 `.claude/rules/`, `CLAUDE.md`, `.claude/skills/` 파일을 **실제 코드 분석 기반**으로 생성/갱신합니다.

## 인풋

- `$ARGUMENTS` — 선택적 커밋 ID (예: `abc1234`)
  - **커밋 ID 있음**: 해당 커밋 이후 변경된 파일만 분석하여 영향받는 rules만 생성/갱신
  - **커밋 ID 없음** (또는 `full`): 전체 코드베이스를 분석하여 모든 rules 생성

---

## 3계층 컨텍스트 구조

| 계층 | 파일 | 로드 시점 | 목표 |
|------|------|-----------|------|
| **L1** | `CLAUDE.md` (~100줄) | 매 턴 자동 | 프로젝트 개요, 명령어, 핵심 원칙 |
| **L2** | `.claude/rules/*.md` | 해당 경로 파일 작업 시 자동 | 경로별 코딩 규칙, 패턴, 참조 파일 |
| **L3** | `.claude/skills/*/SKILL.md` | `/backend`, `/frontend` 호출 시 | 신규 기능 개발 워크플로우 가이드 |

## 작성 원칙

1. **실제 코드 분석 기반** — 기존 문서 복사 금지, 코드에서 직접 패턴 추출
2. **코드 예제는 실제 파일에서 추출** — 이론적 예제 금지
3. **각 rules 파일 50-120줄** 목표 — 너무 길면 토큰 낭비
4. **명령형 규칙** 위주 — "~하라", "~금지" 형태
5. **참조 파일 경로 명시** — 패턴 확인용

---

## 실행 단계

### 1단계: 분석 범위 결정

인풋에 따라 분석 범위를 결정합니다.

**전체 분석 (커밋 ID 없음):**
```bash
# 현재 상태 확인
ls .claude/rules/*.md 2>/dev/null | wc -l
wc -l CLAUDE.md 2>/dev/null
```

**델타 분석 (커밋 ID 있음):**
```bash
# 해당 커밋 이후 변경된 파일 목록 추출
git diff --name-only {COMMIT_ID}..HEAD

# 변경된 파일의 디렉토리 패턴 분석
git diff --name-only {COMMIT_ID}..HEAD | sed 's|/[^/]*$||' | sort -u
```

### 2단계: 코드베이스 구조 탐색 — Rules 도메인 도출

**이 단계가 핵심입니다.** 파일 수와 이름을 미리 정하지 않고, 코드를 분석하여 어떤 rules 도메인이 필요한지 도출합니다.

#### 2-1. 디렉토리 구조 스캔

코드베이스의 주요 디렉토리를 탐색하여 독립된 도메인을 식별합니다.

**백엔드 도메인 식별:**
- `backend/open_webui/routers/*.py` → 각 라우터가 하나의 feature 도메인 후보
- `backend/open_webui/models/*.py` → 라우터와 1:1 매핑되는지 확인
- `backend/open_webui/utils/*.py` → 코어 유틸리티 (auth, middleware, config 등)
- `backend/extension_modules/*/` → 각 모듈이 하나의 ext 도메인 후보
- `backend/open_webui/socket/`, `storage/` → 인프라 도메인 후보

**프론트엔드 도메인 식별:**
- `src/lib/components/*/` → 각 1레벨 서브디렉토리가 UI 도메인 후보
- `src/lib/apis/*/` → API 클라이언트 모듈 (코어 rules에 포함)
- `src/lib/stores/`, `src/lib/utils/`, `src/lib/i18n/` → 코어 도메인
- `src/routes/(app)/*/` → 라우트 구조 확인

**인프라 도메인 식별:**
- `Dockerfile`, `docker-compose*`, `Makefile` → 배포
- `cypress/`, `backend/test/` → 테스트
- Socket.IO, Storage → 인프라 서비스

#### 2-2. 도메인 분류 기준

| 분류 | 네이밍 패턴 | 기준 |
|------|-------------|------|
| 백엔드 코어 | `backend-*.md` | 여러 라우터/모델에서 공통 사용하는 패턴 (router, model, auth, config, middleware) |
| 백엔드 기능 | `feature-*.md` | 특정 비즈니스 기능 단위 (라우터+모델+프론트엔드 묶음). 관련성 높은 라우터는 하나로 합침 |
| 백엔드 인프라 | `infra-*.md` | 비즈니스 로직이 아닌 시스템 인프라 |
| Extension Module | `ext-*.md` | `extension_modules/` 하위 독립 모듈 |
| 프론트엔드 코어 | `frontend-*.md` | 여러 컴포넌트에서 공통 사용하는 패턴 (component, styling, api-client, store, page, i18n, utils) |
| 프론트엔드 기능 | `ui-*.md` | `src/lib/components/{domain}/` 단위의 UI 도메인 |

#### 2-3. 도메인 합치기/분리 판단

- **합치기**: 관련 라우터가 2-3개이고 항상 함께 수정되면 하나의 feature로 (예: tools + functions + tool_connections → `feature-tools-functions.md`)
- **분리**: 하나의 디렉토리가 너무 크면 (예: admin/Settings → `ui-admin.md` + `ui-admin-settings.md`)
- **기준**: 하나의 rules 파일이 50-120줄을 유지할 수 있는 단위

#### 2-4. 델타 분석 시 (커밋 ID 있음)

변경된 파일 경로를 기존 rules의 `paths:` 패턴과 매칭합니다.

```
변경 파일 → 매칭되는 기존 rules 파일 찾기:
  - 매칭됨 → 해당 rules 파일 내용 갱신 대상
  - 매칭 안됨 → 새 rules 도메인이 필요한지 판단
    - 기존 도메인에 paths 추가로 해결 가능 → paths만 갱신
    - 완전히 새로운 도메인 → 새 rules 파일 생성
```

### 3단계: 코드 패턴 수집 (병렬)

도출된 도메인별로 Explore 에이전트를 **병렬 실행**하여 실제 코드 패턴을 수집합니다.

**에이전트당 수집 항목:**
- 임포트 패턴, 클래스/함수 시그니처
- CRUD 엔드포인트 목록 (라우터)
- DB 스키마 필드 목록 (모델)
- 컴포넌트 계층 구조 (프론트엔드)
- 특이 패턴 (해당 도메인에만 있는 것)
- 참조 파일 경로

**병렬 그룹 구성:**
- 전체 분석: 도메인 수에 따라 4-6개 그룹으로 분배
- 델타 분석: 영향받는 도메인만 그룹화

### 4단계: Rules 파일 생성/갱신

수집된 패턴으로 rules 파일을 작성합니다.

#### Rules 파일 필수 구조

```markdown
---
paths:
  - "glob/패턴/1"
  - "glob/패턴/2"
---

# 제목 (한글)

## 핵심 패턴
(실제 코드에서 추출한 임포트, 생성, 호출 패턴)

## 주요 규칙
(명령형: ~하라, ~금지, ~확인)

## 참조 파일
(실제 파일 경로 목록)
```

#### paths 패턴 설계 규칙
- 해당 도메인의 모든 관련 파일을 포괄하는 glob 패턴
- 백엔드: `backend/open_webui/{dir}/**/*.py`
- 프론트엔드: `src/lib/components/{domain}/**/*.svelte`, `src/routes/(app)/{path}/**/*`
- Extension: `backend/extension_modules/{module}/**/*.py`
- 인프라: 구체적 파일 경로 또는 와일드카드

#### 내용 작성 규칙
- 코드 예제는 반드시 실제 파일에서 복사
- 해당 도메인의 고유한 패턴에 집중 (공통 패턴은 코어 rules에서 다룸)
- feature-*.md: 라우터 엔드포인트 + 모델 스키마 + 비즈니스 로직 + 프론트엔드 연동
- ui-*.md: 컴포넌트 계층 + Props/이벤트 + 특이 패턴 + 참조 파일
- ext-*.md: 베이스 클래스 + 상속 패턴 + 설정 방법

### 5단계: CLAUDE.md 갱신

**전체 분석 시:** CLAUDE.md를 ~100줄로 재작성합니다.

포함 항목:
- 프로젝트 한줄 소개
- 스택 (5줄)
- 개발 명령어 (10줄)
- 핵심 원칙 (7줄)
- 아키텍처 개요 (25줄) — "상세는 `.claude/rules/`에서 자동 로드됨" 안내
- 주요 환경 변수 (6줄)
- Docker (5줄)
- 컨텍스트 구조 (3줄)
- 기술 요구사항 (3줄)

제거 대상: 파일 경로 전체 목록, 개발 워크플로우 상세, 코드 예제, 환경 변수 전체 목록

**델타 분석 시:** 새 도메인 추가된 경우 아키텍처 개요 섹션만 갱신합니다.

### 6단계: Skills SKILL.md 정리

Skills 파일에서 코딩 규칙/패턴 부분을 제거하고 **워크플로우 가이드만** 유지합니다.

- `.claude/skills/backend/SKILL.md`: 새 API 엔드포인트 개발 워크플로우 + 체크리스트
- `.claude/skills/frontend/SKILL.md`: 새 프론트엔드 기능 개발 워크플로우 + 체크리스트

**핵심:** "코딩 규칙은 `.claude/rules/`에서 파일 작업 시 자동 로드됨" 안내 문구 포함

### 7단계: 검증

```bash
# rules 파일 수 확인
ls .claude/rules/*.md | wc -l

# CLAUDE.md 줄 수 확인 (목표: ~100줄)
wc -l CLAUDE.md

# Skills 줄 수 확인
wc -l .claude/skills/*/SKILL.md

# paths 프론트매터 누락 확인
for f in .claude/rules/*.md; do
  head -1 "$f" | grep -q "^---" || echo "MISSING frontmatter: $f"
done

# 각 rules 파일 줄 수 확인 (50-120줄 범위)
wc -l .claude/rules/*.md | sort -n
```

---

## 델타 분석 예시

```
/cloosphere_init abc1234
```

1. `git diff --name-only abc1234..HEAD` → 변경 파일 수집
2. 변경 파일을 기존 rules의 paths와 매칭
3. 매칭된 rules만 코드 재분석 후 갱신
4. 매칭 안 되는 새 파일 → 새 도메인 필요 여부 판단
5. CLAUDE.md는 새 도메인 추가 시에만 아키텍처 개요 갱신

---

## 체크리스트

- [ ] 분석 범위 결정 (전체 vs 델타)
- [ ] 코드베이스 구조 스캔 → rules 도메인 도출
- [ ] 도메인별 코드 패턴 수집 (병렬 에이전트)
- [ ] Rules 파일 생성/갱신 (paths 프론트매터 포함)
- [ ] CLAUDE.md 갱신 (~100줄)
- [ ] Skills SKILL.md 정리 (워크플로우만 유지)
- [ ] 전체 검증 (파일 수, 줄 수, 프론트매터)
