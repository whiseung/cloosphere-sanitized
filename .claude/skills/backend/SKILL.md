---
name: backend
description: Cloosphere 백엔드 개발 컨벤션. FastAPI 라우터, SQLAlchemy 모델, 권한 관리, 설정 등.
---

# Backend Development Workflow

새로운 백엔드 기능을 처음부터 만드는 전체 워크플로우입니다.
코딩 규칙과 패턴은 `.claude/rules/backend-*.md`, `.claude/rules/feature-*.md`, `.claude/rules/ext-*.md` 파일에서 해당 파일 작업 시 자동 로드됩니다.

---

## 신규 API 엔드포인트 개발 워크플로우

### 1단계: 기존 코드 참조 확인
- 유사한 기존 라우터/모델 코드 확인
- 참조 파일:
  - CRUD 라우터: `routers/knowledge.py`, `routers/groups.py`
  - 복잡한 라우터: `routers/organizations.py`, `routers/dbsphere.py`
  - 모델 정의: `models/knowledge.py`, `models/organization.py`

### 2단계: 모델 생성
- `backend/open_webui/models/{resource}.py` 파일 생성
- ORM 클래스, Pydantic 스키마, Table 클래스 작성
- 필수 필드: id, user_id, created_at, updated_at
- 선택 필드: name, description, data(JSON), meta(JSON), access_control(JSON)
- 상세 패턴: `.claude/rules/backend-model.md` 자동 참조

### 3단계: 마이그레이션 작성
```bash
cd backend && alembic revision -m "Add {resource} table"
```
- **주의**: `--autogenerate` 사용 금지 — 수동 작성 필수
- 마이그레이션 파일에서 `upgrade()`, `downgrade()` 구현

### 4단계: 라우터 생성
- `backend/open_webui/routers/{resource}.py` 파일 생성
- CRUD 엔드포인트 5종: GET list, POST create, GET by id, POST update, DELETE
- 권한 검사: `Depends(get_verified_user)` 또는 `get_admin_user`
- 상세 패턴: `.claude/rules/backend-router.md` 자동 참조

### 5단계: main.py 등록
```python
from open_webui.routers import {resource}
app.include_router({resource}.router, prefix="/api/v1/{resource}", tags=["{resource}"])
```

### 6단계: 프론트엔드 연동 (선택)
- API 클라이언트: `src/lib/apis/{resource}/index.ts`
- 스토어 업데이트: `src/lib/stores/index.ts`
- 컴포넌트 작성
- `/frontend` 스킬 사용 권장

---

## 체크리스트

- [ ] 유사한 기존 라우터/모델 코드 확인
- [ ] `user_id` 필드 포함 여부 확인
- [ ] 권한 검사 Depends 추가 여부 확인
- [ ] `access_control` 필드 필요 여부 검토
- [ ] 마이그레이션 파일 작성 (--autogenerate 금지)
- [ ] main.py에 라우터 등록
- [ ] API 응답 형식이 기존과 일치하는지 확인

---

## Extension Module 개발 워크플로우

### ReAct 에이전트 추가
1. `extension_modules/{module}/` 디렉토리 생성
2. `ReactAgentBase` 상속하여 에이전트 구현
3. `MiddlewareBase` 사용하여 이벤트/추적 처리
4. 상세 패턴: `.claude/rules/ext-react-agent.md`

### 검색 엔진 백엔드 추가
1. `extension_modules/search_engine/dbs/{engine}.py` 구현
2. `SearchEngineBase` 상속
3. `connector.py`에 팩토리 등록
4. 상세 패턴: `.claude/rules/ext-search-engine.md`

---

## 상세 가이드 (서브 문서)

| 주제 | 파일 | 설명 |
|------|------|------|
| 라우터 작성 | [router.md](router.md) | CRUD 엔드포인트, 권한, 에러 처리 |
| 모델 작성 | [model.md](model.md) | ORM, Pydantic, CRUD 클래스 |
| 권한/인증 | [permission.md](permission.md) | JWT, 역할, 접근 제어 |
| 워크스페이스 | [workspace.md](workspace.md) | Knowledge, DbSphere, Glossary |
| 설정 관리 | [config.md](config.md) | PersistentConfig, AppConfig |
