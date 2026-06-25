# 설정 관리 가이드

## 설정 계층

Cloosphere는 3단계 설정 계층을 사용합니다:

```
┌─────────────────────────────────────┐
│  1. 환경 변수 (env.py)               │
│     - 서버 시작 시 로드               │
│     - 변경 시 재시작 필요             │
├─────────────────────────────────────┤
│  2. DB 설정 (Config 테이블)          │
│     - 런타임 변경 가능                │
│     - 관리자 API로 수정               │
├─────────────────────────────────────┤
│  3. AppConfig (request.app.state)    │
│     - 메모리에 캐시                   │
│     - 빠른 접근                       │
└─────────────────────────────────────┘
```

---

## 1. 환경 변수 (env.py)

### 파일 위치

- **정의**: `backend/open_webui/env.py`
- **사용**: `backend/open_webui/config.py`에서 import

### 주요 환경 변수

#### 데이터베이스

```bash
# SQL 데이터베이스
DATABASE_URL=sqlite:///./data/webui.db
# PostgreSQL: postgresql://user:pass@localhost:5432/dbname

# 벡터 데이터베이스
VECTOR_DB=qdrant                    # qdrant, milvus, pgvector, azure_search, chroma
QDRANT_URL=http://localhost:6333
MILVUS_URI=http://localhost:19530
AZURE_SEARCH_ENDPOINT=https://xxx.search.windows.net
AZURE_SEARCH_KEY=xxx
```

#### LLM 프로바이더

```bash
# Ollama
ENABLE_OLLAMA_API=true
OLLAMA_BASE_URLS=http://localhost:11434,http://localhost:11435  # 로드밸런싱

# OpenAI
ENABLE_OPENAI_API=true
OPENAI_API_BASE_URLS=https://api.openai.com/v1
OPENAI_API_KEYS=sk-xxx

# Azure OpenAI
AZURE_OPENAI_API_BASE_URL=https://xxx.openai.azure.com/
AZURE_OPENAI_API_KEY=xxx
AZURE_OPENAI_API_VERSION=2024-02-01
```

#### RAG/검색

```bash
# 임베딩
RAG_EMBEDDING_ENGINE=openai         # local, openai, azure
RAG_EMBEDDING_MODEL=text-embedding-ada-002

# Azure OpenAI 임베딩
RAG_AZURE_OPENAI_API_BASE_URL=https://xxx.openai.azure.com/
RAG_AZURE_OPENAI_API_KEY=xxx

# 검색 설정
RAG_TOP_K=3                         # 검색 결과 수
RELEVANCE_THRESHOLD=0.7             # 최소 관련성 점수
CHUNK_SIZE=1024                     # 문서 청킹 크기
CHUNK_OVERLAP=20                    # 청크 오버랩

# 웹 검색
ENABLE_WEB_SEARCH=true
WEB_SEARCH_ENGINE=tavily            # tavily, brave, google, bing, duckduckgo
TAVILY_API_KEY=xxx
WEB_SEARCH_RESULT_COUNT=3
```

#### 인증

```bash
# 기본 인증
WEBUI_AUTH=true
WEBUI_SECRET_KEY=xxx                # JWT 서명 키 (자동 생성)
JWT_EXPIRES_IN=7d

# 회원가입
ENABLE_SIGNUP=true
DEFAULT_USER_ROLE=user              # pending, user

# OAuth
ENABLE_OAUTH_SIGNUP=true
OAUTH_CLIENT_ID=xxx
OAUTH_CLIENT_SECRET=xxx
OPENID_PROVIDER_URL=https://login.microsoftonline.com/xxx/v2.0

# Microsoft OAuth
MICROSOFT_CLIENT_ID=xxx
MICROSOFT_CLIENT_SECRET=xxx
MICROSOFT_CLIENT_TENANT_ID=xxx

# LDAP
ENABLE_LDAP=false
LDAP_SERVER_HOST=ldap.example.com
LDAP_SERVER_PORT=389
```

#### 기능 플래그

```bash
# 기능 활성화
ENABLE_CODE_EXECUTION=true
ENABLE_IMAGE_GENERATION=true
ENABLE_CHANNELS=true
ENABLE_SHAREPOINT_INTEGRATION=true
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true

# 제한
MAX_FILE_SIZE=100MB
MAX_UPLOAD_COUNT=10
```

#### 서버

```bash
# 기본
PORT=8080
WEBUI_URL=http://localhost:8080
DATA_DIR=/app/backend/data

# Redis (분산 환경)
REDIS_URL=redis://localhost:6379

# 워커
UVICORN_WORKERS=1
```

### 환경 변수 로드

```python
# env.py
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/webui.db")
ENABLE_OLLAMA_API = os.environ.get("ENABLE_OLLAMA_API", "true").lower() == "true"
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
```

---

## 2. PersistentConfig (DB 저장)

### 개요

런타임에 변경 가능한 설정을 DB에 저장합니다.

### PersistentConfig 클래스

```python
# config.py

class PersistentConfig:
    """DB에 저장되는 설정"""

    def __init__(
        self,
        env_name: str,           # 환경 변수 이름
        db_key: str,             # DB 저장 키
        default_value: Any       # 기본값
    ):
        self.env_name = env_name
        self.db_key = db_key
        self.default_value = default_value

    @property
    def value(self):
        # 1. DB에서 조회
        db_value = get_config_value(self.db_key)
        if db_value is not None:
            return db_value

        # 2. 환경 변수
        env_value = os.environ.get(self.env_name)
        if env_value is not None:
            return self._parse(env_value)

        # 3. 기본값
        return self.default_value

    @value.setter
    def value(self, new_value):
        save_config_value(self.db_key, new_value)
```

### 사용 예시

```python
# config.py

# 정의
ENABLE_WEB_SEARCH = PersistentConfig(
    "ENABLE_WEB_SEARCH",
    "rag.web_search.enabled",
    True
)

RAG_TOP_K = PersistentConfig(
    "RAG_TOP_K",
    "rag.top_k",
    3
)

# 읽기
if ENABLE_WEB_SEARCH.value:
    results = web_search(query)

# 쓰기 (관리자 API에서)
ENABLE_WEB_SEARCH.value = False
```

### DB Config 테이블

```python
# models/configs.py

class Config(Base):
    __tablename__ = "config"

    id = Column(Integer, primary_key=True)
    data = Column(JSON)           # 모든 설정을 JSON으로 저장
    version = Column(Integer)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

---

## 3. AppConfig (런타임 캐시)

### 개요

자주 접근하는 설정을 `request.app.state.config`에 캐시합니다.

### AppConfig 클래스

```python
# config.py

class AppConfig:
    """FastAPI app.state.config에 저장되는 설정"""

    # 기본 설정
    WEBUI_URL: str
    ENABLE_SIGNUP: bool
    DEFAULT_USER_ROLE: str

    # Ollama
    ENABLE_OLLAMA_API: bool
    OLLAMA_BASE_URLS: list[str]

    # OpenAI
    ENABLE_OPENAI_API: bool
    OPENAI_API_BASE_URLS: list[str]
    OPENAI_API_KEYS: list[str]

    # RAG
    RAG_EMBEDDING_ENGINE: str
    RAG_EMBEDDING_MODEL: str
    RAG_TOP_K: int
    RELEVANCE_THRESHOLD: float

    # 웹 검색
    ENABLE_WEB_SEARCH: bool
    WEB_SEARCH_ENGINE: str
    WEB_SEARCH_RESULT_COUNT: int

    # 기능 플래그
    ENABLE_CODE_EXECUTION: bool
    ENABLE_IMAGE_GENERATION: bool
```

### 초기화 (main.py)

```python
# main.py

from open_webui.config import AppConfig

app = FastAPI()

@app.on_event("startup")
async def startup():
    # 설정 로드
    app.state.config = AppConfig()
    app.state.config.ENABLE_WEB_SEARCH = ENABLE_WEB_SEARCH.value
    app.state.config.RAG_TOP_K = RAG_TOP_K.value
    # ...
```

### 라우터에서 사용

```python
from fastapi import Request

@router.get("/search")
async def search(query: str, request: Request):
    config = request.app.state.config

    if not config.ENABLE_WEB_SEARCH:
        raise HTTPException(status_code=400, detail="Web search disabled")

    results = web_search(
        query=query,
        engine=config.WEB_SEARCH_ENGINE,
        count=config.WEB_SEARCH_RESULT_COUNT
    )
    return results
```

---

## 4. 관리자 설정 API

### 설정 조회

```python
# routers/configs.py

@router.get("/app")
async def get_app_config(user=Depends(get_admin_user)):
    """현재 앱 설정 조회"""
    return {
        "ENABLE_WEB_SEARCH": ENABLE_WEB_SEARCH.value,
        "WEB_SEARCH_ENGINE": WEB_SEARCH_ENGINE.value,
        "RAG_TOP_K": RAG_TOP_K.value,
        "ENABLE_SIGNUP": ENABLE_SIGNUP.value,
        # ...
    }
```

### 설정 변경

```python
@router.post("/app")
async def update_app_config(
    form_data: AppConfigForm,
    request: Request,
    user=Depends(get_admin_user)
):
    """앱 설정 변경"""

    # DB에 저장
    if form_data.ENABLE_WEB_SEARCH is not None:
        ENABLE_WEB_SEARCH.value = form_data.ENABLE_WEB_SEARCH

    if form_data.RAG_TOP_K is not None:
        RAG_TOP_K.value = form_data.RAG_TOP_K

    # 캐시 업데이트
    request.app.state.config.ENABLE_WEB_SEARCH = ENABLE_WEB_SEARCH.value
    request.app.state.config.RAG_TOP_K = RAG_TOP_K.value

    return {"success": True}
```

---

## 5. 설정 우선순위

```
1. DB 저장 값 (PersistentConfig)     ← 최우선
2. 환경 변수 (os.environ)
3. 코드 기본값                        ← 최하위
```

### 예시

```python
# 환경 변수: RAG_TOP_K=5
# DB 저장: rag.top_k = 10
# 기본값: 3

RAG_TOP_K.value  # → 10 (DB 값 우선)
```

---

## 6. 설정 카테고리

### 구조

```python
# DB에 저장되는 설정 구조
config_data = {
    "oauth": {
        "enable_signup": True,
        "enable_org_unit_mapping": True
    },
    "rag": {
        "top_k": 3,
        "relevance_threshold": 0.7,
        "web_search": {
            "enabled": True,
            "engine": "tavily"
        }
    },
    "ui": {
        "default_models": ["gpt-4"],
        "enable_community_sharing": False
    },
    "audio": {
        "tts_engine": "openai",
        "stt_engine": "openai"
    }
}
```

### DB 키 네이밍

```python
# 점(.)으로 계층 구분
"oauth.enable_signup"           # oauth > enable_signup
"rag.web_search.enabled"        # rag > web_search > enabled
"ui.default_models"             # ui > default_models
```

---

## 7. 새 설정 추가하기

### 1단계: 환경 변수 정의

```python
# env.py
MY_NEW_SETTING = os.environ.get("MY_NEW_SETTING", "default")
```

### 2단계: PersistentConfig 정의

```python
# config.py
MY_NEW_SETTING = PersistentConfig(
    "MY_NEW_SETTING",        # 환경 변수 이름
    "category.my_setting",   # DB 키
    "default"                # 기본값
)
```

### 3단계: AppConfig에 추가 (선택적)

```python
# config.py
class AppConfig:
    MY_NEW_SETTING: str
```

### 4단계: 초기화 (main.py)

```python
app.state.config.MY_NEW_SETTING = MY_NEW_SETTING.value
```

### 5단계: 관리자 API 추가 (선택적)

```python
# routers/configs.py
@router.post("/app")
async def update_config(form_data: ConfigForm, request: Request):
    if form_data.MY_NEW_SETTING is not None:
        MY_NEW_SETTING.value = form_data.MY_NEW_SETTING
        request.app.state.config.MY_NEW_SETTING = form_data.MY_NEW_SETTING
```

---

## 참조 파일

| 파일 | 역할 | 크기 |
|------|------|------|
| `env.py` | 환경 변수 로드 | - |
| `config.py` | 설정 관리, PersistentConfig | 82KB |
| `routers/configs.py` | 관리자 설정 API | 11KB |
| `models/configs.py` | Config 테이블 모델 | - |
