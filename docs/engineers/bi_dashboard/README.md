> Last Updated: 2026-04-08

# BI Dashboard (비즈니스 인텔리전스 대시보드)

관리자 모니터링 대시보드. **DbSphere에 등록된 DB를 데이터 소스**로 사용하고, **DBSphereAgent로 NL→SQL**을 생성한 후 **Plotly로 시각화**한다. 수동으로 panel을 추가하거나, LLM 기반 Dashboard Builder Agent로 자동 생성할 수 있으며, **share link**를 통해 외부에도 공개 가능하다.

## 문서 목록

| # | 파일 | 내용 |
|---|---|---|
| 1 | [개요](./01_overview.md) | 기능 목적, 핵심 개념, 데이터 흐름 |
| 2 | [아키텍처](./02_architecture.md) | DB 모델 (`bi_dashboard`, `bi_panel`), Auto-Build 에이전트, SQL 생성·검증 흐름, 트러블슈팅 |
| 3 | [API](./03_api.md) | 19개 REST 엔드포인트 |
| 4 | [프론트엔드](./04_frontend.md) | 9개 Svelte 컴포넌트, Plotly 렌더링, Time Range picker |

## 퀵 스타트

1. **DbSphere 생성**: 데이터 소스가 될 DB 등록 (`workspace/database`)
2. **Monitoring → Dashboards** 탭 진입
3. **새 대시보드 생성** 또는 **Auto-Build** (자연어 프롬프트 입력)
4. Panel 추가:
   - Card panel (단일 KPI)
   - Chart panel (bar, line, pie, scatter, area, table, histogram, heatmap, grouped_bar)
5. **Share link 발급** → 외부 공개 URL 생성 (read-only)

## 주요 기능

| 기능 | 설명 |
|---|---|
| **NL→SQL** | Panel 생성 시 자연어 설명 → DBSphereAgent가 SQL 생성 + 검증 |
| **Auto-Build** | 스키마 분석 후 3-5개 card + 3-5개 chart panel 자동 생성 (Dashboard Builder Agent) |
| **Time Range Filter** | 전역 1d/7d/30d/custom 필터 — 모든 panel의 `sql_template` `$st`/`$ed`에 주입 |
| **Diverse Chart Types** | bar/line/pie/area/table/histogram/heatmap/grouped_bar 자동 선택 |
| **Share Link** | `share_id`로 public URL 생성, read-only 접근 |
| **HTML Export** | 대시보드를 단독 HTML 파일로 export (offline 공유) |
| **Access Control** | Dashboard별 read/write 권한 (group, user, org_unit) |

## 관련 코드

- **Backend**:
  - Router: `backend/open_webui/routers/bi_dashboard.py` (19 endpoints)
  - Model: `backend/open_webui/models/bi_dashboard.py` (`BiDashboard`, `BiPanel`)
  - Auto-Build agent: `backend/extension_modules/dbsphere/dashboard_builder_agent.py`
  - Auxiliary tools: `backend/extension_modules/dbsphere/tools/dashboard_tools.py` (card_panel, chart_panel, set_layout 등)
- **Frontend**:
  - Components: `src/lib/components/admin/Monitoring/BiDashboard/` (9 files)
  - Parent integration: `src/lib/components/admin/Monitoring/` (Monitoring 탭 안에 Dashboards 서브탭)
- **Auth**:
  - `get_admin_monitoring_read_access` / `get_admin_monitoring_write_access`
  - Shared views는 인증 없이 `share_id`만으로 접근 가능

## 관련 문서

- [DBsphere](../dbsphere/README.md) — 데이터 소스 역할. `dashboard_builder_agent.py`가 DBSphere 인프라를 공유
- [Monitoring](../monitoring/README.md) — 상위 모니터링 모듈. BI Dashboard는 Monitoring 탭의 서브 기능
- [License](../license/README.md) — License 게이팅 (아래 "License" 섹션 참조)

## License 게이팅

BI Dashboard는 **`require_feature()` 데코레이터를 직접 사용하지 않는다** (2026-04-08 기준). 라우터 자체는 admin monitoring auth만 검사하지만, **Panel 생성 시점**에 사용하는 DbSphere가 `require_feature("dbsphere")` 게이트를 통과해야 하므로 사실상 `dbsphere` feature에 의존한다. 향후 별도 `bi_dashboard` feature key로 분리할 가능성 있음.

## 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-04-08 | 문서 신규 작성 (`docs/eng-docs-refresh` 브랜치). 9 컴포넌트, 19 endpoints 기준 |
