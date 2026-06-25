# 04. Ruff Formatter: 일관된 코드 스타일리스트

**포맷터**(Formatter)는 개발자가 작성한 코드의 **스타일**(style)을 정해진 규칙에 따라 자동으로 통일시켜주는 도구입니다. 들여쓰기는 몇 칸으로 할지, 따옴표는 작은따옴표(')와 큰따옴표(") 중 무엇을 쓸지, 한 줄의 길이는 얼마로 제한할지 등 모든 코드 스타일을 자동으로 맞춰줍니다.

`Ruff`의 Formatter는 `Black`이라는 유명한 포맷터의 스타일을 거의 그대로 따르면서도, 훨씬 빠른 속도를 제공합니다.

> 플러그인이 설치되어 있으면 아래 작업들을 명령어를 치지 않더라도 vscode 안에서 해결해줍니다.

### 학습 목표

-   Formatter의 역할과 장점을 이해합니다.
-   `ruff format` 명령어로 코드의 스타일을 자동으로 정리할 수 있습니다.
-   Linter와 Formatter의 역할 차이를 설명할 수 있습니다.

---

### 1. Formatter는 왜 필요한가요?

-   **불필요한 논쟁 방지**: "들여쓰기는 스페이스 4칸이 맞다, 2칸이 맞다"와 같은 코드 스타일에 대한 모든 논쟁을 없애줍니다. Formatter가 정해준 규칙을 따르면 됩니다.
-   **가독성 향상**: 모든 코드가 일관된 스타일로 작성되어, 다른 사람이 작성한 코드를 읽고 이해하는 시간이 단축됩니다.
-   **핵심 로직에 집중**: 개발자는 코드 스타일에 신경 쓸 필요 없이, 오직 프로그램의 기능과 로직 구현에만 집중할 수 있습니다.

---

### 2. Formatter 사용하기: `ruff format`

`Ruff`의 Formatter 기능은 `ruff format` 명령어로 실행합니다. 이 명령어는 현재 디렉터리와 하위 디렉터리의 모든 Python 파일의 스타일을 설정에 맞게 수정합니다.

```bash
# uv를 통해 ruff format 실행
uv run ruff format .
```
이 한 번의 명령으로 모든 파일의 따옴표, 줄 바꿈, 간격 등이 아름답게 정리됩니다.

#### CI/CD 환경에서 스타일 검사하기: `--check` 옵션

CI/CD 파이프라인에서는 코드를 직접 수정하는 대신, 정해진 스타일을 따랐는지 검사만 하고 싶을 수 있습니다. 이때 `--check` 옵션을 사용합니다. 만약 스타일이 다른 코드가 있다면, `ruff format --check`는 **non-zero exit code**를 반환하여 CI가 실패하게 만듭니다. 파일을 수정하지는 않습니다.

```bash
# CI에서 스타일 검증만 (수정하지 않음)
uv run ruff format . --check
```

Cloosphere CI (`.github/workflows/...`)에서 사용되는 정확한 명령은 `CLAUDE.md` 참조:

```bash
uv run ruff check . --select F,I,E9 --ignore W,F841   # Linter
uv run ruff format . --check                           # Formatter (validate only)
```

---

### 3. Linter vs Formatter 차이

| 항목 | Linter (`ruff check`) | Formatter (`ruff format`) |
|---|---|---|
| 목적 | **코드 오류/냄새 탐지** | **코드 스타일 통일** |
| 수정 대상 | 논리적 문제 (unused imports, undefined names) | 시각적 요소 (quotes, spacing, line length) |
| 자동 수정 | `--fix` 옵션으로 일부 가능 | 기본 동작이 파일 수정 |
| CI 패턴 | `ruff check . --select F,I,E9` | `ruff format . --check` |
| 속도 | 매우 빠름 | 매우 빠름 |

두 도구는 **보완적**으로 사용됩니다. Linter는 "이 코드는 버그 가능성이 있다"를 잡고, Formatter는 "이 코드는 팀 스타일에 안 맞는다"를 고칩니다. 둘 다 CI에서 함께 실행해야 합니다.

---

### 4. Ruff Formatter vs Black

`Ruff` Formatter는 `Black`의 스타일을 **거의 동일하게 구현**했지만 몇 가지 차이가 있습니다:

- **속도**: Ruff가 Black보다 수십 배 빠름 (Rust vs Python)
- **Opinionated**: 둘 다 설정 가능한 옵션이 거의 없음 (의도적)
- **Line length**: 기본 88자 (Black과 동일)
- **String quotes**: 큰따옴표(`"`) 선호 (Black과 동일)
- **호환성**: Ruff Formatter는 Black 87% 이상 호환 (일부 엣지 케이스만 다름)

---

### 5. Cloosphere 프로젝트 설정

**현재 `pyproject.toml`의 `[tool.ruff]` 설정** (2026-04 기준):

- **`tool.ruff.lint`**에 정의된 규칙: `select = ["E", "F", "I", "B"]`
- **Exclude**: `migrations/`, `templates/`, `.langgraph_api/`, `media/`, `tests/`, `unit_tests/`
- **`[tool.ruff.format]` 섹션**: **설정 없음** (기본값 사용 — line length 88, double quote)

> ⚠️ **주의**: Cloosphere `pyproject.toml`에 명시적인 `[tool.ruff.format]` 섹션이 없습니다. 기본값이 동작하지만, 팀 컨벤션을 고정하고 싶다면 `line-length`, `quote-style` 등을 명시 추가 권장.

### 6. VS Code 통합

`.vscode/settings.json`에서 ruff extension을 기본 formatter로 설정:

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll": "explicit",
      "source.organizeImports": "explicit"
    }
  }
}
```

저장 시 자동으로 format + fix + import 정렬이 적용됩니다.