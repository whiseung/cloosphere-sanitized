# Description

## 📝 요약

Cloosphere v2 엔터프라이즈 기능 대규모 업데이트

이번 PR은 조직 관리, 모니터링, 워크스페이스 기능 확장, 검색 엔진 추상화 등 엔터프라이즈급 기능을 추가하는 메이저 업데이트입니다.

---

## 📄 변경 내용

### 1. 조직(Organization) 관리 시스템

- **조직/부서 관리**: Microsoft Entra ID (Azure AD) 연동으로 조직 구조 동기화
- **조직 단위(Organizational Unit)**: 계층 구조 트리 형태로 조직 단위 관리
- **접근 제어 확장**: 기존 그룹 기반 + 조직 단위 기반 권한 관리
- **OAuth 자동 동기화**: 로그인 시 사용자 부서 정보 자동 배치

**관련 파일:**
- `backend/open_webui/models/organization.py`
- `backend/open_webui/routers/organizations.py`
- `backend/open_webui/services/organization_providers/`
- `backend/open_webui/utils/oauth.py`
- `src/lib/components/admin/Users/Organizations.svelte`

### 2. 모니터링 시스템 (Usage & Audit)

#### Usage 추적
- **LLM 사용량 기록**: 모든 API 호출의 토큰 사용량 추적
- **Agent ID 분리**: 워크스페이스 에이전트(agent_id)와 실제 LLM 모델(model_id) 분리 추적
- **백그라운드 태스크 추적**: 제목/태그/이모지 생성 등 모든 태스크 기록
- **임베딩 추적**: OpenAI, Azure, Ollama 임베딩 API 호출 기록
- **스트리밍 Usage 추출**: `stream_options: {"include_usage": true}` 지원

**Message Types:**
```
CHAT, EMBEDDING, AGENT_STATE, TOOL_CALL, REASONING,
TITLE_GENERATION, TAGS_GENERATION, EMOJI_GENERATION,
QUERY_GENERATION, IMAGE_PROMPT_GENERATION, AUTOCOMPLETE_GENERATION,
FUNCTION_CALLING, MOA_RESPONSE_GENERATION
```

#### Audit Logging
- **사용자 활동 기록**: 로그인, CRUD, 권한 변경 등 모든 활동 기록
- **IP/User Agent 추적**: 요청 출처 정보 기록
- **CSV 내보내기**: 감사 로그 다운로드 기능

**관련 파일:**
- `backend/open_webui/models/usage.py`
- `backend/open_webui/models/audit_log.py`
- `backend/open_webui/routers/openai.py` (usage 추적 추가)
- `backend/extension_modules/react/react_middleware_base.py`
- `src/lib/components/admin/Monitoring/Usage.svelte`
- `src/lib/components/admin/Monitoring/AuditLogs.svelte`

### 3. 워크스페이스 기능 확장

#### Models → Agents 리네이밍
- 워크스페이스 "Models"를 "Agents"로 리브랜딩
- UI 레이블 및 네비게이션 업데이트

#### Glossary (용어집)
- **용어 관리**: 도메인 용어, 약어, 업무 규칙 정의
- **검색 엔진 연동**: 벡터 검색 기반 용어 검색
- **Agent 도구**: LangChain Tool로 에이전트에서 용어 참조
- **별칭 지원**: 하나의 용어에 여러 별칭 등록

#### DbSphere 개선
- 에이전트 모듈 개선
- Usage 추적 연동

**관련 파일:**
- `backend/open_webui/models/glossary.py`
- `backend/open_webui/routers/glossary.py`
- `backend/extension_modules/glossary/`
- `src/lib/components/workspace/Glossary/`
- `src/lib/components/workspace/Models/` (Agents)

### 4. 검색 엔진 추상화 모듈

다양한 벡터 데이터베이스를 통일된 인터페이스로 사용할 수 있는 추상화 레이어:

**지원 엔진:**
| 엔진 | 클래스 |
|------|--------|
| Azure AI Search | `AzureSearchEngine` |
| PostgreSQL pgvector | `PgVectorEngine` |
| Milvus | `MilvusEngine` |
| Elasticsearch | `ElasticsearchEngine` |
| Vertex AI Search | `VertexSearchEngine` |

**스키마 프리셋:**
- `create_knowledge_config()` - 지식베이스
- `create_glossary_config()` - 용어집
- `create_dbsphere_config()` - DB 메타데이터

**관련 파일:**
- `backend/extension_modules/search_engine/`
  - `base.py` - 추상 베이스 클래스
  - `connector.py` - 팩토리 함수
  - `schemas.py` - 스키마 프리셋
  - `dbs/` - 엔진별 구현체

### 5. 도구 서버 연결 (MCP/OpenAPI)

외부 도구 서버와의 연결을 위한 모듈:

- **MCP Connector**: Model Context Protocol 서버 연결
- **OpenAPI Connector**: OpenAPI 스펙 기반 도구 연결
- **LangChain Adapter**: 도구를 LangChain Tool로 변환

**관련 파일:**
- `backend/extension_modules/server/`
- `backend/open_webui/models/tool_connections.py`
- `backend/open_webui/routers/tool_connections.py`

### 6. 관리자 패널 권한 분리

- **세분화된 권한**: `userPermissions` 스토어 기반 탭별 접근 제어
- **권한 항목**: users, evaluations, functions, settings, monitoring
- **Developer Mode**: 관리자 전용 개발자 도구 (로케일 관리 등)

**관련 파일:**
- `src/routes/(app)/admin/+layout.svelte`
- `src/lib/stores/index.ts`

### 7. SharePoint 연동 개선

- Enable/Disable 설정 추가
- 채팅창 노출 조건 제어

**관련 파일:**
- `src/lib/components/common/SharePointBrowser.svelte`
- `src/lib/components/chat/MessageInput/InputMenu.svelte`

### 8. 개발자 모드 기능

- **로케일 관리**: 다국어 번역 키 관리
- **디버그 도구**: 개발 시 유용한 도구 모음

### 9. 문서화

#### Claude Skills 업데이트
- 백엔드 스킬: Extension Modules, Usage 추적, Audit Logging
- 프론트엔드 스킬: 관리자 권한, Monitoring 컴포넌트, Agents

#### 엔지니어 문서 추가
- `docs/engineers/organization/` - 조직 관리 가이드
- `docs/engineers/search_engine/` - 검색 엔진 가이드
- `docs/engineers/glossary/` - 용어집 가이드
- `docs/engineers/monitoring/` - 모니터링 가이드
- `docs/engineers/dbsphere/` - DbSphere 가이드
- `docs/engineers/sharepoint/` - SharePoint 가이드

### 10. 기타 개선사항

- **UI 컴포넌트 개선**: 사이드바, 네비게이션, 아이콘 추가
- **다국어 번역**: en-US, ko-KR 업데이트
- **빌드 방식 변경**: Azure DevOps 파이프라인 복구
- **코드 정리**: imports 정리, 포맷팅 개선

---

## 🔗 관련 항목

**관련 이슈:**
- 조직 관리 기능 요청
- Usage 추적 기능 요청
- 모니터링 대시보드 요청

**관련 문서:**
- [조직 관리 가이드](docs/engineers/organization/README.md)
- [검색 엔진 가이드](docs/engineers/search_engine/README.md)
- [모니터링 가이드](docs/engineers/monitoring/README.md)
- [Glossary 가이드](docs/engineers/glossary/README.md)

---

## ✅ 체크리스트

### PR 제출 전 확인사항
- [x] PR 제목이 `{TYPE}({SCOPE}): {설명}` 형식을 따름
  - **TYPE**: feat
  - **SCOPE**: backend, frontend

### 로컬 검증
- [x] 린트 통과: `uv run ruff check . --select F,I,E9 --ignore W,F841`
- [x] 포맷 확인: `uv run ruff format . --check`
- [ ] 테스트 통과: `uv run pytest -q`

### 변경 유형
- [x] 새 기능
- [x] 버그 수정
- [x] 리팩토링 (기능 변경 없음)
- [x] 문서 수정
- [x] 설정/CI 변경
- [ ] 기타:

---

## 📊 변경 통계

| 항목 | 수치 |
|------|------|
| 커밋 수 | 40+ |
| 변경 파일 수 | 395 |
| 주요 기능 | 10개 |

---

## 📸 스크린샷 (UI 변경 시)

### 관리자 패널 - Monitoring 탭
- Usage 대시보드: 일별/주별/월별 사용량 차트
- Audit Logs: 사용자 활동 로그 테이블

### 워크스페이스 - Agents
- Models → Agents 리네이밍
- Glossary 관리 페이지

### 조직 관리
- 조직 단위 트리 뷰
- 접근 제어 설정 모달

---

## 💬 리뷰어 참고사항

### 주요 리뷰 포인트

1. **Usage 추적 로직**: `routers/openai.py`의 스트리밍 usage 추출 로직
2. **검색 엔진 추상화**: `extension_modules/search_engine/` 아키텍처
3. **조직 권한**: `utils/access_control.py`의 조직 단위 권한 검사
4. **DB 마이그레이션**: `migrations/versions/` 새 테이블 추가

### 테스트 방법

1. **조직 관리**
   - 관리자 > 사용자 > 조직 탭에서 동기화 테스트
   - 리소스에 조직 단위 권한 할당 테스트

2. **모니터링**
   - 관리자 > Monitoring 탭에서 Usage/Audit 조회
   - 채팅 후 Usage 기록 확인

3. **Glossary**
   - 워크스페이스 > Glossary에서 용어 추가
   - 에이전트에 Glossary 연결 후 용어 검색 테스트

### 환경 변수 추가

```env
# 검색 엔진
SEARCH_ENGINE_TYPE=azure_search
SEARCH_ENGINE_AZURE_ENDPOINT=https://...
SEARCH_ENGINE_AZURE_API_KEY=...

# 조직 동기화
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true

# 모니터링
ENABLE_USAGE_TRACKING=true
ENABLE_AUDIT_LOGGING=true
```

### 마이그레이션

```bash
cd backend
alembic upgrade head
```

---
