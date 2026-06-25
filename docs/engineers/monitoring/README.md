> Last Updated: 2026-04-08

# Monitoring (모니터링) 모듈

Cloosphere의 Usage 추적 및 Audit Logging 기능에 대한 기술 문서입니다.

> **문서 구조 참고**: 이 폴더는 토픽 기반 네이밍 (`01_usage_tracking`, `02_audit_logging`, `03_admin_ui`, `04_tracing`)을 사용합니다.
>
> **관련 별도 폴더**:
> - [`bi_dashboard/`](../bi_dashboard/README.md) — 9개 컴포넌트 기반 BI 대시보드 (`admin/Monitoring/BiDashboard/`)
> - [`guardrails/` 03_api.md](../guardrails/03_api.md#1-b-guardrail-logs-api-apiv1guardrail-logs) — Guardrail 감지 로그 API (`/api/v1/guardrail-logs`)

## 목차

1. [개요](#개요)
2. [주요 기능](#주요-기능)
3. [상세 문서](#상세-문서)
4. [퀵 스타트](#퀵-스타트)

---

## 개요

모니터링 모듈은 시스템 사용량 추적(Usage)과 감사 로깅(Audit Logs) 기능을 제공합니다. 관리자는 API 사용량을 분석하고, 사용자 활동을 감사할 수 있습니다.

### 주요 개념

| 개념 | 설명 |
|------|------|
| **Usage** | LLM API 호출 사용량 (토큰 수, 요청 횟수 등) |
| **Agent ID** | 워크스페이스 에이전트 식별자 |
| **Model ID** | 실제 사용된 LLM 모델 식별자 (GPT-4, Claude 등) |
| **Audit Log** | 사용자 활동 기록 (로그인, 리소스 변경 등) |
| **Message Type** | 요청 유형 (chat, embedding, tool_call 등) |
| **Tracing** | AI 요청 처리 과정의 상세 추적 (LangSmith 스타일) |

### 데이터 흐름

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  API 요청       │────▶│  Usage 추적     │────▶│  log_usage      │
│  (Chat, Agent)  │     │  Middleware     │     │  테이블         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       │ 스트리밍 응답에서
        │                       │ usage 정보 추출
        ▼                       ▼
   OpenAI Router          stream_options:
   Ollama Router          {"include_usage": true}
```

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  사용자 활동    │────▶│  Audit Logger   │────▶│  log_audit      │
│  (CRUD 등)      │     │  Middleware     │     │  테이블         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       │ IP, User Agent,
        │                       │ 리소스 정보 기록
        ▼                       ▼
   라우터 함수            utils/audit_logger.py
```

---

## 주요 기능

### 1. Usage 추적

- **LLM 사용량 기록**: 채팅, 에이전트, 백그라운드 태스크 모든 API 호출 기록
- **토큰 사용량**: 입력/출력 토큰 수, 총 토큰 수 기록
- **에이전트 분리**: agent_id (워크스페이스 에이전트)와 model_id (실제 LLM) 분리 추적
- **임베딩 추적**: OpenAI, Azure, Ollama 임베딩 API 호출 기록
- **백그라운드 태스크**: 제목 생성, 태그 생성, 이모지 생성 등 추적

### 2. Audit Logging

- **사용자 활동 기록**: 로그인, 로그아웃, 리소스 CRUD 등
- **IP 주소 추적**: 요청 출처 IP 기록
- **상세 정보**: 변경 전/후 데이터, 오류 메시지 등
- **CSV 내보내기**: 감사 로그 다운로드

### 3. Tracing (트레이싱)

- **Run 기반 트리 구조**: LangSmith 스타일의 처리 단계 추적
- **상세 입출력 기록**: 각 단계의 inputs/outputs 저장
- **토큰 사용량**: LLM Run별 토큰 사용량 기록
- **지연 시간 측정**: 각 단계의 실행 시간 측정

### 4. 관리자 대시보드

- **사용량 통계**: 일별/주별/월별 사용량 차트
- **사용자별 분석**: 사용자별 토큰 사용량, 요청 횟수
- **모델별 분석**: LLM 모델별 사용 빈도
- **에이전트별 분석**: 워크스페이스 에이전트별 사용량
- **트레이싱 뷰어**: 메시지별 처리 과정 상세 확인

---

## 상세 문서

| 문서 | 설명 |
|------|------|
| [01_usage_tracking.md](./01_usage_tracking.md) | Usage 추적 상세 |
| [02_audit_logging.md](./02_audit_logging.md) | 감사 로깅 상세 |
| [03_admin_ui.md](./03_admin_ui.md) | 관리자 UI 컴포넌트 |
| [04_tracing.md](./04_tracing.md) | 트레이싱 (LangSmith 스타일 Run 추적) |

---

## 퀵 스타트

### 1. Usage 조회

```python
from open_webui.models.usage import Usages

# 사용자별 사용량 조회
usages = Usages.get_usages_by_user_id(user_id, skip=0, limit=100)

# 기간별 통계
stats = Usages.get_usage_stats(
    start_date=1706000000,
    end_date=1706100000,
    user_id=user_id,
    group_by="day"
)
```

### 2. Audit Log 기록

```python
from open_webui.utils.audit_logger import log_audit

# 활동 기록
log_audit(
    user_id=user.id,
    action="create",
    resource_type="knowledge",
    resource_id=knowledge.id,
    details={"name": knowledge.name},
    request=request,
)
```

### 3. 관리자 UI 접근

1. 관리자 패널 → Monitoring 탭
2. Usage 또는 Audit Logs 서브탭 선택
3. 필터 적용 (기간, 사용자, 모델 등)
4. 데이터 조회 또는 내보내기

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `ENABLE_USAGE_TRACKING` | Usage 추적 활성화 | `true` |
| `ENABLE_AUDIT_LOGGING` | Audit 로깅 활성화 | `true` |
| `USAGE_RETENTION_DAYS` | Usage 데이터 보존 기간 (일) | `365` |
| `AUDIT_RETENTION_DAYS` | Audit 로그 보존 기간 (일) | `90` |

---

## 관련 파일

### Backend

- `backend/open_webui/models/usage.py` - Usage 모델
- `backend/open_webui/models/audit_log.py` - Audit Log 모델
- `backend/open_webui/models/message_trace.py` - 트레이싱 모델
- `backend/open_webui/routers/usage.py` - Usage API
- `backend/open_webui/routers/audit_logs.py` - Audit Log API
- `backend/open_webui/routers/traces.py` - 트레이싱 API
- `backend/open_webui/utils/audit_logger.py` - 감사 로깅 유틸리티
- `backend/open_webui/routers/openai.py` - 채팅 usage 추적
- `backend/extension_modules/react/react_middleware_base.py` - 에이전트 usage 추적

### Frontend

- `src/lib/components/admin/Monitoring/Usage.svelte` - Usage 대시보드
- `src/lib/components/admin/Monitoring/AuditLogs.svelte` - Audit 로그 뷰어
- `src/lib/components/admin/Evaluations/Tracing.svelte` - 트레이싱 UI
- `src/lib/components/admin/Evaluations/RunTreeItem.svelte` - 트레이스 트리 아이템
- `src/lib/components/common/JsonTreeView.svelte` - JSON 트리 뷰어
- `src/lib/apis/usage/index.ts` - Usage API 클라이언트
- `src/lib/apis/audit_logs/index.ts` - Audit Log API 클라이언트
- `src/lib/apis/traces/index.ts` - 트레이싱 API 클라이언트
