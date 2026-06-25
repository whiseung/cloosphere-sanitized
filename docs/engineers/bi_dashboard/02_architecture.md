> Last Updated: 2026-04-08

# 02. BI Dashboard 아키텍처

## 1. 데이터베이스 모델

### `bi_dashboard` 테이블

```python
# backend/open_webui/models/bi_dashboard.py

class BiDashboard(Base):
    __tablename__ = "bi_dashboard"

    id = Column(Text, unique=True, primary_key=True)    # UUID
    user_id = Column(Text)                              # 생성자
    name = Column(Text)
    description = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)                  # 레이아웃, 필터, 메타 (panels는 bi_panel 테이블)
    meta = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)
    share_id = Column(Text, unique=True, nullable=True) # 공유 URL UUID (NULL이면 비공개)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### `data` JSON 서브 구조

```json
{
  "layout": [
    {"i": "panel-uuid-1", "x": 0, "y": 0, "w": 6, "h": 4},
    {"i": "panel-uuid-2", "x": 6, "y": 0, "w": 6, "h": 4}
  ],
  "filters": [
    {"label": "Date", "type": "date_range", "field": "created_at", "from_value": "...", "to_value": "..."},
    {"label": "Model", "type": "select", "field": "model_id", "value": "gpt-4"}
  ],
  "time_range": "7d",
  "meta": {}
}
```

### `bi_panel` 테이블

```python
class BiPanel(Base):
    __tablename__ = "bi_panel"

    id = Column(Text, unique=True, primary_key=True)   # UUID
    dashboard_id = Column(Text)                         # FK (not enforced at DB level)
    user_id = Column(Text)                              # 생성자
    name = Column(Text)
    description = Column(Text, nullable=True)
    dbsphere_id = Column(Text)                          # 데이터 소스 DbSphere
    data = Column(JSON, nullable=True)                  # sql, chart_type, x/y, color 등
    meta = Column(JSON, nullable=True)                  # panel type, status 등
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### `data` JSON — Card Panel

```json
{
  "type": "card",
  "sql": "SELECT COUNT(*) as total FROM orders WHERE created_at BETWEEN '2026-03-01' AND '2026-03-31'",
  "sql_template": "SELECT COUNT(*) as total FROM orders WHERE created_at BETWEEN $st AND $ed",
  "value_column": "total",
  "format": "number",
  "color": "#3B82F6",
  "icon": "trending-up"
}
```

### `data` JSON — Chart Panel

```json
{
  "type": "chart",
  "chart_type": "bar",
  "sql": "...",
  "sql_template": "SELECT model_id, COUNT(*) as req FROM log_usage WHERE created_at BETWEEN $st AND $ed GROUP BY model_id ORDER BY req DESC LIMIT 10",
  "x_column": "model_id",
  "y_column": "req",
  "title": "Top 10 Models by Request Count",
  "last_result": {
    "x": ["gpt-4", "claude-3.5", ...],
    "y": [1234, 987, ...],
    "executed_at": 1712000000
  }
}
```

## 2. Auto-Build Agent (`dashboard_builder_agent.py`)

### 위치

`backend/extension_modules/dbsphere/dashboard_builder_agent.py` — DBSphere 하위 모듈로 배치 (공통 infrastructure 공유).

### 클래스 시그니처

```python
class DashboardBuilderAgent(ReactAgentBase):
    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
        dbsphere_ids: List[str],     # ← 복수! 여러 DbSphere를 동시에 데이터 소스로 사용 가능
    ):
        ...
        self.dbsphere_ids = dbsphere_ids
        self.sql_runners: Dict[str, Any] = {}       # dbsphere_id → SqlRunner
        self.schema_info_map: Dict[str, str] = {}   # dbsphere_id → 스키마 DDL/설명
        self.dbsphere_names: Dict[str, str] = {}    # dbsphere_id → 표시 이름
```

> **핵심**: `DBSphereAgent`는 단일 DbSphere에 바인딩되지만, `DashboardBuilderAgent`는 **복수의 DbSphere를 동시에** 처리할 수 있어 **서로 다른 DB를 조합한 대시보드** 생성이 가능합니다 (예: `sales_db` + `users_db`에서 각각 card/chart 생성).

### `load_data_sources()` 흐름

```python
for dbsphere_id in self.dbsphere_ids:
    dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
    data = decrypt_connection_password(copy.deepcopy(dbsphere.data))
    db_config = DBConfig.from_dbsphere_data(data)
    runner = self._create_sql_runner_for_config(db_config)

    if runner:
        self.sql_runners[dbsphere_id] = runner
        # Live schema 조회 시도
        try:
            schema = await runner.get_schema_info()
            self.schema_info_map[dbsphere_id] = schema
        except Exception:
            # Fallback: dbsphere.data["schema_summary"] + "table_overview"
            ...
    else:
        # Runner 생성 실패해도 pre-extracted schema가 있으면 사용
        fallback = dbsphere.data.get("schema_summary") + dbsphere.data.get("table_overview")
        self.schema_info_map[dbsphere_id] = fallback
```

### 두 개의 시스템 프롬프트

파일 내에 **2종의 프롬프트 상수**가 정의되어 있음:

| 상수 | 용도 | 엔드포인트 |
|---|---|---|
| `DASHBOARD_BUILDER_SYSTEM_PROMPT` | **Batch 모드** — 한 번에 완전한 대시보드 생성 (질문 없음) | `POST /auto-build` |
| `DASHBOARD_BUILDER_CHAT_PROMPT` | **Chat 모드** — 다중 턴 대화, `ask_user` 도구 포함, 기존 대시보드 수정 지원 | `POST /auto-build/chat` |

**Chat 프롬프트의 추가 동작**:
- `ask_user` 도구 사용 규칙: 필요할 때만 질문 (어떤 DB 쓸지, 대시보드 의도가 모호할 때). chart type/색상/레이아웃은 자동 결정.
- **Modify existing dashboard** 지원: 기존 panel 보존, 변경/삭제 요청 시 `delete_panel` → 새로 `create_*_panel` 순서로 처리.
- "ALWAYS respond in the same language as the user" — 다국어 대응.

### 공통 시스템 프롬프트 원칙

두 프롬프트 모두 다음 원칙을 강제:

```
1. 스키마 분석 → key business metrics 식별
2. 3-5개 card panel 생성 (totals, counts, averages)
3. 3-5개 chart panel 생성 (trends, distributions, comparisons)
4. 차트 panel 생성 시 필수 절차:
   a) SQL을 run_sql로 1차 검증 (날짜 필터 없이)
   b) 날짜 WHERE절 추가 후 run_sql로 2차 검증
   c) 2차 SQL의 날짜 값을 $st/$ed로 치환 → sql_template
   d) create_chart_panel(sql, sql_template, chart_type, x, y)
5. 차트 타입 다양화 강제 — bar/line/pie/area/table/histogram/heatmap/grouped_bar 골고루
6. 완료 후 set_dashboard_layout(grid 12 cols)
```

### 도구 세트 (`tools/dashboard_tools.py`)

| 도구 | 역할 |
|---|---|
| `create_card_panel_tool` | KPI 카드 panel 생성 (sql, sql_template, value_column, format, color, icon) |
| `create_chart_panel_tool` | 차트 panel 생성 (sql, sql_template, chart_type, x, y, title, color 등) |
| `create_delete_panel_tool` | panel 삭제 |
| `create_set_layout_tool` | 레이아웃 배치 (12-col grid) |
| `create_set_existing_layout_tool` | 기존 레이아웃 로드 (수정 모드) |
| `create_ask_user_tool` | 모호할 때 사용자에게 선택지 제공 (interactive) |
| `create_run_sql_tool` | SQL 실행 검증 (DBSphere에서 재사용) |

### `DashboardBuilderState`

```python
class DashboardBuilderState(TypedDict):
    dashboard_id: str
    dbsphere_id: str
    current_panels: List[Dict]
    layout: List[Dict]
    schema_info: str
    time_range: str
    db_config: DBConfig
```

## 3. NL→SQL 검증 흐름 (Panel 생성)

Panel 생성 시 사용자는 자연어로 설명을 작성하면 백엔드가 DBSphereAgent를 호출해 SQL을 생성한 뒤 검증한다.

```
POST /{dashboard_id}/panels/create
  │
  ├─▶ BiPanels.insert_new_panel()            # status=pending
  │
  ├─▶ POST /generate-sql (internal)
  │     │
  │     └─▶ DBSphereAgent 인스턴스화 (dbsphere_id 기반)
  │           ├─▶ DBSphere 스키마 컨텍스트 로드 (memory + schema_extractor)
  │           ├─▶ LLM 호출 → SQL 생성
  │           └─▶ SQL 리턴
  │
  ├─▶ POST /execute-sql (internal)
  │     │
  │     └─▶ SqlRunnerBase.execute(sql) → rows + columns
  │
  ├─▶ Plotly spec 생성 (chart_type에 따라 x/y 자동 매핑)
  │
  └─▶ BiPanels.update_panel_data() → data={sql, sql_template, chart_type, ...}
  ↓
응답: panel + 초기 실행 결과
```

## 4. Share Link 동작

### 발급 흐름

```
POST /{dashboard_id}/share
  ↓
share_id = uuid.uuid4()
BiDashboards.update_share_id(dashboard_id, share_id)
  ↓
응답: {"share_id": "uuid", "url": "/shared/{uuid}"}
```

### 공개 접근

```
GET /shared/{share_id}
  ↓
BiDashboards.get_by_share_id(share_id)      # 인증 없이 조회
  ↓
응답: read-only dashboard view (현재 저장된 panel + last_result)
```

### 공유 모드 SQL 실행

공유 뷰에서도 time range를 바꿔 실시간 갱신이 가능해야 하므로 별도 엔드포인트가 있다:

```
POST /shared/{share_id}/execute-sql
  body: {panel_id, time_range}
  ↓
검증: share_id 유효성 + panel이 해당 dashboard에 속하는지
  ↓
panel.sql_template의 $st/$ed 치환 → SQL 실행 → 결과 반환
```

**보안**: 공유 뷰는 저장된 `sql_template`만 실행 가능. 사용자가 임의의 SQL을 주입할 수 없다.

## 5. HTML Export

`POST /{dashboard_id}/export-html` — 대시보드의 현재 상태를 **독립 실행 가능한 HTML 파일**로 export한다.

- Plotly CDN + 인라인 chart data
- Static snapshot (time range 고정)
- Offline 공유용 (이메일 첨부 등)

## 6. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| Panel 생성 시 "SQL validation failed" | LLM이 스키마에 없는 컬럼/테이블 참조 | DbSphere의 스키마 추출 (`POST /dbsphere/{id}/extract-schema`) 먼저 실행 |
| Auto-Build가 모든 차트를 bar type으로 생성 | 시스템 프롬프트의 diversity 규칙을 LLM이 무시 | Task Model을 더 유능한 모델로 변경 (GPT-4, Claude Sonnet 권장) |
| Time range 변경 시 panel이 빈 결과 반환 | `$st`/`$ed` placeholder가 SQL에 없거나 자료형 불일치 | `sql_template`에 정확히 `$st`/`$ed` 문자열이 있는지 확인. 날짜 컬럼 타입이 string이면 `CAST($st AS DATE)` 필요 |
| Share URL 접근 시 404 | `share_id`가 revoke됨 (`DELETE /share`) | 대시보드 소유자에게 문의, 재발급 필요 |
| Dashboard 저장은 되나 panel이 안 보임 | `dashboard.data.layout`에 panel_id가 누락 | `set_dashboard_layout()` 재호출 또는 프론트엔드 수동 배치 |
| Plotly 렌더링 오류 "undefined x" | panel.data에 `x_column` 없음 | PanelEditor에서 x/y 컬럼을 명시적으로 선택 |
| Auto-Build 응답이 매우 느림 | LLM이 많은 도구를 순차 호출 (3-5 cards + 3-5 charts + layout = 10+ 호출) | Task Model을 fast 모델로 변경, 또는 panels 개수 제한 옵션 추가 검토 |
| 공유 뷰에서 "Unauthorized" | `share_id`가 NULL이거나 삭제된 dashboard | 소유자가 다시 `POST /{dashboard_id}/share` 호출 |
