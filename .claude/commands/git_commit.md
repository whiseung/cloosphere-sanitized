# Git Commit Command

현재 세션에서 작업한 내용만 커밋합니다.

## 커밋 타입

| 타입 | 설명 | 예시 |
|------|------|------|
| `feat` | 새로운 기능 추가 | feat: 검색 엔진 모듈 추가 |
| `fix` | 버그 수정 | fix: 로그인 오류 수정 |
| `update` | 기존 기능 개선/수정 | update: 사용자 목록 페이지네이션 개선 |
| `refactor` | 코드 리팩토링 (기능 변경 없음) | refactor: API 클라이언트 구조 개선 |
| `docs` | 문서 추가/수정 | docs: API 사용 가이드 작성 |
| `style` | 코드 스타일 변경 (포맷팅, 세미콜론 등) | style: 코드 포맷팅 적용 |
| `test` | 테스트 추가/수정 | test: 인증 API 테스트 추가 |
| `chore` | 빌드, 설정 파일 변경 | chore: 의존성 업데이트 |
| `perf` | 성능 개선 | perf: 쿼리 최적화 |

## 커밋 메시지 규칙

1. **언어**: 한글로 작성
2. **형식**: `{타입}: {제목}` (예: `feat: 용어집 검색 기능 추가`)
3. **제목**: 50자 이내, 명령형으로 작성
4. **본문**: 필요시 변경 사항을 bullet point로 상세 설명
5. **Co-Author**: 항상 포함

```
feat: 제목

- 변경 사항 1
- 변경 사항 2
```

## 실행 단계

### 0-a단계: i18n 검토 (커밋 전 필수)

이번 세션에서 변경/추가된 파일에 누락된 i18n 키나 하드코딩된 사용자 가시 문자열이 없는지 확인합니다. 변경 파일에 한정해서 리뷰하며, 세션 범위 밖의 기존 문자열은 건드리지 않습니다.

**확인 대상**

1. **프론트 화면 노출 텍스트**
   - 버튼 라벨, 제목, 설명, placeholder, tooltip, aria-label, empty state 문구 등 템플릿의 모든 사용자 가시 문자열
   - `$i18n.t('...')` 로 래핑되어야 함 — 리터럴 한글/영문 금지
2. **Toast / 알림 메시지**
   - `toast.success()` / `toast.error()` / `toast.info()` / `toast.warning()` 의 메시지 인자
   - 정적 메시지는 `$i18n.t('...')` 로 래핑
   - 서버에서 내려온 동적 에러(`e?.detail`, `e?.message`)는 번역 대상이 아니므로 래핑하지 않고 그대로 표시 (`toast.error($i18n.t(\`${e}\`))` 같은 잘못된 패턴 금지)
3. **백엔드 → 프론트 전달 텍스트**
   - `HTTPException(detail=...)`, `ERROR_MESSAGES` 등 사용자에게 노출될 수 있는 메시지
   - 프론트가 번역 키로 매핑하거나, 백엔드가 요청 언어에 따라 메시지를 선택하도록 구현되어 있어야 함

**검사 포인트**

- 새로 추가한 키는 `src/lib/i18n/locales/ko-KR/translation.json` 과 `en-US/translation.json` **둘 다** 존재해야 함
- 두 파일은 직접 수동 편집 — `npm run i18n:parse` 는 **실행 금지** (다른 로케일이 꼬임)
- `$i18n.t()` 인자는 정적 문자열 리터럴이어야 함. 런타임 변수를 키로 넘기면 번역이 안 됨
- 위반 사항 발견 시 사용자에게 보고하고 수정 후 커밋을 진행합니다.

### 0-b단계: Ruff 자동 수정 (커밋 전 필수)

백엔드(Python) 변경이 있을 때 아래 순서로 실행합니다. 프론트엔드만 변경된 세션에서는 생략 가능.

```bash
# 1. 자동 수정 (import 정렬, 간단한 lint 오류 등)
cd backend && uv run ruff check . --select F,I,E9 --ignore W,F841 --fix
cd backend && uv run ruff format .

# 2. 재검사 (자동 수정 불가한 오류 확인)
cd backend && uv run ruff check . --select F,I,E9 --ignore W,F841
```

- **재검사 후 오류가 있으면**: 자동 수정 불가한 문제이므로 내용을 사용자에게 보고하고 커밋을 중단합니다.
- **재검사 통과하면**: 자동 수정된 파일을 스테이징에 포함하고 다음 단계로 진행합니다.

### 0-c단계: 의존성 동기화 검토 (커밋 전 필수)

이번 세션에서 **새 의존성 (Python 패키지 / npm 패키지) 을 추가/사용**했다면 모든
manifest 파일에 반영돼 있는지 확인합니다. 한 곳만 빠져도 배포 환경에서
`ModuleNotFoundError` / `Cannot find module` 으로 즉시 깨집니다.

**Python 의존성 (백엔드)**

새 `import` 문이 추가됐거나, 기존엔 없던 외부 패키지를 사용하기 시작한 경우:

1. **`pyproject.toml`** (`/cloosphere/pyproject.toml`) 의 `dependencies` 배열에 추가
2. **`backend/requirements.txt`** 에 동일 버전으로 추가 (Docker 빌드 / pip install 이 이걸 사용)
3. **`uv.lock`** (`/cloosphere/uv.lock`) 도 동기화 — `uv lock` 또는 `uv sync` 로 업데이트
4. 세 파일이 같은 버전을 가리키는지 확인:
   ```bash
   grep -nE "^<package-name>" /cloosphere/pyproject.toml /cloosphere/backend/requirements.txt
   grep -A1 "^name = \"<package-name>\"" /cloosphere/uv.lock
   ```

**알려진 함정**:
- `pyproject.toml` 만 추가하고 `requirements.txt` 누락 → Docker 배포 깨짐
- `requirements.txt` 만 추가하고 `pyproject.toml` 누락 → 로컬 개발 (uv sync) 깨짐
- transitive 의존성 (예: `langgraph-checkpoint-postgres` 가 `psycopg`/`psycopg-pool` 를 끌고 옴) 도 lock 에 잡혀야 함 — `uv lock` 이 자동 처리

**npm 의존성 (프론트엔드)**

새 `import` 가 추가됐거나 새 라이브러리를 사용한 경우:

1. **`package.json`** 의 `dependencies` / `devDependencies` 에 추가
2. **`package-lock.json`** 도 동기화 — `npm install <pkg>` 가 자동 처리

**검사 절차**

세션 중 추가한 import 들을 grep 으로 확인:

```bash
# 백엔드: 변경된 .py 파일에서 신규 import 추출
git diff --cached --name-only | grep '\.py$' | xargs grep -hE "^(import |from )" 2>/dev/null | sort -u

# 프론트: 변경된 .svelte/.ts 파일에서 신규 import 추출
git diff --cached --name-only | grep -E '\.(svelte|ts)$' | xargs grep -hE "^import " 2>/dev/null | sort -u
```

각 import 의 패키지명이 manifest 에 있는지 대조. 없으면 사용자에게 보고 후 추가하고 커밋을 진행합니다.

### 1단계: 현재 세션 작업 내용 파악

대화 내용을 분석하여 이번 세션에서 작업한 항목을 파악합니다.
- 어떤 기능을 구현했는지
- 어떤 파일을 생성/수정했는지
- 각 작업이 어떤 커밋 타입에 해당하는지

### 2단계: 파일 분류

`git status --porcelain`으로 변경된 파일을 확인하고, 세션에서 작업한 파일만 분류합니다.

```bash
git status --porcelain
```

**주의사항:**
- 이번 세션에서 작업하지 않은 파일은 커밋하지 않습니다
- 여러 기능이 섞인 파일은 해당 기능과 함께 커밋하거나 별도 안내합니다
- 삭제된 파일(D)도 확인합니다

### 3단계: 작업 항목별 커밋

각 작업 항목별로 관련 파일을 묶어서 커밋합니다.

```bash
# 1. 관련 파일 스테이징
git add <파일1> <파일2> ...

# 2. 스테이징된 파일 확인
git diff --cached --name-only

# 3. 커밋 (HEREDOC 사용)
git commit -m "$(cat <<'EOF'
feat: 커밋 제목

- 변경 사항 1
- 변경 사항 2
)"
```

### 4단계: 결과 확인

```bash
git log --oneline -5
```

커밋 결과와 남은 미커밋 파일을 사용자에게 보고합니다.

## 예시 출력

```markdown
## 커밋 완료

| 커밋 | 내용 |
|------|------|
| `abc1234` | feat: 검색 엔진 모듈 추가 |
| `def5678` | feat: 용어집 검색 연동 |

**남은 파일:** config.py, main.py (다른 기능과 혼합됨)
```

## 주의사항

1. **세션 범위**: 현재 대화에서 작업한 내용만 커밋
2. **혼합 변경**: 한 파일에 여러 기능 변경이 있으면 사용자에게 알림
3. **push 금지**: 사용자가 명시적으로 요청하지 않으면 push하지 않음
4. **destructive 명령 금지**: `--force`, `--hard`, `-D` 등 사용 금지
