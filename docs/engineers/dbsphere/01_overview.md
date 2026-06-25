> Last Updated: 2026-04-08

# 01. DBSphere 개요

## 목적

SQL 지식이 없는 사용자도 자연어로 DB를 질의하고, 결과를 자동 시각화하여 인사이트를 얻을 수 있게 하는 것. DBSphere는 각 DbSphere 레코드마다 독립된 연결/스키마/메모리를 가지며, 관리자가 워크스페이스에서 등록하면 에이전트가 자동으로 해당 DB 컨텍스트에서 동작한다.

## 핵심 개념

| 용어 | 설명 |
|---|---|
| **DbSphere** | DB 연결 + 스키마 메타데이터 + 메모리 설정을 묶은 리소스 (DB 테이블 1행). Workspace에서 CRUD 가능. |
| **DBConfig** | DbSphere의 연결 정보를 런타임에 로드한 Pydantic 모델 (`dbsphere_state.py`). 8종 DB별 선택 필드를 포함. |
| **DBSphereAgent** | `ReactAgentBase` 상속, LangChain create_agent로 구성된 ReAct 에이전트. SQL 생성·실행·시각화 루프를 담당. |
| **SqlRunnerBase** | 8개 DB별 실행기의 공통 부모 클래스. `connect`, `execute`, `get_schema_ddl`, `close` 메서드. |
| **SearchEngineDbSphereMemory** | 단일 벡터 인덱스(`dbsphere_memory`)에 `dbsphere_id`와 `entity_type`로 구분하여 저장하는 메모리 시스템. |
| **Entity Types** | `sql_memory` (Q-SQL 쌍), `ddl_schema` (테이블/컬럼+설명), `documentation` (업무 용어), `sql_example` (설명 포함 예제) |
| **Schema Extractor** | LLM이 스키마를 분석하여 테이블/컬럼 설명을 자동 생성하는 모듈. Background task로 실행됨. |
| **Dashboard Builder Agent** | 스키마를 분석하여 의미 있는 카드+차트 패널을 자동 생성하는 별개 에이전트 (`dashboard_builder_agent.py`, 2026-04 신규). |

## 데이터 흐름 (NL 질문 → 응답)

```
[User] "지난 달 매출 상위 10개 제품"
   │
   ▼
DBSphereAgent.run(request, payload, metadata, user)
   │
   ├─▶ DbSpheres.get_dbsphere_by_id(dbsphere_id)   ← metadata에서 dbsphere_id 추출
   │      │
   │      └─▶ DBConfig.from_dbsphere_data(data)     ← 연결 정보 복원
   │
   ├─▶ SqlRunner = PostgresRunner(config)            ← DB 타입별 인스턴스
   │
   ├─▶ SearchEngineDbSphereMemory.search(question)
   │      ├─▶ ddl_schema         → schema_info
   │      └─▶ sql_memory/example → similar_queries
   │
   ├─▶ create_agent(tools=[run_sql, visualize_data],
   │                middleware=[dynamic_system_prompt])
   │      │
   │      │   dynamic_system_prompt(state):
   │      │     - dialect = state.db_dialect
   │      │     - schema_ddl = state.schema_info
   │      │     - similar_queries = state.similar_queries_text
   │      │
   │      ▼
   │   [LLM] → SQL 생성 → run_sql 호출
   │            │
   │            ▼
   │   [Runner.execute(sql)] → rows + columns → CSV 저장
   │            │
   │            ▼
   │   [LLM] → visualize_data 호출 (csv_path + chart_type + x,y)
   │            │
   │            ▼
   │   [PlotlyChartGenerator.generate()] → Plotly JSON
   │
   ├─▶ StreamingResponse (SSE)
   │      ├─▶ ```sql ... ```          (생성된 SQL)
   │      ├─▶ text chunks              (LLM 분석)
   │      └─▶ ```html ... ```          (Plotly HTML)
   │
   └─▶ Usages.log(user_id, dbsphere_id, usage_data)   ← 감사 로그
```

## 모듈 구조

```
backend/extension_modules/dbsphere/
├── __init__.py
├── dbsphere_agent.py           # 메인 NL-to-SQL 에이전트 (ReactAgentBase)
├── dashboard_builder_agent.py  # 대시보드 자동 생성 에이전트 (2026-04 신규)
├── dbsphere_state.py           # DBConfig, DBType, DBSphereAgentState
├── prompts.py                  # 시스템/정규화/최종 답변 프롬프트
├── sql_runners/
│   ├── base.py                 # SqlRunnerBase (ABC)
│   ├── postgres.py
│   ├── mysql.py
│   ├── mssql.py
│   ├── oracle.py
│   ├── snowflake.py
│   ├── databricks.py
│   ├── synapse.py
│   └── fabric.py
├── memory/
│   ├── models.py               # MemoryType, UnifiedSearchResult
│   ├── search_memory.py        # SearchEngineDbSphereMemory
│   └── schema_extractor.py     # LLM 기반 스키마 설명 생성
├── chart/
│   └── plotly_generator.py     # PlotlyChartGenerator
└── tools/
    ├── run_sql.py              # create_run_sql_tool()
    ├── visualize_data.py       # create_visualize_data_tool()
    ├── dashboard_tools.py      # card_panel, chart_panel, set_layout 등 (dashboard_builder용)
    ├── get_table_details.py
    ├── dbsphere_info.py
    └── schemas.py
```

## 다른 모듈과의 관계

| 모듈 | 관계 |
|---|---|
| `extension_modules/react` | `DBSphereAgent`, `DashboardBuilderAgent`가 `ReactAgentBase`를 상속 |
| `extension_modules/search_engine` | 메모리 저장/검색에 `search_engine`의 Vector DB 추상화 사용 |
| `open_webui/models/models` | Agent 모델에서 DbSphere를 metadata로 연결 |
| `open_webui/models/usage` | 쿼리 실행 시 `Usages.log()`로 사용량 기록 |
| `open_webui/models/message_trace` | `RunType.dbsphere`로 trace 분류 |
| `open_webui/utils/license` | `require_feature("dbsphere")` 데코레이터로 전체 라우터 gating |
| `open_webui/utils/crypto` | 저장 시 `encrypt_value`, 응답 시 `mask_sensitive_value` |
