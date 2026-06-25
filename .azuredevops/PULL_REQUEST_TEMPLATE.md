## 📝 요약

<!-- PR의 목적을 한 줄로 요약해주세요 -->

## 📄 변경 내용

<!-- 어떤 변경을 했는지 설명해주세요 -->

- 

## 🔗 관련 항목

- 관련 이슈: <!-- AB#123 또는 링크 -->

## ✅ 체크리스트

### PR 제출 전 확인사항
- [ ] PR 제목이 `{TYPE}({SCOPE}): {설명}` 형식을 따름
  - TYPE: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, `release`
  - SCOPE (선택): `backend`, `frontend`, `api`, `ui`, `docs`, `tests`, `ci`, `deps`, `config`, `db`, `auth`, `chat`, `models`, `routers`, `utils`

### 로컬 검증
- [ ] 린트 통과: `uv run ruff check . --select F,I,E9 --ignore W,F841`
- [ ] 포맷 확인: `uv run ruff format . --check`
- [ ] 테스트 통과: `uv run pytest -q` (해당되는 경우)

### 변경 유형
- [ ] 새 기능
- [ ] 버그 수정
- [ ] 리팩토링 (기능 변경 없음)
- [ ] 문서 수정
- [ ] 설정/CI 변경
- [ ] 기타: 

## 📸 스크린샷 (UI 변경 시)

## 💬 리뷰어 참고사항

<!-- 리뷰어가 알아야 할 내용이 있다면 작성해주세요 -->

