> Last Updated: 2026-04-08

# 01. 로컬 개발 환경 셋업

## 프로젝트 개요

Cloosphere는 Open WebUI를 기반으로 확장된 엔터프라이즈 AI 플랫폼입니다. Backend는 Python FastAPI + SQLAlchemy + LangGraph, Frontend는 SvelteKit 기반입니다. 다양한 LLM (Azure OpenAI, Anthropic, Ollama), Vector DB (Azure Search, pgvector, Elasticsearch, Vertex AI Search), SharePoint/Entra ID 등을 통합 지원합니다.


## 1. 환경 설명

- **OS**: Linux (WSL2 포함) 권장, macOS 지원
- **Python**: **3.12 이상** (`uv`로 자동 설치 가능)
- **Node.js**: 18.13.0 ~ 22.x.x (`package.json` engines 참조)
- **Package Manager**: **`uv`** (Python), `npm` (Frontend) — pip/poetry 금지
- **데이터베이스**: PostgreSQL (권장, Azure PostgreSQL Flexible Server), SQLite (개발 간이 모드)
- **벡터 DB**: Azure AI Search / pgvector / Elasticsearch / Vertex AI Search (`SEARCH_ENGINE_TYPE`로 선택)
- **캐시**: Redis (Memory extraction debounce, 미설정 시 in-process fallback)
- 주요 디렉터리
  - `backend/`: FastAPI 백엔드 + `extension_modules/` (DbSphere, KbSphere, Search Engine, ReAct Agent 등)
  - `src/`: SvelteKit 프론트엔드


## 2. 빌드 및 실행 방법

### 2.1 VS Code 디버깅

1) 의존성 설치

```bash
# Node.js 설치 ubuntu 혹은 wsl2 기준
sudo apt update
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# Frontend 빌드
npm ci --force
npm run build
```


```bash
# Python (uv 필수, pip/poetry 금지)
# requirements.txt 대신 pyproject.toml + uv.lock 기반 sync 사용
uv sync

# 의존성 그룹별 설치 (필요 시)
uv sync --group test      # 테스트용
uv sync --all-groups      # 전체 (test + lint + dev)
```

> **레거시 주의**: `backend/requirements.txt`는 uv가 export한 스냅샷입니다. 사용자가 직접 `pip install`로 설치하지 **않습니다**. 항상 `uv sync`를 사용하세요.

2) 환경 변수 설정 (루트 `.env` 또는 VS Code 런치/터미널 환경)

필수(예시):

```bash
# Database (하단 3.1 참조)
DATABASE_URL=postgresql://<USER>:<URL_ENCODED_PASSWORD>@<HOST>:5432/<DB_NAME>?sslmode=require
DATABASE_SCHEMA=app

# Azure OpenAI (확장 파이프라인에서 사용)
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=<deployment_name>
AZURE_OPENAI_API_VERSION=2024-05-01-preview

# Azure AI Search (벡터 검색)
AZURE_SEARCH_ENDPOINT=https://<service>.search.windows.net
AZURE_SEARCH_API_KEY=<admin_key>
AZURE_SEARCH_INDEX=<index_name>
AZURE_SEARCH_VECTOR_DIM=1536

# 선택(멀티 인스턴스/세션)
REDIS_URL=redis://<host>:6379/0

# 퍼포먼스
UVICORN_WORKERS=2
DATABASE_POOL_SIZE=10
DATABASE_POOL_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=1800
```

3) VS Code 실행

F5로 디버깅 실행
브라우저 접속:
- http://localhost:8080

### 2.2 Docker 단일 이미지 빌드/실행 (예시)

```bash
# 이미지 빌드
docker build -t cloosphere/open-webui:local .

# 실행 (호스트의 .env 사용 권장)
docker run --rm -p 8080:8080 --env-file ./.env \
  --name openwebui cloosphere/open-webui:local
```

컨테이너 환경에서 `UVICORN_WORKERS`, DB 풀 관련 변수를 함께 지정하세요.


### 2.3 Docker Compose (예시)

`docker-compose.yml` 참고

```bash
docker compose up -d --build
```


## 3. 설정 방법

### 3.1 DB 구성 및 연결 (Azure PostgreSQL)

1) 연결 문자열 구성

env.example 참고

```text
DATABASE_TYPE=postgresql
DATABASE_HOST=
DATABASE_PORT=5432
DATABASE_NAME=
DATABASE_USER=
DATABASE_PASSWORD=
DATABASE_SCHEMA=app
DATABASE_POOL_SIZE=10
DATABASE_POOL_MAX_OVERFLOW=5
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=3600
```


2) 스키마/권한 설정(최초 1회, 관리자 계정)

```sql
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION cloosphere;
GRANT USAGE, CREATE ON SCHEMA app TO cloosphere;
ALTER ROLE cloosphere IN DATABASE db_cloosphere SET search_path = app, public;
```


### 3.2 Azure AI Search 구성

1) 리소스 준비: Azure AI Search 서비스와 Admin Key 확보

2) 환경 변수

```bash
AZURE_SEARCH_ENDPOINT=https://<service>search.windows.net
AZURE_SEARCH_API_KEY=<apikey>
AZURE_SEARCH_INDEX=default
AZURE_SEARCH_API_VERSION=2024-07-01
```

3) 인덱스 자동 생성: 최초 실행 시 지정한 인덱스가 없으면 자동 생성됩니다.


### 3.3 인증 연동 (Microsoft SSO)

1) Azure Entra ID → 앱 등록
- 리디렉션 URI: `https://<your-domain>/auth/microsoft/callback` (로컬 개발 시 http://localhost:8080 등)
- 권한/동의: 기본 OpenID/OAuth 권한
- Cloocus의 경우 Cloocus 태넌트에 앱등록이 되어야 함함

2) 환경 변수

```bash
MICROSOFT_CLIENT_ID=<app_id>
MICROSOFT_CLIENT_SECRET=<secret>
MICROSOFT_CLIENT_TENANT_ID=<tenant_id>
MICROSOFT_OAUTH_SCOPE=openid profile email
MICROSOFT_REDIRECT_URI=https://<your-domain>/auth/microsoft/callback
ENABLE_LOGIN_FORM=false    # 자체 로그인 폼 숨김 (SSO 전용 UI)
ENABLE_SIGNUP=true         # 필요 시 가입 허용
```

3) 흔한 오류
- `AADSTS500113: No reply address is registered`: 앱 등록의 Redirect URI 누락 → 추가 후 저장


## 4. 배포 방법 (ACR → Azure App Service)

1) 컨테이너 이미지 빌드/푸시

```bash
az login (권한있는 사용자 계정으로 azure cli 로그인)
az acr login --name <ACR_NAME>
docker buildx build --platform linux/amd64 -t <ACR_NAME>.azurecr.io/cloosphere:latest .
docker push <ACR_NAME>.azurecr.io/cloosphere:latest
```

2) App Service (Linux, Container)
- 이미지: `<ACR_NAME>.azurecr.io/openwebui:prod`
- 설정(Environment Variables):
  - `WEBSITES_PORT=8080`
  - 위 2.1의 모든 환경 변수 (DB/AI Search/SSO/성능 관련)
- 스케일 아웃: 2 인스턴스 이상

3) 연결 확인
- App Service 로그/헬스 체크로 API 200 응답 확인
- 최초 구동 시 마이그레이션 로그 확인 (스키마 권한 오류 주의)
