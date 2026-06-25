> Last Updated: 2026-04-08

# 05. 설정 및 의존성

## 1. License Feature Gate

DBSphere는 **professional tier 이상**에서 활성화되는 license feature다.

| 설정 | 값 |
|---|---|
| **Feature key** | `dbsphere` (`FeatureModule.DBSPHERE = "dbsphere"`) |
| **Tier** | PROFESSIONAL 이상 (STANDARD에서는 차단됨) |
| **Enforcement** | `router = APIRouter(dependencies=[Depends(require_feature("dbsphere"))])` — 전체 라우터에 적용 |
| **Gating 동작** | License 없거나 `ENABLE_LICENSE_ENFORCEMENT=false` → feature 차단 시 `403 Forbidden` |

**License 관련 env/config**:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LICENSE_KEYS` | `[]` | 등록된 license key 목록 (PersistentConfig: `license.keys`) |
| `FEATURE_KEYS` | `[]` | 개별 feature key (PersistentConfig: `license.feature_keys`) |
| `ENABLE_LICENSE_ENFORCEMENT` | `true` | false면 개발 환경에서 모든 feature 허용 (운영 금지) |

자세한 내용: [`docs/engineers/license/`](../license/README.md)

---

## 2. Workspace 권한

신규 DbSphere 생성은 `workspace.databases` permission이 필요하다.

```python
# routers/dbsphere.py::create_new_dbsphere
if user.role != "admin" and not has_permission_min_level(
    user.id,
    "workspace.databases",
    "write",
    request.app.state.config.USER_PERMISSIONS,
):
    raise HTTPException(401, ERROR_MESSAGES.UNAUTHORIZED)
```

**설정 경로**: Admin Settings → Users → Default Permissions → `workspace.databases`

---

## 3. Access Control (Per-DbSphere)

각 DbSphere는 `access_control` JSON 필드로 read/write 권한을 관리한다.

```json
{
  "read": {
    "group_ids": ["analytics-team", "sales-team"],
    "user_ids": []
  },
  "write": {
    "group_ids": [],
    "user_ids": ["OWNER_USER_ID"]
  }
}
```

- `access_control = null` → public (역할 `user` 이상 모두 접근 가능)
- `access_control = {}` → private (owner만)
- `access_control = {...}` → 명시된 group/user만

**체크 지점**: `has_access(user.id, "read"/"write", dbsphere.access_control)` (`utils/access_control.py`)

---

## 4. DB 연결 파라미터 (DB Type별)

`DBConfig` (`extension_modules/dbsphere/dbsphere_state.py`)에서 지원하는 필드. DbSphere 생성 UI가 db_type에 따라 필요한 필드만 렌더링해야 한다.

| DB Type | 필수 | 선택 | 특이사항 |
|---|---|---|---|
| `postgresql` | host, port, database, username, password | schema_name | 기본 port 5432 |
| `mysql` | host, port, database, username, password | — | 기본 port 3306 |
| `mssql` | host, port, database, username, password | — | 기본 port 1433 |
| `oracle` | host, port, username, password, `service_name` | `dsn` | `service_name` 또는 `dsn` 중 하나 필수. 기본 port 1521 |
| `snowflake` | `account`, `warehouse`, username, password, database | `role`, schema_name | `host` 대신 `account.snowflakecomputing.com` 형태 |
| `databricks` | host, `http_path`, `catalog`, `access_token` | schema_name | PAT 인증. `access_token`은 암호화 저장 |
| `synapse` | host, database, username, password **또는** (`tenant_id` + `client_id` + `client_secret`) | schema_name, `use_managed_identity` | Azure AD Service Principal 또는 Managed Identity |
| `fabric` | host, database, (`tenant_id` + `client_id` + `client_secret`) | schema_name, `use_managed_identity` | Fabric SQL endpoint |
| `sqlite` | *(enum 존재하나 현재 Runner 미구현)* | | 향후 구현 예정 |

### 암호화 대상 필드

저장 시 `encrypt_value()` 처리:
- `password`
- `access_token` (Databricks)
- `client_secret` (Synapse, Fabric)

복호화 키: `WEBUI_SECRET_KEY` (env). **주의**: 이 키 변경 시 기존 DbSphere의 암호화 값 복호화 불가 → 재입력 필요.

---

## 5. 스키마 추출 설정

| 필드 | 설명 |
|---|---|
| `DbSphere.auto_extract_model` | 스키마 추출 시 사용할 LLM model ID. 없으면 DDL만 저장 (설명 생성 스킵) |
| `DbSphere.sample_row_count` | 각 테이블에서 샘플링할 row 수 (기본 5) |
| `DbSphere.last_extracted_at` | 마지막 추출 완료 시점 (epoch) |

**권장 모델**: `gpt-4o-mini` 또는 `claude-haiku` (비용 효율적). 대형 스키마(100+ tables)는 반드시 background 실행.

---

## 6. 의존 서비스

### Search Engine (Vector DB)

DBSphere 메모리는 `extension_modules/search_engine`의 `search_engine` 모듈을 통해 Vector DB에 저장된다. 운영 환경에서 다음 중 하나가 활성화되어 있어야 한다:

| Backend | Env 예시 |
|---|---|
| Azure AI Search | `SEARCH_ENGINE_TYPE=azure_search` + `SEARCH_ENGINE_AZURE_*` |
| pgvector | `SEARCH_ENGINE_TYPE=pgvector` + `SEARCH_ENGINE_PGVECTOR_*` |
| Elasticsearch | `SEARCH_ENGINE_TYPE=elasticsearch` + `SEARCH_ENGINE_ELASTICSEARCH_*` |
| Vertex AI Search | `SEARCH_ENGINE_TYPE=vertex` + `SEARCH_ENGINE_VERTEX_*` |

자세한 설정: [`docs/engineers/search_engine/`](../search_engine/README.md)

**인덱스 이름**: `dbsphere_memory` (단일 인덱스에 모든 DbSphere가 `dbsphere_id` 필터로 분리됨).

### Embedding Model

스키마 추출 및 메모리 저장 시 임베딩 생성 필요. `get_embedding_config_from_app(request.app)`에서 RAG 설정을 공유한다.

| Env | 설명 |
|---|---|
| `RAG_EMBEDDING_ENGINE` | `openai` / `ollama` / 기타 |
| `RAG_EMBEDDING_MODEL` | 모델 이름 (예: `text-embedding-3-small`) |

### LLM (SQL 생성)

에이전트가 SQL을 생성하려면 기본 LLM (Chat model)이 연결되어 있어야 한다. Agent 편집기에서 `base_model_id` 설정.

---

## 7. 개발 환경 설정 체크리스트

1. [ ] Python 3.12+, `uv sync` 완료
2. [ ] `alembic upgrade head`로 마이그레이션 적용 (`9c1d2e3f4a5b_add_dbsphere_and_glossary_tables`, `f7a8b9c0d1e2_add_dbsphere_schema_extraction_fields` 포함)
3. [ ] `WEBUI_SECRET_KEY` env 설정 (비밀번호 암호화용)
4. [ ] Search Engine 설정 (위 Backend 중 하나)
5. [ ] `RAG_EMBEDDING_ENGINE`, `RAG_EMBEDDING_MODEL` 설정
6. [ ] License: 개발 시 `ENABLE_LICENSE_ENFORCEMENT=false` 가능 (운영 금지)
7. [ ] 테스트 DB (Postgres 권장): `docker run --rm -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16`
8. [ ] Admin 계정에서 `workspace.databases` permission 확인

---

## 8. 운영 고려사항

- **비밀번호 로테이션**: `WEBUI_SECRET_KEY` 교체 전 모든 DbSphere의 연결 정보를 백업하고, 교체 후 재입력해야 한다. 자동 마이그레이션 없음.
- **대형 스키마**: 100+ tables는 background 추출 필수. 타임아웃은 `max(600s, tables_total * 120s)` = 테이블당 2분 예상.
- **동시 작업**: `update_extraction_job_atomic()`이 `with_for_update()` row-lock을 사용하므로 동일 DbSphere에 대한 동시 추출 요청은 안전하게 직렬화됨.
- **메모리 크기**: 단일 `dbsphere_memory` 인덱스에 모든 DbSphere가 공존 → 수천 개 DbSphere 시 인덱스 크기 모니터링 필요. `entity_type` + `dbsphere_id` 복합 필터 성능 확인.
- **License 회수 시**: 기존 DbSphere 데이터는 DB에 유지되나 라우터가 차단됨 → 다시 license 등록하면 즉시 복원.
