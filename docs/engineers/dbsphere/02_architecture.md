> Last Updated: 2026-04-08

# 02. DBSphere 아키텍처

## 1. 데이터베이스 모델

### `dbsphere` 테이블 (`backend/open_webui/models/dbsphere.py`)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | Text PK | UUID4 |
| `user_id` | Text | 소유자 (multi-tenancy) |
| `name` | Text | DbSphere 이름 |
| `description` | Text | 설명 |
| `data` | JSON nullable | 연결 정보(`connection`), 추출된 스키마(`extracted_schema`), 추출 job 상태(`extraction_job`) 등 |
| `meta` | JSON nullable | 추가 메타데이터 |
| `access_control` | JSON nullable | 그룹/사용자 read/write 권한 (규약은 `open_webui/utils/access_control.py`) |
| `auto_extract_model` | Text nullable | 스키마 추출에 사용할 모델 ID |
| `sample_row_count` | BigInteger (기본 5) | 스키마 추출 시 샘플링할 row 수 |
| `last_extracted_at` | BigInteger nullable | 마지막 스키마 추출 완료 시점 (epoch) |
| `created_at` | BigInteger | 생성 시점 (epoch) |
| `updated_at` | BigInteger | 수정 시점 (epoch) |

### `data` JSON 서브 구조

```json
{
  "connection": {
    "db_type": "postgresql",
    "host": "...",
    "port": 5432,
    "database": "...",
    "username": "...",
    "password": "encrypted:...",
    "schema_name": "public",
    "warehouse": null,
    "account": null,
    "role": null,
    "service_name": null,
    "dsn": null,
    "http_path": null,
    "catalog": null,
    "access_token": null,
    "tenant_id": null,
    "client_id": null,
    "client_secret": null,
    "use_managed_identity": false
  },
  "extracted_schema": {
    "tables": [ ... ],
    "ddl": "..."
  },
  "extraction_job": {
    "status": "idle | running | completed | failed",
    "started_at": 1234567890,
    "progress": 0,
    "error": null
  }
}
```

**참고**: `password`, `access_token`, `client_secret`은 저장 시 `encrypt_value()`로 암호화되며, 응답 시 `mask_sensitive_value()`로 마스킹된다 (`utils/crypto.py`).

### 마이그레이션

| Migration | 내용 |
|---|---|
| `9c1d2e3f4a5b_add_dbsphere_and_glossary_tables.py` | 초기 `dbsphere` 테이블 생성 |
| `f7a8b9c0d1e2_add_dbsphere_schema_extraction_fields.py` | `auto_extract_model`, `sample_row_count`, `last_extracted_at` 컬럼 추가 |

---

## 2. DBSphereAgent (메인 에이전트)

### 클래스 구조

`DBSphereAgent`는 `ReactAgentBase` (from `extension_modules/react/react_base.py`)를 상속받아 LangChain의 `create_agent`로 ReAct 에이전트를 구성한다.

```python
# dbsphere_agent.py (핵심 임포트)
from extension_modules.react.react_base import ReactAgentBase
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt

class DBSphereV2AgentState(DBSphereAgentState):
    db_dialect: str = "PostgreSQL"

@dynamic_prompt
def dynamic_system_prompt(request: ModelRequest) -> str:
    state = request.state
    return get_dbsphere_system_prompt(
        dialect=state.get("db_dialect", "PostgreSQL"),
        schema_ddl=state.get("schema_info", ""),
        similar_queries=state.get("similar_queries_text", ""),
        ...
    )
```

### AgentState (`dbsphere_state.py`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `messages` | `List[BaseMessage]` | 대화 메시지 (상위 `AgentStateBase`에서 상속) |
| `normalized_question` | `str` | 정규화된 질문 (대명사 해결, 맥락 통합) |
| `executed_sql` | `str` | 마지막 실행된 SQL |
| `query_result_file` | `str` | 쿼리 결과 CSV 파일 경로 |
| `chart_data_list` | `List[Dict]` | 다중 차트 누적 (복수 시각화 지원) |
| `schema_info` | `str` | DB 스키마 DDL 문자열 |
| `similar_queries` | `List[Dict]` | 메모리 검색 결과 (Q-SQL pairs) |
| `query_history` | `List[str]` | 세션 내 쿼리 이력 |

### 실행 루프

1. `run(request, payload, metadata, user)` 진입
2. `_get_dbsphere_id_from_metadata()` 로 dbsphere_id 추출 (아래 "Metadata 해석 순서" 참조)
3. `DbSpheres.get_dbsphere_by_id(id)` → `decrypt_connection_password(data)` → `DBConfig.from_dbsphere_data(data)`
4. `db_type` 기반으로 적절한 `SqlRunnerBase` 구현체 선택 (Postgres/MySQL/MSSQL/…)
5. `SearchEngineDbSphereMemory(dbsphere_id)` 인스턴스화 → 유사 쿼리 검색
6. LangChain tools 등록: `create_run_sql_tool(runner)`, `create_visualize_data_tool(chart_generator)`
7. `create_agent(tools, middleware=[dynamic_system_prompt])` → ReAct 에이전트
8. 에이전트 실행 → SSE 스트리밍 응답 (SQL / 텍스트 / HTML 차트)
9. `Usages.log()` 로 사용량 기록, `RunType.dbsphere` trace 생성

### Metadata 해석 순서 (`_get_dbsphere_id_from_metadata`)

DBSphereAgent는 여러 metadata 소스를 폴백 순서로 확인한다:

1. **Primary**: `self.agent_config.get_first_dbsphere_id()` — `ReactAgentBase`의 `AgentConfig` 통합 (신규 패턴)
2. **Legacy 1**: `metadata.model.info.meta.dbspheres` 또는 `metadata.model.info.meta.dbsphere` — 리스트/dict/string 모두 허용 (backward compat)
3. **Legacy 2**: `metadata.enhanced_params.dbsphere_id` — 플로우 빌더에서 파라미터로 전달되는 경우

선순위 일치 시 즉시 반환. 여러 Agent가 `meta.dbspheres`에 복수 DbSphere를 등록할 수 있지만, DBSphereAgent는 **첫 번째 것만** 사용한다 (다중 DB가 필요한 경우는 `DashboardBuilderAgent` 참조).

### 권한 검증 (`_load_dbsphere_config`)

DBSphereAgent는 DbSphere 로드 직전에 사용자 권한을 재검증한다:

```python
user = Users.get_user_by_id(user_id)
if user.role != "admin":
    user_dbspheres = DbSpheres.get_dbspheres_by_user_id(user_id, "read")
    if self.dbsphere_id not in [db.id for db in user_dbspheres]:
        return None   # 로그 경고 후 None 반환 → 에이전트 실행 중단
```

즉 **사용자가 에이전트를 통해 간접적으로** 권한 없는 DbSphere에 접근하는 것을 방지한다.

### Working Directory

쿼리 결과(CSV)는 로컬 디스크에 임시 저장된다:

```python
self.working_directory = "data/cache/dbsphere_v2"   # 리팩토링 전 이름 유지 (레거시 호환)
os.makedirs(self.working_directory, exist_ok=True)
```

**주의**: 경로가 `dbsphere_v2`로 되어 있는 것은 **리팩토링 이전 이름**이 cache 디렉토리에 남아 있기 때문 (파일 시스템 호환성을 위해 변경 안 됨). 실제 코드는 `backend/extension_modules/dbsphere/`에 위치.

---

## 3. SQL Runner (DB별 실행기)

### `SqlRunnerBase` (ABC — `sql_runners/base.py`)

```python
class SqlRunnerBase(ABC):
    def __init__(self, config: DBConfig): ...
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def execute(self, sql: str) -> Tuple[List[Dict], List[str]]: ...
    @abstractmethod
    def get_schema_ddl(self, tables: Optional[List[str]] = None) -> str: ...
    @abstractmethod
    def close(self) -> None: ...
```

### 8종 구현체

| Runner | DB 타입 | 필수 추가 필드 | 특이사항 |
|---|---|---|---|
| `PostgresRunner` | `postgresql` | — | `psycopg2` |
| `MySQLRunner` | `mysql` | — | `pymysql` |
| `MSSQLRunner` | `mssql` | — | `pymssql` |
| `OracleRunner` | `oracle` | `service_name` 또는 `dsn` | `oracledb` / cx_Oracle |
| `SnowflakeRunner` | `snowflake` | `account`, `warehouse`, (`role`) | `snowflake-connector-python` |
| `DatabricksRunner` | `databricks` | `http_path`, `catalog`, `access_token` (PAT) | `databricks-sql-connector` |
| `SynapseRunner` | `synapse` | Azure AD (`tenant_id`, `client_id`, `client_secret` 또는 managed identity) | Azure Synapse Dedicated/Serverless SQL Pool |
| `FabricRunner` | `fabric` | Azure AD (동일) | Microsoft Fabric SQL endpoint |

**주의**: `DBType` enum에는 `SQLITE`도 포함되나 현재 SQLite 전용 Runner는 존재하지 않는다 (2026-04-08 기준). 추가 예정이거나, PostgresRunner/기본 경로로 폴백 처리될 가능성 있음. 실제 사용 전 확인 필요.

---

## 4. Memory System

### `SearchEngineDbSphereMemory` (`memory/search_memory.py`)

**단일 벡터 인덱스**에 `dbsphere_id` 필터와 `entity_type` 구분자로 모든 메모리를 저장하는 통합 구조.

**인덱스 이름**: `dbsphere_memory` (Vector DB — Azure Search / pgvector / ES / Vertex, `extension_modules/search_engine` 통해 추상화)

**Entity Types** (`memory/models.py::MemoryType`):

| Entity Type | 용도 |
|---|---|
| `sql_memory` | 과거 성공적으로 실행된 Question-SQL 쌍. 유사 질문 검색 시 few-shot 예시로 활용 |
| `ddl_schema` | 테이블/컬럼 정의 + LLM이 생성한 한국어 설명 (schema_extractor가 생성) |
| `documentation` | 업무 용어, 정책, 도메인 지식 (관리자가 수동 추가 가능) |
| `sql_example` | 설명 포함 SQL 예제 (특정 패턴을 LLM에게 가르치는 용도) |

### Schema Extractor (`memory/schema_extractor.py`)

1. `auto_extract_model`로 지정된 LLM 인스턴스화
2. DB에서 테이블 목록 + 샘플 row (`sample_row_count`) 조회
3. LLM에 테이블 단위 프롬프트 전송 → 한국어 설명 생성
4. 생성된 설명을 `ddl_schema` entity type으로 `dbsphere_memory` 인덱스에 upsert
5. 완료 시 `dbsphere.data["extraction_job"]` 상태 업데이트 (atomic, row-level lock 사용: `with_for_update()`)
6. `dbsphere.last_extracted_at` 갱신

**Background task**로 실행되므로 `GET /{id}/extraction-status`로 진행 상황 폴링 가능.

---

## 5. Chart Generation

### `PlotlyChartGenerator` (`chart/plotly_generator.py`)

CSV/DataFrame을 입력받아 Plotly JSON spec을 생성한다. Chart type 자동 선택 휴리스틱을 내장.

**지원 차트 유형**:

| 유형 | 적합한 데이터 | 자동 선택 조건 |
|---|---|---|
| `bar` | 범주별 비교 | 카테고리 컬럼 + 수치 컬럼 (기본) |
| `line` | 시계열 추세 | X축이 datetime 타입 |
| `pie` | 비율 (5개 이하 카테고리) | 범주형 + row ≤ 10 + unique ≤ 5 |
| `scatter` | 상관관계 | 수치 2개 |
| `area` | 누적 추세 | 명시적 요청 시 |
| `histogram` | 값 분포 | X축만 수치, Y축 없음 |
| `heatmap` | 2D 매트릭스 | 2 카테고리 + 1 수치 (dashboard_builder 전용) |
| `grouped_bar` | 다중 시리즈 비교 | 2+ 카테고리 + 1 수치 (dashboard_builder 전용) |
| `table` | 4+ 컬럼 | 컬럼 많을 때 기본값 |

**차트 결정 순위**:
1. 사용자가 `chart_type`을 명시 → 해당 타입 사용
2. 없으면 `auto_select_chart_type()`으로 데이터 특성 기반 자동 선택

---

## 6. Dashboard Builder Agent

`dashboard_builder_agent.py` (2026-04 신규)는 DbSphere 스키마를 분석하여 **대시보드를 자동 생성**하는 별개 에이전트다. `DBSphereAgent`와 구조는 유사하나 목적이 다르다.

### 특징

- `ReactAgentBase` 상속
- 에이전트 루프: 스키마 분석 → 3-5개 card panel + 3-5개 chart panel 생성 → `set_dashboard_layout`으로 12컬럼 그리드에 배치
- **Time filter with SQL template**: 모든 panel은 `$st`, `$ed` placeholder를 가진 `sql_template`을 저장해야 함 (1d/7d/30d 필터 지원)
- 다양한 차트 타입을 강제 (bar/line/pie/area/table/histogram/heatmap/grouped_bar 골고루)

### Panel 생성 도구 (`tools/dashboard_tools.py`)

| 도구 | 역할 |
|---|---|
| `create_card_panel_tool` | KPI 카드 패널 (단일 수치 + 색상) |
| `create_chart_panel_tool` | 차트 패널 (sql + sql_template + chart_type + x/y) |
| `create_delete_panel_tool` | 패널 삭제 |
| `create_set_layout_tool` | 12-col 그리드 레이아웃 설정 |
| `create_set_existing_layout_tool` | 기존 레이아웃 로드 |
| `create_ask_user_tool` | 사용자에게 선택지 질문 |

**검증 단계**: 차트 panel 생성 전 반드시 `run_sql`로 1차 (필터 없이), 2차 (날짜 필터 포함)를 검증한 뒤 `$st`/`$ed` 템플릿으로 치환한다.

---

## 7. Refactor History (Vanna.ai → LangChain/LangGraph)

`dbsphere`는 초기에 [Vanna.ai](https://vanna.ai/) 프레임워크 위에 구축되었으나, 2026-01~02에 **LangChain/LangGraph + ReactAgentBase** 기반으로 완전 리팩토링되었다. 리팩토링의 배경과 차이점을 기록한다.

### 변경 요약

| 영역 | 구 (Vanna 기반) | 신 (LangChain 기반) |
|---|---|---|
| **Framework** | Vanna.ai core + custom tools | LangChain `create_agent` + `@dynamic_prompt` middleware |
| **Agent base** | Vanna 커스터마이징 | `ReactAgentBase` (자체 베이스) |
| **Tool 시스템** | Vanna Tools 확장 | LangChain `StructuredTool` |
| **Memory** | `AzureAISearchAgentMemory` (Azure AI Search 직접) | `SearchEngineDbSphereMemory` (`search_engine` 모듈 경유, Vector DB 추상화) |
| **SQL Runner** | 단일 구현 | DB별 8종 분리 (`sql_runners/*.py`) |
| **DB 지원** | Postgres, MySQL | Postgres, MySQL, MSSQL, Oracle, Snowflake, Databricks, Synapse, Fabric |
| **State** | Vanna 내부 관리 | `DBSphereAgentState` (Pydantic, LangGraph 호환) |

### 리팩토링 동기

1. **DB 지원 확장**: Cloosphere 고객사의 엔터프라이즈 DB (Oracle, Snowflake, Databricks, Synapse, Fabric) 요구를 Vanna의 제한된 어댑터로는 대응 어려움
2. **메모리 일관성**: 다른 모듈(`glossary`, `kbsphere`)도 사용하는 `search_engine` 추상화로 통합하여 Vector DB 운영 단일화
3. **LangGraph 생태계**: ReAct 패턴, streaming, middleware 등 LangChain 생태계 도구 활용
4. **테스트 용이성**: Runner/Memory/Chart를 독립 모듈로 분리하여 단위 테스트 가능

### 과거 문서 (`docs/engineers/dbsphere_v2/`)

2026-02에 "V2 리팩토링 계획"으로 별도 문서 폴더(`dbsphere_v2/`)가 만들어졌으나, 실제로는 같은 `dbsphere/` 폴더에서 리팩토링이 진행되었고 별도 `dbsphere_v2/` 코드 폴더는 존재하지 않는다. 해당 문서는 이 섹션으로 요약 병합되고 **2026-04-08에 삭제**되었다. (`docs/eng-docs-refresh` 브랜치)

---

## 8. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `403 Forbidden`이 모든 dbsphere 엔드포인트에서 발생 | License feature `dbsphere`가 비활성 | Settings → License에서 `dbsphere` feature 활성화된 license key 등록 |
| Connection test 실패: "password authentication failed" | 저장된 password가 `encrypted:` prefix인데 복호화 안 되고 그대로 전송됨 | `routers/dbsphere.py::decrypt_connection_password()` 호출 확인. `WEBUI_SECRET_KEY` 변경되면 기존 암호화 값 복호화 불가 — 재입력 필요 |
| Snowflake 연결 시 "Account locator not found" | `account` 필드 누락 | Snowflake DbSphere는 `host`와 별도로 `account` 필수 (`dbsphere_state.py::from_dbsphere_data`) |
| Databricks 연결 시 "Missing HTTP path" | `http_path` 필드 누락 | Databricks SQL Warehouse의 HTTP Path 설정 필요 |
| Synapse/Fabric 인증 실패 | Azure AD credential 불완전 | `tenant_id` + `client_id` + `client_secret` 모두 필요, 또는 `use_managed_identity=true` |
| 스키마 추출이 `running` 상태에서 멈춤 | Background task 예외 발생했으나 상태 미갱신 | `dbsphere.data["extraction_job"]["error"]` 확인. 재시도: `POST /{id}/extract-schema` |
| 차트가 `null` 또는 빈 HTML | `visualize_data` 도구 호출 시 x/y 컬럼명이 CSV 컬럼과 불일치 | LLM 프롬프트에서 실제 컬럼명 지정하도록 유도. `get_dbsphere_system_prompt`의 스키마 정보 확인 |
| 메모리 검색 결과가 없음 | `search_engine`에 `dbsphere_memory` 인덱스 없음 | 관리자: Admin Settings → Search Engine에서 `dbsphere_memory` 인덱스 자동 생성 확인. 또는 첫 스키마 추출 후 생성됨 |
| Dashboard Builder 에이전트가 `create_chart_panel` 실패 | SQL이 `$st`/`$ed` placeholder 없이 제출됨 | `dashboard_builder_agent.py` 시스템 프롬프트 준수 확인 — 반드시 2차 검증 후 템플릿화 필요 |
| 라우터 `require_feature("dbsphere")` 데코레이터가 무효화됨 | `LICENSE_ENFORCEMENT_ENABLED=false` | 개발 환경에서 의도된 경우 무시. 운영에서는 활성화 필요 (`config.py::ENABLE_LICENSE_ENFORCEMENT`) |

---

## 9. 설계 결정

**D1. 단일 인덱스 + `entity_type` 필터** (vs 인덱스당 1 entity type)
- **채택**: 단일 `dbsphere_memory` 인덱스에 `dbsphere_id` + `entity_type`으로 구분
- **이유**: Vector DB 인덱스 생성 비용 (특히 Azure Search) 절감. DbSphere가 많아질수록 인덱스 수 폭증 회피
- **Trade-off**: 쿼리마다 `entity_type` 필터 적용 필요 — 필터 성능 확인 필요

**D2. 비밀번호 암호화는 저장 시점, 마스킹은 응답 시점**
- **채택**: `encrypt_value()` on save, `mask_sensitive_value()` on response
- **이유**: DB 유출 시 평문 노출 방지 + 프론트엔드에 실제 값 전달 금지
- **Trade-off**: `WEBUI_SECRET_KEY` 교체 시 기존 암호화 값 복호화 불가 — 운영 시 키 로테이션 주의

**D3. Background task로 스키마 추출**
- **채택**: `asyncio.Task`로 비동기 실행, `_background_tasks: Set[asyncio.Task]`로 GC 방지
- **이유**: 대형 DB는 수십~수백 테이블 → LLM 호출 수 많음 → 동기 처리 시 timeout
- **Trade-off**: 워커 재시작 시 in-flight job 유실 가능 — 상태를 DB에 atomic 업데이트로 보존

**D4. Dashboard Builder를 별도 에이전트로 분리** (vs DBSphereAgent에 통합)
- **채택**: `dashboard_builder_agent.py`를 독립 클래스로 분리 (2026-04)
- **이유**: Q&A vs 대시보드 생성은 프롬프트/도구/루프 구조가 크게 다름. 섞으면 프롬프트 복잡도 폭증
- **Trade-off**: 코드 중복 (DBConfig 로드, SqlRunner 초기화 등) — 공통 부분을 향후 mixin/helper로 추출 고려
