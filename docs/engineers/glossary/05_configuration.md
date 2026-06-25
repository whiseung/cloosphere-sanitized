> Last Updated: 2026-04-08

# 05. Glossary 설정 및 의존성

## 1. License Feature Gate

| 설정 | 값 |
|---|---|
| **Feature key** | `glossary` (`FeatureModule.GLOSSARY`) |
| **Tier** | **STANDARD** 이상 |
| **Enforcement** | `router = APIRouter(dependencies=[Depends(require_feature("glossary"))])` — 전체 라우터 |

자세한 license 시스템: [`docs/engineers/license/`](../license/README.md)

## 2. 워크스페이스 권한

Glossary 신규 생성은 `workspace.glossary` permission이 필요하다.

```python
# routers/glossary.py::create_new_glossary
if user.role != "admin" and not has_permission_min_level(
    user.id, "workspace.glossary", "write", request.app.state.config.USER_PERMISSIONS
):
    raise HTTPException(401, ERROR_MESSAGES.UNAUTHORIZED)
```

**설정 경로**: Admin Settings → Users → Default Permissions → `workspace.glossary`

## 3. Per-Glossary Access Control

`access_control` JSON 필드로 read/write 권한을 관리.

```json
{
  "read": {
    "group_ids": ["engineering"],
    "user_ids": [],
    "org_unit_ids": ["r-and-d"]
  },
  "write": {
    "group_ids": [],
    "user_ids": ["OWNER_ID"],
    "org_unit_ids": []
  }
}
```

- `None` → public
- `{}` → owner only
- 위 예시 → engineering 그룹 또는 R&D 조직 단위는 읽기, owner만 쓰기

## 4. 검색 엔진 의존성

Glossary는 `extension_modules/search_engine` 모듈을 통해 벡터 DB에 색인한다. 검색 엔진이 설정되지 않아도 Glossary CRUD는 정상 동작하지만, **LLM 주입 기능은 비활성화**된다 (에이전트가 용어를 참조할 수 없음).

### 필수 환경 변수

| 변수 | 설명 | 예시 |
|---|---|---|
| `SEARCH_ENGINE_TYPE` | 검색 엔진 타입 | `azure_search`, `pgvector`, `elasticsearch`, `vertex_search` |
| Backend별 설정 | 엔진별로 다름 | 아래 표 참조 |

### Backend별 추가 환경 변수

| Backend | 환경 변수 |
|---|---|
| `azure_search` | `SEARCH_ENGINE_AZURE_ENDPOINT`, `SEARCH_ENGINE_AZURE_API_KEY`, `SEARCH_ENGINE_AZURE_INDEX_NAME` |
| `pgvector` | `SEARCH_ENGINE_PGVECTOR_HOST`, `_PORT`, `_DATABASE`, `_USER`, `_PASSWORD` |
| `elasticsearch` | `SEARCH_ENGINE_ELASTICSEARCH_URL`, `_USERNAME`, `_PASSWORD`, `_INDEX_NAME`, `_VERIFY_CERTS` |
| `vertex_search` | `SEARCH_ENGINE_VERTEX_PROJECT_ID`, `_LOCATION`, `_SEARCH_ENGINE_ID` |

자세한 설정: [`docs/engineers/search_engine/`](../search_engine/README.md)

### 인덱스 스키마 (`create_glossary_config`)

```python
# extension_modules/search_engine/schemas.py::create_glossary_config()
IndexConfig(
    index_name=index_name,    # 기본: glossary의 경우 glossary별 별도 인덱스 또는 단일 인덱스 + glossary_id 필터
    columns=[
        ColumnDefinition(name="term", data_type="text", searchable=True),
        ColumnDefinition(name="description", data_type="text", searchable=True),
        ColumnDefinition(name="synonyms", data_type="text", searchable=True),
        ColumnDefinition(name="example", data_type="text", searchable=True),
        ColumnDefinition(name="category", data_type="text", filterable=True),
        ColumnDefinition(name="glossary_id", data_type="text", filterable=True),
        ColumnDefinition(name="vector", data_type="vector", vector_dimensions=<embedding model dim>),
    ],
)
```

## 5. 임베딩 모델 의존성

검색을 위해 임베딩 생성이 필요하다. RAG 설정과 공유:

| 변수 | 설명 | 예시 |
|---|---|---|
| `RAG_EMBEDDING_ENGINE` | 임베딩 엔진 | `openai`, `ollama`, `azure_openai` |
| `RAG_EMBEDDING_MODEL` | 모델 이름 | `text-embedding-3-small`, `all-MiniLM-L6-v2` |
| `RAG_OPENAI_API_KEY` | OpenAI API key (engine=openai 시) | |
| `RAG_OPENAI_API_BASE_URL` | OpenAI endpoint | |

임베딩 차원은 모델에 따라 달라지므로, 모델 변경 시 기존 인덱스를 drop하고 재색인해야 한다 (`POST /{id}/sync`).

## 6. Agent 연동 설정

Agent가 Glossary를 사용하려면 `meta.glossary_ids` 배열에 Glossary ID를 등록해야 한다.

```json
// Agent model.meta
{
  "glossary_ids": ["glossary-uuid-1", "glossary-uuid-2"],
  ...
}
```

런타임에서 unified_agent는 이 배열을 읽고 `GlossarySearchTool`을 구성한다. Agent는 ReAct 루프 중 `glossary_search(query)` 도구를 호출하여 관련 용어를 찾는다.

## 7. 캐싱 (Memory 모듈 연동)

`backend/extension_modules/agent/memory_extractor.py`에서 **60초 in-memory 캐시**로 Glossary terms를 로드한다. 목적: entity extraction 시 이미 Glossary에 등록된 term은 entity로 추출하지 않기 위함.

- **Cache key**: user_id (또는 전역)
- **TTL**: 60초
- **Max terms**: 50개 (성능 고려)
- **Fallback**: Glossary API 실패 시 cache miss로 취급 — entity extraction 정상 진행 (중복 필터 일시 비활성)

## 8. 개발 환경 체크리스트

1. [ ] Python 3.12+, `uv sync`
2. [ ] `alembic upgrade head` (`9c1d2e3f4a5b_add_dbsphere_and_glossary_tables` 포함)
3. [ ] `RAG_EMBEDDING_ENGINE`, `RAG_EMBEDDING_MODEL` 설정
4. [ ] Search Engine 설정 (위 Backend 중 하나)
5. [ ] License: 개발 시 `ENABLE_LICENSE_ENFORCEMENT=false` 가능
6. [ ] Admin 계정에서 `workspace.glossary` permission 확인
7. [ ] 첫 Glossary 생성 → `POST /{id}/sync`로 검색 엔진 인덱스 생성 확인

## 9. 운영 고려사항

- **임베딩 모델 변경**: 모든 기존 인덱스 재생성 필요. 각 Glossary에 대해 `POST /{id}/sync` 수행
- **대량 import**: 수백~수천 개 entries를 한 번에 import 시 검색 엔진 upsert rate limit 주의 (Azure Search는 기본 1000 req/s). Background task에서 처리되므로 클라이언트는 즉시 응답 받음
- **인덱스 비용**: Azure Search 벡터 인덱스는 row당 비용 발생. 대형 Glossary (수만 entries) 운영 시 인덱스 크기 모니터링
- **Agent에 연결된 Glossary 삭제**: `linked-agents` 확인 후 삭제. 삭제된 Glossary ID가 Agent의 `meta.glossary_ids`에 남아있으면 조용히 무시됨 (에러 없음)
- **검색 엔진 장애 시 graceful degradation**: Glossary CRUD는 계속 동작, LLM 주입만 실패. Agent는 용어를 참조하지 못해도 일반 응답 생성 가능
