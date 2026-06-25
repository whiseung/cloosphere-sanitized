> Last Updated: 2026-04-08

# 03. BI Dashboard REST API

**Base path**: `/api/v1/bi-dashboard`
**Router**: `backend/open_webui/routers/bi_dashboard.py` (19 endpoints)
**Auth**:
- 일반: `get_admin_monitoring_read_access` / `get_admin_monitoring_write_access`
- Shared: `get_verified_user` (발급 후 공유 조회는 인증 없음, 아래 참조)

## 엔드포인트 목록 (19개)

### CRUD

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | admin monitoring (read) | 사용자가 접근 가능한 전체 대시보드 |
| GET | `/accessible` | verified user | 본인이 접근 가능한 대시보드만 (일반 사용자용) |
| POST | `/create` | admin monitoring (write) | 대시보드 생성 |
| GET | `/{dashboard_id}` | 권한 기반 | 대시보드 상세 + 모든 panel |
| POST | `/{dashboard_id}/update` | 권한 기반 (write) | 대시보드 메타 업데이트 (name, description, layout, filters) |
| DELETE | `/{dashboard_id}/delete` | 권한 기반 (write) | 대시보드 + 모든 panel 삭제 |

### Auto-Build

| Method | Path | Description |
|---|---|---|
| POST | `/auto-build` | 배치 자동 생성 (비대화형, 한 번에 완성) |
| POST | `/auto-build/chat` | 대화형 자동 생성 (streaming, 사용자가 선택지 제공 가능) |

**Request body (`AutoBuildForm`)** — 실제 코드 기준:
```python
class AutoBuildForm(BaseModel):
    name: str                              # 생성할 대시보드 이름
    dbsphere_ids: list[str]                # ★ 복수! 여러 DbSphere를 데이터 소스로 사용 가능
    model_id: str                          # 사용할 LLM 모델
    prompt: Optional[str] = None           # 자연어 목적/지시 (예: "매출 분석용 대시보드")
```

> **중요**: `dbsphere_ids`는 **리스트**입니다. 단일 DbSphere만 쓰더라도 `["uuid"]` 형태로 전달해야 하며, 2개 이상의 DbSphere를 지정하면 `DashboardBuilderAgent`가 여러 DB에서 데이터를 조합한 대시보드를 생성합니다.

### Panel CRUD (dashboard 하위)

| Method | Path | Description |
|---|---|---|
| POST | `/{dashboard_id}/panels/create` | 새 panel 추가 (NL→SQL 검증 포함) |
| POST | `/{dashboard_id}/panels/{panel_id}/update` | panel 수정 |
| DELETE | `/{dashboard_id}/panels/{panel_id}/delete` | panel 삭제 |
| POST | `/{dashboard_id}/panels/{panel_id}/execute` | panel SQL 실행 (time range filter 적용) |

### SQL 도구 (Panel 생성 전용 내부 호출용이지만 API로도 노출)

| Method | Path | Description |
|---|---|---|
| POST | `/generate-sql` | 자연어 → SQL 변환 (DBSphereAgent) |
| POST | `/execute-sql` | SQL 직접 실행 (검증 또는 ad-hoc 쿼리) |

**Request body (`GenerateSqlForm`)** — 실제 코드 기준:
```python
class GenerateSqlForm(BaseModel):
    dbsphere_id: str                       # 단일 DbSphere (generate-sql은 개별 panel용이므로 단수)
    nl_query: str                          # 자연어 쿼리
    model_id: str                          # LLM 모델
    filters: Optional[list[dict]] = None   # 추가 필터
```

**Request body (`ExecuteSqlForm`)**:
```python
class ExecuteSqlForm(BaseModel):
    dbsphere_id: str
    sql: str                               # 실제 실행할 SQL
    sql_template: Optional[str] = None     # $st/$ed placeholder 포함 SQL (재사용용)
    from_value: Optional[str] = None       # 시작일 (YYYY-MM-DD)
    to_value: Optional[str] = None         # 종료일 (YYYY-MM-DD)
    filters: Optional[list[dict]] = None
```

### Share

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/{dashboard_id}/share` | 권한 기반 (write) | `share_id` 발급 또는 재발급 |
| DELETE | `/{dashboard_id}/share` | 권한 기반 (write) | `share_id` revoke |
| GET | `/shared/{share_id}` | **인증 없음** | 공유 뷰 조회 (read-only) |
| POST | `/shared/{share_id}/execute-sql` | **인증 없음** | 공유 뷰에서 time range 변경 후 재실행 |

### Export

| Method | Path | Description |
|---|---|---|
| POST | `/{dashboard_id}/export-html` | 대시보드를 독립 HTML 파일로 export |

## Request/Response 스키마

### `BiDashboardForm`

```python
class BiDashboardForm(BaseModel):
    name: str
    description: Optional[str] = None
    data: Optional[dict] = None        # {layout, filters, time_range, meta}
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
```

### `BiPanelForm`

```python
class BiPanelForm(BaseModel):
    name: str
    description: Optional[str] = None
    dbsphere_id: str
    data: dict                          # {type, sql, sql_template, chart_type, x, y, ...}
    meta: Optional[dict] = None
```

### `DashboardFilter`

```python
class DashboardFilter(BaseModel):
    label: str
    type: str = "text"                  # "date_range" | "select" | "text"
    field: str                          # DB 컬럼명
    value: Optional[str] = None
    from_value: Optional[str] = None    # date_range용
    to_value: Optional[str] = None
```

## 에러 케이스

| Status | 상황 |
|---|---|
| 400 | 잘못된 입력 (필수 필드 누락, SQL 검증 실패, share_id 존재하지 않음) |
| 401 | `UNAUTHORIZED`, `ACCESS_PROHIBITED` |
| 404 | Dashboard/Panel/DbSphere not found |
| 403 | DbSphere license feature 비활성 (간접 게이트) |
| 500 | DB 연결 실패, LLM 호출 실패, SQL 실행 오류 |

## 주의사항

- **Panel 생성은 반드시 `dbsphere_id` 필수** — 해당 DbSphere는 `require_feature("dbsphere")` 게이트를 통과해야 함
- **Share link 접근 보안**: 공유 뷰에서 임의 SQL 실행 불가. 저장된 `sql_template`의 `$st`/`$ed` 치환만 허용
- **Time range 파라미터**: `1d` / `7d` / `30d` / `{custom: from,to}` — 프론트엔드에서 placeholder 치환 후 `execute-sql` 호출
