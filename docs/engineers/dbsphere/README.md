> Last Updated: 2026-04-08

# DBSphere (데이터베이스 에이전트)

자연어 질문을 SQL로 변환하고 결과를 시각화하는 NL-to-SQL 에이전트 모듈. LangChain/LangGraph + ReactAgentBase 기반으로 구현되었으며, **8종 DB** (PostgreSQL, MySQL, MSSQL, Oracle, Snowflake, Databricks, Synapse, Fabric) 를 지원한다. License feature gate `dbsphere`로 제어된다.

## 문서 목록

| # | 파일 | 내용 |
|---|---|---|
| 1 | [개요](./01_overview.md) | 기능 목적 · 핵심 개념 · 데이터 흐름 · 모듈 구조 |
| 2 | [아키텍처](./02_architecture.md) | DB 모델 · Agent · SQL Runner · Memory · Chart · Refactor History · 트러블슈팅 |
| 3 | [API](./03_api.md) | 22개 REST 엔드포인트 (CRUD + Connection + Schema Extraction + Memory) |
| 4 | [프론트엔드](./04_frontend.md) | `workspace/Database/` 3컴포넌트 + API 클라이언트 |
| 5 | [설정](./05_configuration.md) | License, 권한, 연결 파라미터, 의존 서비스 |

## 퀵 스타트

### 1. License 확인

`dbsphere`는 license feature gate가 걸려있다 (`require_feature("dbsphere")`). 관리자 계정에서 **Settings → License**에서 해당 feature가 활성화되어 있어야 한다.

### 2. DbSphere 생성 (Workspace → Database → New)

1. Workspace → Database → **New Database**
2. DB Type 선택 (postgresql, mysql, mssql, oracle, snowflake, databricks, synapse, fabric 중 하나)
3. 연결 정보 입력 (`host`, `port`, `database`, `username`, `password`)
4. DB 종속 옵션 입력 (예: Snowflake → `warehouse`, `account`, `role`)
5. **Test Connection**으로 연결 검증
6. 저장

### 3. Agent에 연결

Workspace → Agents → (Agent 편집) → **Database** 섹션에서 방금 생성한 DbSphere 선택.

### 4. 대화

Agent로 채팅 시작하면 에이전트가 자동으로:
1. 사용자 질문을 정규화(normalized_question)
2. 메모리에서 유사 SQL 예시 검색 (`SearchEngineDbSphereMemory`)
3. 스키마 컨텍스트와 함께 SQL 생성 (`dynamic_system_prompt`)
4. `run_sql` 도구로 실행 → CSV 저장
5. `visualize_data` 도구로 Plotly 차트 생성
6. SSE 스트리밍 응답

## 주요 기능

| 기능 | 설명 |
|---|---|
| **NL-to-SQL** | 자연어 → SQL 변환 (ReactAgent + LangGraph) |
| **8종 DB 지원** | Postgres/MySQL/MSSQL/Oracle/Snowflake/Databricks/Synapse/Fabric |
| **스키마 자동 추출** | LLM이 테이블/컬럼을 분석하여 설명 생성 (`schema_extractor.py`) |
| **메모리 기반 학습** | Question-SQL 쌍, DDL, 문서, 예제를 `search_engine`에 저장 |
| **자동 시각화** | Plotly 기반 차트 자동 타입 선택 (bar/line/pie/scatter/table/histogram/heatmap/grouped_bar) |
| **Dashboard Builder** | 스키마 분석 → 카드+차트 패널 자동 생성 에이전트 (`dashboard_builder_agent.py`, 2026-04 신규) |
| **비밀번호 암호화** | 저장 시 `encrypt_value`, 응답 시 마스킹 |
| **Access Control** | 그룹/사용자별 read/write 권한 (JSON 필드) |

## 관련 코드 경로

- **Router**: `backend/open_webui/routers/dbsphere.py` (22 endpoints)
- **Model**: `backend/open_webui/models/dbsphere.py` (`DbSphere`, `DbSphereModel`, `DbSphereForm`)
- **Extension**: `backend/extension_modules/dbsphere/`
  - `dbsphere_agent.py` — 메인 NL-to-SQL 에이전트 (`ReactAgentBase` 상속)
  - `dashboard_builder_agent.py` — 대시보드 자동 생성 에이전트 (2026-04 신규)
  - `dbsphere_state.py` — `DBConfig`, `DBType`, `DBSphereAgentState`
  - `prompts.py` — 시스템/쿼리 정규화/최종 답변 프롬프트
  - `sql_runners/` — base + 8 DB별 runner
  - `memory/` — `SearchEngineDbSphereMemory`, `schema_extractor`
  - `chart/plotly_generator.py` — Plotly 차트 생성
  - `tools/` — run_sql, visualize_data, dashboard_tools, get_table_details, dbsphere_info
- **Frontend**: `src/lib/components/workspace/Database/`
  - `CreateDatabase.svelte`, `DbSphereDetail.svelte`, `MemoryEditModal.svelte`
- **API Client**: `src/lib/apis/dbsphere/index.ts`
- **Migrations**:
  - `9c1d2e3f4a5b_add_dbsphere_and_glossary_tables.py` — 초기 테이블 생성
  - `f7a8b9c0d1e2_add_dbsphere_schema_extraction_fields.py` — `auto_extract_model`, `sample_row_count`, `last_extracted_at` 컬럼 추가

## 변경 이력

| 날짜 | 변경 | 관련 |
|---|---|---|
| 2026-04-08 | 문서 전면 재작성 (신스타일 마이그레이션, 8 DB 타입/22 endpoints/dashboard_builder 반영, Vanna.ai 레거시 제거) | `docs/eng-docs-refresh` 브랜치 |
| 2026-04-08 | `dashboard_builder_agent.py` 신규 추가 (코드) | — |
| 2026-03-19 | Oracle/Snowflake/Databricks/Synapse/Fabric SQL Runner 추가 | — |
| 2026-01-30 | 초기 문서 작성 (Vanna.ai 기반 설명, 현재는 폐기됨) | — |
