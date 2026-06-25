---
paths:
  - "cypress/**/*"
  - "backend/test/**/*"
  - "**/*.test.ts"
  - "**/*.spec.ts"
  - "**/*_test.py"
  - "**/*test_*.py"
---

# 테스트 규칙

## Cypress E2E 테스트
- 위치: `cypress/e2e/`
- 테스트 파일: `chat.cy.ts`, `documents.cy.ts`, `settings.cy.ts`, `registration.cy.ts`
- 설정: `cypress.config.ts` (baseUrl 설정, video recording)
- 실행: `npm run cy:open` (인터랙티브) 또는 `npx cypress run`

## pytest 백엔드 테스트
- 설정: `pyproject.toml` [tool.pytest.ini_options]
- 실행: `cd backend && pytest`
- 위치: `backend/test/` 또는 `backend/tests/`

## 프론트엔드 단위 테스트
- 확장자: `.test.ts`
- 실행: `npm run test:frontend`

## 테스트 작성 패턴
- Cypress: Page Object 패턴 없이 직접 접근
- pytest: fixture 기반, async 테스트 지원
- 프론트엔드: Vitest 사용

## 참조 파일
- `cypress/e2e/`: E2E 테스트
- `pyproject.toml`: pytest 설정
- `package.json`: 테스트 스크립트
