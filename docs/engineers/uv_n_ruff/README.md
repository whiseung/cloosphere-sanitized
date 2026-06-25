> Last Updated: 2026-04-08

# uv + Ruff — Python 도구 체인 가이드

Cloosphere 프로젝트에서 사용하는 Python **패키지 관리자(`uv`)** 와 **린터/포매터(`ruff`)** 의 사용 가이드. 이 폴더는 feature 문서가 아닌 **개발 도구 메타 문서**이며, 단일 제품 기능이 아니라 7개의 주제별 파일로 구성됩니다.

## 문서 목록

| # | 파일 | 주제 |
|---|---|---|
| 01 | [uv 소개](./01-uv.md) | `uv`란 무엇인가, 왜 `pip`/`poetry` 대신 사용하는가 |
| 02 | [pyproject.toml](./02-pyproject.md) | `pyproject.toml` 구조, dependencies, `[dependency-groups]` (PEP 735) |
| 03 | [pip vs uv](./03-pip_n_uv.md) | `pip`와 `uv`의 명령어 대응, 마이그레이션 |
| 04 | [Python 버전 관리](./04-python-version-managing.md) | `uv python install`, `.python-version` |
| 05 | [Ruff 소개](./05-ruff.md) | `ruff`란 무엇인가, Linter + Formatter 통합 |
| 06 | [Lint](./06-lint.md) | `ruff check` 사용법, 규칙 선택 |
| 07 | [Formatter](./07-formatter.md) | `ruff format` 사용법, Linter vs Formatter |

추가 학습 자료: `examples/` 폴더 (실전 예제 프로젝트들)

## Cloosphere 현재 설정 요약

### Python 버전

```toml
# pyproject.toml
requires-python = ">=3.12"
```

**`.python-version` 파일**은 현재 프로젝트에 없습니다. 팀 consistency를 원한다면 추가 권장 (uv가 자동으로 읽음):

```bash
echo "3.12" > .python-version
```

### Dependency Groups (PEP 735)

Cloosphere `pyproject.toml`은 **PEP 735 `[dependency-groups]` 형식**을 사용합니다 (과거의 `[tool.uv.dev-dependencies]` 아님):

```toml
[dependency-groups]
test = ["pytest", "pytest-asyncio", ...]
lint = ["ruff", "mypy"]
dev = ["ipython", "ipdb", ...]
```

설치:

```bash
# 특정 group만
uv sync --group test

# 전체 (기본 dependencies + 모든 group)
uv sync --all-groups
```

### Ruff 설정

```toml
[tool.ruff]
# line-length, target-version 등 (기본값 사용)

[tool.ruff.lint]
select = ["E", "F", "I", "B"]
# Exclude
exclude = ["migrations/", "templates/", ".langgraph_api/", "media/", "tests/", "unit_tests/"]
```

- **E**: pycodestyle errors
- **F**: pyflakes (unused imports, undefined names)
- **I**: isort (import 정렬)
- **B**: flake8-bugbear (common bugs)

> **⚠️ 주의**: `CLAUDE.md`에는 `--select F,I,E9 --ignore W,F841`로 명시되어 있습니다. `pyproject.toml`의 설정과 CI 스크립트가 다를 수 있으니 실제 운영 설정은 두 파일을 모두 확인하세요.

## 자주 쓰는 명령 (Cloosphere 기준)

```bash
# 의존성 설치 (lock 기반)
uv sync

# 새 패키지 추가
uv add fastapi

# 개발 의존성에 추가
uv add --group dev ipython

# 패키지 제거
uv remove old-package

# Lock 파일 업데이트
uv lock --upgrade

# Lint 검사 (CLAUDE.md 명령)
uv run ruff check . --select F,I,E9 --ignore W,F841

# Format 검증 (수정하지 않음)
uv run ruff format . --check

# Format 자동 수정
uv run ruff format .

# Lint + 자동 수정
uv run ruff check . --fix
```

## 참고 링크

- uv: https://docs.astral.sh/uv/
- Ruff: https://docs.astral.sh/ruff/
- PEP 735 (Dependency Groups): https://peps.python.org/pep-0735/

## 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-04-08 | README 신규 작성 (front-door) + `[dependency-groups]` PEP 735 안내 + 현재 Ruff rule 반영 + `.python-version` 부재 알림 + 07-formatter.md 완성 | `docs/eng-docs-refresh` |
| 2026-01-30 | 01~07 파일 초기 작성 | |
