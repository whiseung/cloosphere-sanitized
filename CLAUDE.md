# Cloosphere

Cloosphere by Cloocus company.

## 스택
- Backend: Python FastAPI (backend/open_webui/)
- Frontend: SvelteKit + Tailwind CSS (src/)
- DB: SQLAlchemy (SQLite/PostgreSQL) + Vector DBs
- Real-time: Socket.IO
- Custom Modules: extension_modules/ (DbSphere, KbSphere, Search Engine, React Agent)

## 개발 명령어
- Frontend dev: `npm run dev` (port 5173)
- Backend dev: `cd backend && PORT=8080 ./dev.sh`
- Build: `npm run build`
- Lint backend: `uv run ruff check . --select F,I,E9 --ignore W,F841` / Format: `uv run ruff format . --check`
- Migration: `cd backend && alembic upgrade head`
- Migration 생성: `cd backend && alembic revision -m "desc"` (--autogenerate 금지)
- Migration 작성 시 모든 DDL 은 idempotent (inspector 가드) — `.claude/rules/backend-model.md` 참조
- Test: `npm run test:frontend` / `cd backend && pytest`

## 핵심 원칙
- 기존 코드 패턴을 반드시 참조하고 따를 것 (특히 프론트엔드는 수정하는 위치의 주변 다른 페이지 포멧을 참고)
- 모든 모델에 user_id 포함 (multi-tenancy)
- 인증: `Depends(get_verified_user)` 의존성 주입
- 다크모드 필수, i18n 필수 (`$i18n.t()`) (영어/한국어)
- `access_control` JSON 필드로 그룹/조직 권한 관리
- 타임스탬프: `int(time.time())` Unix timestamp
- 에러: `HTTPException` + `ERROR_MESSAGES` 상수

## 아키텍처 개요

상세 코딩 규칙은 경로별로 `.claude/rules/`에서 자동 로드됨.

### 백엔드 (56 라우터, 40 모델)
- 인증/사용자: auths, users, organizations, groups, inquiries
- 채팅/LLM: chats, openai, ollama, tasks, channels, memories, admin_memory, folders
- 워크스페이스: knowledge, knowledge_graph, dbsphere, glossary, guardrails, tools, tool_connections, functions, prompts, models, agent_flows, projects, workspace_tags, document_profiles
- 미디어: files, file_logs, images, audio, sr
- 모니터링: usage, audit_logs, guardrail_logs, traces, trace_analysis, evaluations, auto_evaluations, bi_dashboard
- 설정: configs, pipelines, notifications, branding, license, license_permissions, code_gateway, schedules, data_retention, guide, cloocus, embed_widgets, devtools

### 프론트엔드 (389 컴포넌트, 45 API 클라이언트)
- 채팅: src/lib/components/chat/ (메시지, 입력, 마크다운)
- 워크스페이스: src/lib/components/workspace/ (Agents, Knowledge, Database, Flows, Glossary, Guardrails, Tools, Prompts, Projects)
- 관리자: src/lib/components/admin/ (Users, Settings 14탭, Monitoring, Evaluations, Functions)
- 채널: src/lib/components/channel/ (메시징, 스레드)
- 공용: src/lib/components/common/ (Modal, Drawer, Spinner 등)

### Extension Modules (backend/extension_modules/)
- dbsphere/: NL-to-SQL 에이전트 (LangGraph) — 8종 DB 지원
- kbsphere/: RAG 에이전트 (React-based)
- agent/: 통합 에이전트 (DbSphere + KbSphere + KG + 메모리/압축)
- knowledge_graph/: KG 서비스 (AGE + 검색 인덱스) + LangChain Tools
- search_engine/: 검색 엔진 추상화 (Azure Search, Elasticsearch, pgvector, Vertex)
- react/: ReAct 에이전트 프레임워크 + AgentConfig 통합 설정
- guardrail/: PII 감지, 콘텐츠 필터
- glossary/: 용어집 서비스
- agent_flow/: 플로우 실행 엔진
- auto_evaluation/: 자동 평가 실행기
- trace_analysis/: 트레이스 LLM 분석
- guide_agent/: 사용 가이드 에이전트
- embed_sso/: 임베드 위젯 SSO
- tools/: 공용 내장 툴
- tools/document/: PPT/Word/Excel 파일 생성 LangChain 툴 (create_pptx/docx/xlsx) — UnifiedAgent 전용

## 환경 변수 (주요)
- `DATABASE_URL`: SQL DB 연결 (기본: SQLite)
- `VECTOR_DB`: 벡터 DB 유형 (qdrant, milvus, pgvector, azure_search 등)
- `OLLAMA_BASE_URL`: Ollama 서버 URL
- `OPENAI_API_BASE_URL` / `OPENAI_API_KEY`: OpenAI 호환 API
- `RAG_EMBEDDING_ENGINE` / `RAG_EMBEDDING_MODEL`: 임베딩 설정
- `WEBUI_SECRET_KEY`: JWT 서명 키

## 컨텍스트 구조
- 경로별 코딩 규칙: `.claude/rules/` (파일 작업 시 자동 활성화)
- 워크플로우: `/backend`, `/frontend` Skills (명시적 호출)
- 메모리: `.claude/projects/memory/MEMORY.md`

## 테스트 환경

개발 시 Claude가 직접 API를 호출하여 동작을 확인할 수 있다.

- **Backend**: `http://localhost:8080` 
- **Frontend**: `http://localhost:5173` (`npm run dev`)
- **테스트 관리자 JWT**: `<REDACTED>`
- **테스트 API Key**: `<REDACTED>`

### API 호출 예시
```bash
curl -H 'Authorization: Bearer <REDACTED>' http://localhost:8080/api/v1/users/
```

## 기술 요구사항
- Python: 3.12+
- Node: 18.13.0 - 22.x.x
- Package manager: `uv` (Python), `npm` (Frontend)
