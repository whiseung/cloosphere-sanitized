---
paths:
  - "backend/open_webui/config.py"
  - "backend/open_webui/env.py"
---

# 설정 관리 규칙

## PersistentConfig 패턴
```python
# 환경 변수 기본값 → DB 저장 → 런타임 변경
SOME_SETTING = PersistentConfig(
    "SOME_SETTING",           # env_name
    "some.setting.path",      # config_path (DB 내 점 표기법)
    os.environ.get("SOME_SETTING", "default_value"),  # env_value
)
```
- DB 값 우선 (ENABLE_PERSISTENT_CONFIG=True 시)
- PERSISTENT_CONFIG_REGISTRY에 자동 등록
- `save()` → DB 영속화, `update()` → DB에서 새로고침

## AppConfig 클래스
```python
# main.py에서 초기화
app.state.config = AppConfig(redis_url=REDIS_URL, redis_sentinels=REDIS_SENTINELS)

# PersistentConfig 등록
app.state.config.SOME_SETTING = SOME_SETTING

# 라우터에서 접근
value = request.app.state.config.SOME_SETTING

# 런타임 변경 (자동 DB 저장 + Redis 동기화)
request.app.state.config.SOME_SETTING = new_value
```

## 새 설정 추가 3단계
1. `env.py`에 환경 변수 선언 (기본값 포함)
2. `config.py`에 PersistentConfig 래핑 (DB 영속화 필요 시)
3. `main.py`에서 `app.state.config.XXX = XXX` 등록

## 로그 레벨 설정
```python
# env.py — 로그 소스 목록
SRC_LOG_LEVELS = {}  # AUDIO, CONFIG, DB, IMAGES, MAIN, MODELS, OLLAMA, OPENAI, RAG, WEBHOOK, SOCKET, OAUTH

# 사용
log.setLevel(SRC_LOG_LEVELS["MODELS"])
```

## Config DB 테이블
- `Config(id, data: JSON, version: int, created_at, updated_at)`
- 단일 레코드 — `data` JSON에 모든 설정 중첩 저장
- `get_config_value("rag.template")` → 점 표기법으로 중첩 접근

## 주의사항
- config.py는 82KB — 수정 시 전체 구조 파악 필수
- 환경 변수명은 대문자 SNAKE_CASE
- Redis 옵션: 분산 배포 시 설정 동기화 (redis_key: `open-webui:config:{key}`)

## 참조 파일
- `config.py`: 전체 설정 정의 (PersistentConfig, AppConfig)
- `env.py`: 환경 변수 로드, SRC_LOG_LEVELS, DATABASE_URL 등
- `internal/db.py`: Config 테이블 모델
