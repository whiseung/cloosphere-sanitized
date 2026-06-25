> Last Updated: 2026-04-08

# 01. BI Dashboard 개요

## 목적

운영/관리자가 DbSphere에 연결된 **업무 DB (Postgres, Snowflake, MSSQL 등) 에 대한 실시간 대시보드**를 자연어 기반으로 빠르게 구축할 수 있게 한다. Cloosphere의 핵심 NL→SQL 엔진 (DBSphereAgent)을 재활용하여 별도의 BI 툴 없이 Cloosphere 내부에서 시각화 가능.

## 핵심 개념

| 용어 | 설명 |
|---|---|
| **BiDashboard** | 대시보드 리소스 (name, description, data=`{panels, layout, filters}`, share_id). DB table `bi_dashboard` |
| **BiPanel** | 대시보드 내부의 개별 시각화 단위. 한 DbSphere에 바인딩. DB table `bi_panel` |
| **Panel Type** | `card` (단일 KPI) 또는 `chart` (Plotly 차트) |
| **Chart Type** | `bar`, `line`, `pie`, `scatter`, `area`, `table`, `histogram`, `heatmap`, `grouped_bar` |
| **Time Range Filter** | 전역 시간 필터 (1d/7d/30d/custom). panel의 SQL template에 `$st`/`$ed` 치환 |
| **SQL Template** | 저장된 SQL + 시간 필터 placeholder. 갱신 시 `$st`/`$ed`를 현재 선택된 시간 범위로 치환 |
| **Share ID** | public URL용 UUID. 발급된 share_id로는 인증 없이 read-only 접근 가능 |
| **Auto-Build** | DbSphere 스키마를 LLM이 분석하여 3-5개 card + 3-5개 chart panel 자동 생성 (`dashboard_builder_agent.py`) |
| **NL→SQL 검증** | Panel 생성 시 자연어 설명 → DBSphereAgent가 SQL 생성 → `run_sql`로 테스트 → 성공하면 저장 |

## 데이터 흐름 (Panel 생성)

```
[User] "지난 30일간 모델별 요청 수를 bar chart로"
   │
   ▼
POST /api/v1/bi-dashboard/{dashboard_id}/panels/create
   │
   ├─▶ BiPanel 생성 (status=pending)
   │
   ├─▶ POST /generate-sql 내부 호출
   │     │
   │     └─▶ DBSphereAgent (dbsphere_id 로딩)
   │           ├─▶ 스키마 컨텍스트 로드
   │           ├─▶ LLM이 SQL 생성
   │           └─▶ run_sql 도구로 실행 검증
   │
   ├─▶ 검증 성공 → panel.data에 {sql, sql_template, chart_type, x, y, ...} 저장
   │
   └─▶ 응답: panel 객체 + 첫 실행 결과 (chart_data)
```

## 데이터 흐름 (Auto-Build)

```
[Admin] "매출 분석 대시보드 만들어줘"
   │
   ▼
POST /api/v1/bi-dashboard/auto-build/chat
   │
   ├─▶ BiDashboard 생성 (빈 dashboard)
   │
   └─▶ DashboardBuilderAgent(dbsphere_ids=[...])   ← 복수 가능!
         │
         ├─▶ load_data_sources()
         │     └─ 각 dbsphere_id별로:
         │         SqlRunner 생성 → live schema 조회 (실패 시 pre-extracted schema fallback)
         │
         ├─▶ 스키마 분석 → key metrics 식별 (여러 DB 교차 분석 가능)
         ├─▶ create_card_panel_tool × 3-5 (KPI 카드)
         ├─▶ create_chart_panel_tool × 3-5 (chart 종류별로 다양하게)
         │     └─ 각 panel: SQL 1차 검증(필터 없음) → SQL 2차 검증(날짜 필터) → $st/$ed 치환
         │     └─ (Chat 모드만) ask_user 도구로 사용자 의도 확인 가능
         └─▶ set_dashboard_layout_tool (12-col grid 배치)
   ↓
응답: 완성된 BiDashboard + panels (streaming)
```

> **중요**: `DashboardBuilderAgent`는 `dbsphere_ids: List[str]` (복수)를 받아 **여러 DbSphere를 동시에 데이터 소스로** 사용할 수 있습니다. 서로 다른 DB의 데이터를 조합한 대시보드 생성이 가능합니다.
>
> **Chat 모드와 Batch 모드의 차이**: `POST /auto-build`(batch)는 한 번에 완성, `POST /auto-build/chat`(chat)은 다중 턴 대화 + `ask_user` 도구 + 기존 대시보드 수정 지원.

## 데이터 흐름 (Panel 갱신 — Time Range 변경)

```
[User] Time Range Picker로 "최근 7일" 선택
   │
   ▼
프론트엔드: panel.sql_template의 $st=(오늘-7일), $ed=(오늘) 치환
   │
   ▼
POST /{dashboard_id}/panels/{panel_id}/execute
   │
   └─▶ DbSphere connection으로 SQL 실행 (저장된 sql 사용, NL→SQL 재호출 없음)
         │
         └─▶ 결과 → Plotly JSON 변환 → 프론트엔드 렌더링
```

**핵심 포인트**: Panel 생성 후 갱신은 **저장된 SQL template**을 그대로 재사용하므로 LLM 호출 없음 — 빠르고 예측 가능한 응답.

## 모듈 구조

```
backend/open_webui/
├── routers/bi_dashboard.py              # 19 endpoints
└── models/bi_dashboard.py               # BiDashboard, BiPanel

backend/extension_modules/dbsphere/
├── dashboard_builder_agent.py            # Auto-Build 에이전트
└── tools/dashboard_tools.py              # create_card_panel, create_chart_panel, set_layout, ask_user

src/lib/components/admin/Monitoring/BiDashboard/
├── DashboardList.svelte                  # 대시보드 목록
├── DashboardView.svelte                  # 단일 대시보드 조회/편집 (메인)
├── PanelCard.svelte                      # Card panel 렌더링
├── PanelChart.svelte                     # Chart panel 렌더링 (Plotly)
├── PanelEditor.svelte                    # Panel 생성/수정 폼
├── FilterBar.svelte                      # 전역 필터 바
├── TimeRangePicker.svelte                # 시간 범위 선택기
├── ShareDashboardModal.svelte            # 공유 링크 발급 모달
└── SharedDashboardView.svelte            # 공개 공유 뷰 (인증 없음)
```

## 다른 모듈과의 관계

| 모듈 | 관계 |
|---|---|
| `dbsphere` | **필수** — BI Dashboard의 모든 panel은 DbSphere를 데이터 소스로 사용. DBSphereAgent 재사용 |
| `dashboard_builder_agent` | Auto-Build 기능 — `extension_modules/dbsphere/` 내부에 위치 |
| `plotly_generator` | Chart 렌더링 — DBSphere의 `PlotlyChartGenerator`를 공유 |
| `search_engine` | DbSphere의 memory/schema 조회를 통해 NL→SQL 컨텍스트 확보 |
| `license` | `dbsphere` feature 의존 (간접적 게이트) |
| `monitoring` | 모니터링 탭의 서브 기능으로 배치됨 (`admin/Monitoring/` 하위) |
