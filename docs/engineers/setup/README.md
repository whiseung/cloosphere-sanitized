> Last Updated: 2026-04-08

# Cloosphere 셋업 가이드

개발 환경 및 배포 환경의 셋업 방법. 로컬 개발, Azure 배포, 그리고 Open WebUI 기반 데이터/설정 저장 흐름을 다룹니다.

## 문서 목록

| # | 파일 | 내용 | 상태 |
|---|---|---|---|
| 1 | [로컬 셋업](./01_local_setup.md) | 로컬 개발 환경 (Python 3.12+, Node 22, PostgreSQL), 환경 변수, VS Code 디버깅 | ⚠️ 일부 최신화 필요 |
| 2 | [Azure 셋업](./02_azure_setup.md) | Azure 배포 가이드 (App Service, PostgreSQL Flexible Server, App Gateway 등) | 🔴 **작성 중 — 내용 없음** |
| 3 | [Open WebUI 데이터/설정 저장 흐름](./03_openwebui_data_and_config_save_flow.md) | `PersistentConfig`, `AppConfig`, `RAGConfig`, `DATA_DIR` 등 설정 저장 메커니즘 | ✅ 최신 |

## ⚠️ 02_azure_setup.md 상태

`02_azure_setup.md`는 **현재 빈 파일입니다** (0 lines). 동료 엔지니어가 초안을 작성 중이며, 확인되는 대로 반영됩니다. 이 파일 구조 자체는 유지되며, 빈 상태일 뿐입니다. Azure 배포가 시급하면 동료에게 문의해주세요.

## 퀵 스타트 (로컬 개발)

```bash
# 1. 저장소 클론 및 의존성 설치
git clone <repo> AIS-Cloosphere && cd AIS-Cloosphere

# 2. Python 환경 (uv 필수, pip/poetry 금지)
uv sync

# 3. Node.js 의존성
npm ci --force
npm run build

# 4. 환경 변수 (backend/.env)
#    자세한 목록은 01_local_setup.md 참조
cp .env.example backend/.env
# 편집 필요: DATABASE_URL, AZURE_OPENAI_*, SEARCH_ENGINE_*, ...

# 5. 마이그레이션
cd backend && alembic upgrade head && cd ..

# 6. 백엔드 실행
cd backend && PORT=8080 ./dev.sh

# 7. 프론트엔드 (새 터미널)
npm run dev
# http://localhost:5173
```

## 주요 환경 변수 카테고리

자세한 목록은 [`01_local_setup.md`](./01_local_setup.md) 참조. 여기서는 카테고리만 요약:

| 카테고리 | 대표 변수 |
|---|---|
| **Database** | `DATABASE_URL`, `DATABASE_SCHEMA` |
| **Azure OpenAI** | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` |
| **Search Engine** | `SEARCH_ENGINE_TYPE` + 18개 엔진별 세부 변수 ([search_engine/README.md](../search_engine/README.md)) |
| **RAG Embedding** | `RAG_EMBEDDING_ENGINE`, `RAG_EMBEDDING_MODEL` |
| **Auth / OAuth** | `WEBUI_SECRET_KEY`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_CLIENT_TENANT_ID` |
| **SharePoint** | `ONEDRIVE_CLIENT_ID_BUSINESS`, `ONEDRIVE_SHAREPOINT_TENANT_ID`, `ONEDRIVE_SHAREPOINT_URL` ([sharepoint/](../sharepoint/README.md) 참조, dual-naming 주의) |
| **License** | `LICENSE_KEYS`, `FEATURE_KEYS`, `ENABLE_LICENSE_ENFORCEMENT`, `CLOOSPHERE_PUBLIC_KEY` |
| **Memory** | `MEMORY_EXTRACTION_MODEL`, `MEMORY_EXTRACTION_CONFIDENCE` ([memory/](../memory/README.md)) |
| **Code Gateway** | `ENABLE_CODE_GATEWAY`, `CODE_GATEWAY_PROVIDERS` |
| **Vector DB (legacy)** | `VECTOR_DB` (deprecated, 새 코드는 `SEARCH_ENGINE_TYPE` 사용) |

## 기술 스택 요구사항

| Layer | 요구사항 |
|---|---|
| Python | **3.12 이상** (`uv sync`로 자동 설치) |
| Node.js | 18.13.0 ~ 22.x.x (package.json `engines` 참조) |
| Package manager (Python) | **`uv`** (pip/poetry 사용 금지) |
| Package manager (JS) | `npm` |
| DB | PostgreSQL (권장) 또는 SQLite (개발) |
| Vector DB | Azure AI Search / pgvector / Elasticsearch / Vertex AI Search |
| OS | Linux (WSL2 포함) 권장, macOS 지원 |

## 관련 문서

- [`../db_migration/`](../db_migration/README.md) — Alembic 마이그레이션 작성/실행
- [`../license/`](../license/README.md) — License 시스템 설정
- [`../search_engine/`](../search_engine/README.md) — 벡터 DB 설정 전체

## 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-04-08 | README 신규 추가 (신스타일 마이그레이션) + 02_azure_setup.md 빈 파일 상태 명시 | `docs/eng-docs-refresh` |
| 2026-01-30 | 01, 03 파일 초기 작성 | |
