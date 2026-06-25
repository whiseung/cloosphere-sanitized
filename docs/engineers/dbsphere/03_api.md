> Last Updated: 2026-04-08

# 03. DBSphere REST API

전체 22개 엔드포인트. 라우터 전체는 `require_feature("dbsphere")` license gate 적용. 모든 엔드포인트는 `Depends(get_verified_user)` 의존성 주입 필수. 권한 체크는 `access_control` 필드를 기반으로 `has_access(user.id, "read"/"write", ...)` 적용.

**Base path**: `/api/v1/dbsphere`
**Router 파일**: `backend/open_webui/routers/dbsphere.py`

## 1. CRUD

| Method | Path | 설명 | Permission |
|---|---|---|---|
| GET | `/` | 사용자가 읽기 가능한 DbSphere 목록 | `read` 또는 owner/admin |
| GET | `/list` | 사용자가 편집 가능한 DbSphere 목록 (에이전트 편집기에서 사용) | `write` 또는 owner/admin |
| POST | `/create` | 신규 DbSphere 생성 | `workspace.databases` (write level) 또는 admin |
| GET | `/{id}` | 단일 DbSphere 조회 (password는 마스킹) | `read` 또는 owner/admin |
| POST | `/{id}/update` | 업데이트 (마스킹된 password는 기존 암호화 값 유지) | `write` 또는 owner/admin |
| DELETE | `/{id}/delete` | 삭제 | `write` 또는 owner/admin |
| GET | `/{id}/linked-agents` | 이 DbSphere를 사용 중인 Agent(Model) 목록 | `verified_user` |

### `POST /create` — Request body

```python
class DbSphereForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None        # connection 정보 포함
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    auto_extract_model: Optional[str] = None
    sample_row_count: Optional[int] = 5
```

**Request 예시**:
```bash
curl -X POST http://localhost:8080/api/v1/dbsphere/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sales DB",
    "description": "영업 데이터 PostgreSQL",
    "data": {
      "connection": {
        "db_type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "database": "sales",
        "username": "analyst",
        "password": "PLAIN_PASSWORD",
        "schema_name": "public"
      }
    },
    "access_control": {
      "read": {"group_ids": ["analytics-team"], "user_ids": []},
      "write": {"group_ids": [], "user_ids": ["OWNER_USER_ID"]}
    },
    "auto_extract_model": "gpt-4o-mini",
    "sample_row_count": 5
  }'
```

## 2. Connection Test

| Method | Path | 설명 |
|---|---|---|
| POST | `/test-connection` | 저장 전 연결 테스트 (DbSphere 생성 전 UI에서 사용) |
| POST | `/{id}/test-connection` | 기존 DbSphere 연결 테스트 (마스킹된 password는 서버가 복원) |
| POST | `/tables` | 연결 정보로 테이블/뷰 목록 조회 (스키마 선택 UI에서 사용) |

### `ConnectionTestForm`

```python
class ConnectionTestForm(BaseModel):
    db_type: str             # postgresql, mysql, mssql, oracle, snowflake, databricks, synapse, fabric
    host: str
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    schema_name: Optional[str] = None
    # Snowflake
    warehouse: Optional[str] = None
    account: Optional[str] = None
    role: Optional[str] = None
    # Databricks
    http_path: Optional[str] = None
    catalog: Optional[str] = None
    access_token: Optional[str] = None
    # Azure AD (Synapse, Fabric)
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    # For resolving masked credentials
    dbsphere_id: Optional[str] = None
```

### `ConnectionTestResponse`

```python
class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None
```

## 3. Schema Extraction

| Method | Path | 설명 |
|---|---|---|
| POST | `/{id}/extract-schema` | 스키마 추출 시작 (기본 background=True) |
| GET | `/{id}/extraction-status` | 추출 job 상태 폴링 |
| GET | `/{id}/extracted-tables` | 추출된 테이블 목록 조회 |
| DELETE | `/{id}/extracted-tables` | 추출된 테이블 전체 삭제 (메모리 초기화) |
| DELETE | `/{id}/extracted-tables/{table_name}` | 특정 테이블의 memory 삭제 (DDL + 관련 샘플 Q&A) |

### `ExtractSchemaForm`

```python
class ExtractSchemaForm(BaseModel):
    model_id: Optional[str] = None    # 없으면 LLM 설명 생성 없이 DDL만 저장
    sample_row_count: int = 5
    table_names: Optional[list[str]] = None  # None이면 전체
    generate_sample_qa: bool = True
    clear_existing: bool = True
    background: bool = True            # False면 동기 실행 (소규모 스키마만 권장)
    force: bool = False                # 기존 running job 강제 리셋
```

### `ExtractionJobStatus`

```python
class ExtractionJobStatus(BaseModel):
    status: str              # "pending" | "running" | "completed" | "failed"
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    current_table: Optional[str] = None
    tables_total: Optional[int] = None
    tables_processed: Optional[int] = None
    error: Optional[str] = None
```

### Stale Job Detection

`POST /{id}/extract-schema`가 기존 `running` job을 감지하면:
- `force=True` → 기존 job을 `failed`로 atomic update 후 새 job 시작
- `force=False` + 경과 시간이 `max(600s, tables_total * 120s)` 초과 → stale로 간주하고 자동 리셋
- 그 외 → `400 Bad Request` (이미 실행 중)

## 4. Memory CRUD

메모리는 `SearchEngineDbSphereMemory`가 관리하며, `entity_type`으로 구분된 4종의 데이터를 저장한다.

| Method | Path | 설명 |
|---|---|---|
| GET | `/{id}/memories` | 메모리 목록 조회 (필터: entity_type, table_name, pagination) |
| GET | `/{id}/memories/stats` | 메모리 통계 (entity_type별 count) |
| GET | `/{id}/memories/{memory_id}` | 단일 메모리 상세 |
| POST | `/{id}/memories/create` | 메모리 신규 생성 (관리자가 `documentation`, `sql_example` 추가) |
| POST | `/{id}/memories/{memory_id}/update` | 메모리 수정 |
| DELETE | `/{id}/memories/{memory_id}` | 메모리 삭제 |
| POST | `/{id}/memories/summary/update` | 스키마 요약 재생성 (`dbsphere.data["schema_summary"]`) |

### Memory filter (쿼리 파라미터)

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `entity_type` | str? | `sql_memory` / `ddl_schema` / `documentation` / `sql_example` 중 하나 |
| `table_name` | str? | 특정 테이블의 메모리만 (DDL + 관련 샘플 Q&A) |
| `query` | str? | 텍스트 검색 (vector search 또는 키워드) |
| `limit` | int | 기본 50 |
| `offset` | int | 기본 0 |

### `MemoryItem` 응답 스키마 (개요)

```python
class MemoryItem(BaseModel):
    id: str
    dbsphere_id: str
    entity_type: str            # sql_memory | ddl_schema | documentation | sql_example
    content: str                # 본문 (Q&A, DDL, 문서, 예제)
    metadata: Optional[dict]    # table_name, columns, score 등
    created_at: int
    updated_at: int
```

## 5. 공통 에러 응답

| Status | 상황 |
|---|---|
| `400` | `NAME_TAKEN`, `NOT_FOUND`, `ACCESS_PROHIBITED`, `Failed to create/update database`, `Unsupported database type`, 스키마 추출 이미 실행 중 |
| `401` | `UNAUTHORIZED` (권한 부족) |
| `403` | License feature gate 차단 (`require_feature("dbsphere")`) |
| `404` | DbSphere 또는 memory item 없음 |
| `500` | DB 연결 실패, SQL 실행 오류, LLM 호출 실패 |

## 6. 암호화/마스킹 규칙

- **저장 시**: `data.connection.password`, `access_token`, `client_secret` 모두 `encrypt_connection_password()`에서 `encrypt_value()` 처리
- **응답 시**: `mask_connection_data()`에서 민감 필드를 `••••••••` 형태로 마스킹
- **업데이트 시**: 클라이언트가 마스킹된 값(`••••••••`)을 그대로 전송하면 서버는 기존 암호화 값을 유지 (`resolve_connection_password()`)
- **`test-connection` 재사용**: `dbsphere_id`를 함께 전송하면 서버가 저장된 암호화 값을 복호화하여 테스트
