> Last Updated: 2026-04-08

# 04. BI Dashboard 프론트엔드

## 1. 컴포넌트 구조

```
src/lib/components/admin/Monitoring/BiDashboard/
├── DashboardList.svelte         # 200 lines — 대시보드 목록 페이지
├── DashboardView.svelte         # 780 lines — 단일 대시보드 (메인 뷰/편집)
├── FilterBar.svelte             # 145 lines — 전역 필터 바
├── PanelCard.svelte             # 360 lines — Card panel 렌더링
├── PanelChart.svelte            # 322 lines — Chart panel (Plotly 렌더링)
├── PanelEditor.svelte           # 534 lines — Panel 생성/수정 모달/폼
├── ShareDashboardModal.svelte   # 162 lines — 공유 링크 발급 모달
├── SharedDashboardView.svelte   # 115 lines — 공개 공유 뷰 (인증 없음)
└── TimeRangePicker.svelte       # 201 lines — 시간 범위 선택기 (1d/7d/30d/custom)
```

**총 9 컴포넌트, ~2819 lines**.

## 2. 컴포넌트별 상세

### `DashboardList.svelte` (200 lines)

대시보드 목록을 카드 그리드로 표시. 새 대시보드 생성 버튼, 검색, 필터 포함.

- **API**: `getBiDashboards(token)` → `list[BiDashboardModel]`
- **Events**: `on:select={dashboardId}` → `DashboardView`로 이동
- **신규 생성**: `+ New Dashboard` 클릭 → 모달 or Auto-Build chat 시작

### `DashboardView.svelte` (780 lines, 가장 큰 컴포넌트)

단일 대시보드의 메인 뷰 + 편집기. 상단에 제목/설명/time range picker/share 버튼, 본문에 grid layout의 panel들, 하단에 `+ Add Panel` 버튼.

**주요 상태**:
| State | 설명 |
|---|---|
| `dashboard` | `BiDashboardModel` |
| `panels` | `BiPanelModel[]` (dashboard.id로 조회) |
| `layout` | `[{i, x, y, w, h}]` — grid 배치 |
| `timeRange` | `"1d" \| "7d" \| "30d" \| {from, to}` |
| `filters` | `DashboardFilter[]` — 전역 필터 값 |
| `editMode` | `boolean` — 편집 모드 토글 |
| `selectedPanel` | 편집 중인 panel |

**주요 동작**:
- **Time range 변경** → 모든 panel 동시 `executePanel(panel_id, timeRange)` 호출 → chart 갱신
- **Panel 드래그**: 편집 모드에서 grid 드래그 앤 드롭 (`layout` 업데이트 후 save)
- **Panel 추가**: `PanelEditor` 모달 오픈 → save 후 `DashboardView`에 추가
- **Share**: `ShareDashboardModal` 오픈

### `PanelCard.svelte` (360 lines)

Card panel (단일 KPI). 숫자 + 라벨 + 아이콘 + 색상.

- **Props**: `panel: BiPanelModel`, `timeRange: string`, `loading: boolean`
- **렌더링**: `panel.data.value_column`으로 결과의 첫 번째 row에서 값 추출
- **포맷**: `panel.data.format` (`number`, `currency`, `percent`, `compact`)
- **색상**: `panel.data.color` (예: `#3B82F6` blue, `#10B981` green)

### `PanelChart.svelte` (322 lines)

Chart panel. Plotly.js 기반 렌더링.

- **Props**: `panel: BiPanelModel`, `timeRange: string`
- **의존**: `plotly.js-dist`
- **동작**:
  ```svelte
  <script>
    import Plotly from 'plotly.js-dist';
    $: if (chartData && chartDiv) {
      Plotly.newPlot(chartDiv, chartData.data, chartData.layout, {
        responsive: true,
        displayModeBar: false
      });
    }
  </script>
  ```
- **지원 chart_type**: `bar`, `line`, `pie`, `scatter`, `area`, `table`, `histogram`, `heatmap`, `grouped_bar`
- **Data flow**: `executePanel()` API → 결과 → chart_type별 Plotly spec 생성 → 렌더

### `PanelEditor.svelte` (534 lines)

Panel 생성 및 수정 폼. 모달 형태.

**탭 구조**:
1. **Basic**: name, description, panel type (card/chart)
2. **Data Source**: `dbsphere_id` 선택 (Selector from `getDbSphereList()`)
3. **SQL**:
   - **NL mode**: 자연어 prompt → `POST /generate-sql` → 생성된 SQL 표시 + 편집 가능
   - **SQL mode**: 직접 SQL 작성 (고급 사용자)
4. **Visualization**: chart_type + x/y column 선택 (SQL 실행 결과의 컬럼 목록에서)
5. **Format**: card format / color / icon (card type만)
6. **Preview**: 현재 설정으로 실시간 미리보기 (`POST /execute-sql`)

**SQL template 변환**:
사용자가 SQL에 날짜 조건을 포함하면, save 시 `PanelEditor`가 자동으로 날짜 값을 `$st`/`$ed`로 치환하여 `sql_template`을 생성한다.

### `FilterBar.svelte` (145 lines)

전역 필터 바. `DashboardFilter[]`를 렌더링하고 사용자 입력을 받아 `DashboardView`에 전달.

- **필터 타입**: `text`, `select`, `date_range`
- **Events**: `on:change={filters}` → `DashboardView.filters` 업데이트 → 모든 panel 재실행

### `TimeRangePicker.svelte` (201 lines)

시간 범위 선택기.

- **Preset**: `1d`, `7d`, `30d`
- **Custom**: date range picker (from/to)
- **Events**: `on:change={timeRange}`
- **변환**: preset은 서버에서 `$st = now - 7d`, `$ed = now` 등으로 계산

### `ShareDashboardModal.svelte` (162 lines)

공유 링크 발급/관리 모달.

- **Generate**: `POST /{id}/share` → `share_id` 받음 → URL 표시 + 복사 버튼
- **Revoke**: `DELETE /{id}/share` → share_id 제거 (기존 URL 무효화)
- **Export HTML**: `POST /{id}/export-html` → HTML 파일 다운로드

### `SharedDashboardView.svelte` (115 lines)

공개 공유 URL (`/shared/{share_id}`)에서 렌더링되는 read-only 뷰. 인증 없이 접근 가능.

- **라우트**: `src/routes/shared/[share_id]/+page.svelte`
- **API**: `GET /shared/{share_id}` → dashboard + panels + last_result
- **Time Range 변경**: `POST /shared/{share_id}/execute-sql` 호출 (저장된 sql_template 재실행)
- **편집 불가**: 모든 write 버튼 숨김

## 3. API 클라이언트

**파일**: `src/lib/apis/bi-dashboard/index.ts` (또는 `src/lib/apis/monitoring/bi-dashboard/`)

| 함수 | 엔드포인트 |
|---|---|
| `getBiDashboards(token)` | `GET /` |
| `getAccessibleDashboards(token)` | `GET /accessible` |
| `createBiDashboard(token, form)` | `POST /create` |
| `getBiDashboardById(token, id)` | `GET /{id}` |
| `updateBiDashboardById(token, id, form)` | `POST /{id}/update` |
| `deleteBiDashboardById(token, id)` | `DELETE /{id}/delete` |
| `autoBuildDashboard(token, form)` | `POST /auto-build` |
| `autoBuildDashboardChat(token, form)` | `POST /auto-build/chat` (streaming) |
| `createBiPanel(token, dashboardId, form)` | `POST /{id}/panels/create` |
| `updateBiPanel(token, dashboardId, panelId, form)` | `POST /{id}/panels/{pid}/update` |
| `deleteBiPanel(token, dashboardId, panelId)` | `DELETE /{id}/panels/{pid}/delete` |
| `executePanel(token, dashboardId, panelId, timeRange)` | `POST /{id}/panels/{pid}/execute` |
| `generateSql(token, form)` | `POST /generate-sql` |
| `executeSql(token, form)` | `POST /execute-sql` |
| `shareDashboard(token, id)` | `POST /{id}/share` |
| `unshareDashboard(token, id)` | `DELETE /{id}/share` |
| `getSharedDashboard(shareId)` | `GET /shared/{share_id}` (인증 없음) |
| `executeSharedSql(shareId, form)` | `POST /shared/{share_id}/execute-sql` (인증 없음) |
| `exportDashboardHtml(token, id)` | `POST /{id}/export-html` |

## 4. 통합 지점

### Monitoring 탭 서브탭

`src/lib/components/admin/Monitoring.svelte`의 탭 구성에 `Dashboards` 서브탭으로 추가됨. 탭 선택 시 `DashboardList.svelte` 렌더링.

### 라우트

- `/admin/monitoring` → Monitoring 메인 (탭 스위칭)
- `/admin/monitoring/dashboard/{id}` → 단일 대시보드 편집
- `/shared/{share_id}` → 공유 뷰 (별도 layout, admin 권한 불필요)

## 5. i18n 키 (주요)

| 키 | 설명 |
|---|---|
| `Dashboards` | 탭/섹션 제목 |
| `Create Dashboard` | 생성 버튼 |
| `Auto-Build Dashboard` | 자동 빌드 버튼 |
| `Add Panel` | panel 추가 |
| `Share` / `Unshare` / `Copy Link` | 공유 관련 |
| `Export HTML` | HTML 내보내기 |
| `Time Range` / `Last 1 day` / `Last 7 days` / `Last 30 days` / `Custom` | 시간 범위 |
| `Edit` / `View` mode | 편집/조회 토글 |

## 6. 확장 시 주의사항

- **새 chart_type 추가**: `PanelChart.svelte`에 렌더링 분기 추가 → `dashboard_builder_agent.py`의 system prompt에 chart_type 추가 → `PanelEditor.svelte`의 chart_type selector에 옵션 추가
- **새 filter type 추가**: `FilterBar.svelte`에 입력 UI 추가 → `DashboardFilter` type에 추가 → `executePanel` API에 필터 파라미터 전달 규약 정의
- **Plotly 버전 업데이트 시**: `PanelChart.svelte`의 `Plotly.newPlot` 호출부 확인, responsive 옵션 변경 가능성
- **공유 뷰 보안**: `SharedDashboardView.svelte`에서 절대 사용자 입력 SQL을 실행하지 않도록 주의. 모든 실행은 저장된 `sql_template`의 `$st`/`$ed` 치환만 허용
