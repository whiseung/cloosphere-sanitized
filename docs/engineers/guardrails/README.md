> Last Updated: 2026-04-08

# Guardrails (가드레일)

가드레일은 모델 입출력에 대한 보안 필터링 및 콘텐츠 제어 시스템입니다. **감지된 위반 사항은 별도의 `guardrail_log` 테이블에 기록**되며, 관리자 화면에서 조회할 수 있습니다.

> **확장 기능 — File Guardrail**: `backend/open_webui/utils/file_guardrails.py`는 파일 업로드 전용 5-stage 파이프라인을 제공합니다. `routers/files.py`에서 업로드 시점에 호출되며, 본 모듈의 `GuardrailEngine`을 재사용합니다.
>
> | Stage | 함수 | 역할 |
> |---|---|---|
> | 1. Pre-Storage | `detect_macros` | Office 매크로 감지 (`.doc`, `.docm`, `.xls` 등) |
> | 2. Post-Storage | `strip_exif_metadata` | 이미지 EXIF 메타데이터 제거 |
> | 2. Post-Storage | `detect_nsfw_via_llm` | LLM 기반 NSFW 이미지 감지 |
> | 3. Text | `apply_text_guardrails` / `apply_text_guardrails_with_llm` | 본 모듈의 `GuardrailEngine` 재사용 (PII + blocked_words + LLM judge). **block-only 전략 강제** (파일 업로드는 redact/mask 부적합) |
> | 4. Classification | `classify_document` | LLM 기반 문서 분류 (카테고리 자동 태깅) |
>
> **Orchestrator**: `run_pre_storage_guardrails`, `run_post_storage_guardrails`, `run_text_guardrails`, `run_classification`. 이들이 `routers/files.py`에서 업로드 플로우의 각 단계에 호출됩니다.
>
> **Config 플래그** (`config.py`): `FILE_GUARDRAIL_ENABLED`, `FILE_GUARDRAIL_SCOPES`.
>
> File Guardrail은 본 `guardrails` 모듈과 **Guardrail 정의를 공유**하지만 (동일한 `Guardrails.get_guardrail_by_id()` 사용), 실행 파이프라인은 분리되어 있습니다. File Guardrail은 **FastAPI 미들웨어가 아니라 utility 함수 집합**이며, 업로드 라우터에서 명시적으로 호출됩니다.

## 문서 목록

1. [개요](./01_overview.md) - 가드레일 시스템 소개
2. [아키텍처](./02_architecture.md) - 데이터 모델 및 처리 엔진
3. [API](./03_api.md) - REST API 엔드포인트 (가드레일 CRUD + **guardrail_log 조회 4개**)
4. [프론트엔드](./04_frontend.md) - UI 컴포넌트 및 통합 (Editor + **GuardrailLogs 뷰**)

## 빠른 시작

### 1. 마이그레이션 실행

```bash
cd backend
alembic upgrade head
```

### 2. 가드레일 생성

워크스페이스 > 가드레일 > 새로 만들기

### 3. 에이전트에 적용

에이전트 편집 > 가드레일 섹션에서 선택

## 주요 기능

- **PII 탐지**: 이메일, 신용카드, IP 주소 등 자동 탐지
- **처리 전략**: block, redact, mask, hash 지원
- **커스텀 패턴**: 정규식 기반 사용자 정의 탐지
- **금지어**: 특정 단어/문구 차단
- **LLM Judge**: AI 모델을 활용한 콘텐츠 심사

## 파일 구조

```
backend/open_webui/
├── models/guardrails.py      # DB 모델
├── routers/guardrails.py     # API 라우터
├── utils/guardrails.py       # 처리 엔진
└── migrations/versions/
    └── d4e5f6a7b8c9_add_guardrail_table.py

src/lib/
├── apis/guardrails/          # API 클라이언트
├── components/workspace/
│   ├── Guardrails/           # 관리 UI
│   └── Agents/Guardrails/    # 에이전트 연동
└── routes/(app)/workspace/guardrails/  # 페이지 라우팅
```
