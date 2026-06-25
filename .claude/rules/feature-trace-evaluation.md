---
paths:
  - "backend/open_webui/routers/traces.py"
  - "backend/open_webui/routers/trace_analysis.py"
  - "backend/open_webui/routers/evaluations.py"
  - "backend/open_webui/routers/auto_evaluations.py"
  - "backend/open_webui/routers/guardrail_logs.py"
  - "backend/open_webui/models/message_trace.py"
  - "backend/open_webui/models/trace_analysis.py"
  - "backend/open_webui/models/auto_evaluations.py"
  - "backend/open_webui/models/guardrail_log.py"
  - "backend/open_webui/models/feedbacks.py"
  - "backend/extension_modules/auto_evaluation/**/*.py"
  - "backend/extension_modules/trace_analysis/**/*.py"
---

# 트레이스 / 평가 / 피드백 / 가드레일 로그 규칙

관찰성(Observability) 계열 5개 라우터. 권한은 `admin.monitoring` / `admin.evaluations`
그룹 권한 기반 (4단계 레벨 — read/write 의존성 사용).

## Traces (routers/traces.py, models/message_trace.py)
메시지 단위 LLM 호출 트리(Trace) 저장·조회.
- `GET /{trace_id}`: 트레이스 트리 응답
- `GET /chat/{chat_id}/message/{message_id}`: 메시지별 트레이스
- `GET /chat/{chat_id}`: 채팅 트레이스 목록
- `GET /`: 전체 목록 (필터 지원)
- `GET /stats/summary`: 통계 요약
- `DELETE /cleanup`: 보존 기간 초과분 정리 (data_retention과 연동)
- 의존성: admin 또는 `admin.monitoring` 권한

## Trace Analysis (routers/trace_analysis.py, extension_modules/trace_analysis/)
Trace를 LLM이 분석해 품질/문제점 보고서 생성.
- `POST /analyze`: 트레이스 분석 실행 (LLM 호출, BackgroundTask)
- `GET /{analysis_id}`, `/by-trace/{trace_id}`
- `DELETE /{analysis_id}`
- 구현: `extension_modules/trace_analysis/analyzer.py` + `prompts.py`

## Evaluations (routers/evaluations.py, models/feedbacks.py)
사용자 피드백(👍/👎/코멘트) 수집.
- `GET/POST /config`: 평가 설정
- `GET /feedbacks/all`, `/feedbacks/all/export`, `DELETE /feedbacks/all` (admin)
- `GET /feedbacks/user`, `DELETE /feedbacks`
- `POST /feedback`, `GET/POST/DELETE /feedback/{id}`
- 의존성: admin 또는 `admin.evaluations` 권한 (read/write 분리)

## Auto Evaluations (routers/auto_evaluations.py, extension_modules/auto_evaluation/)
LLM-as-Judge 자동 평가 (정확도/관련성/안전성 등).
- `GET /`, `/stats`, `/export`, `/{id}`: 조회
- `POST /`, `PUT /{id}`, `DELETE /{id}`, `DELETE /`: CRUD
- `GET /chat/{chat_id}`, `/message/{message_id}`: 범위별 조회
- 구현: `extension_modules/auto_evaluation/evaluator.py`(LLM 호출) + `trigger.py`(자동 실행 트리거)

## Guardrail Logs (routers/guardrail_logs.py, models/guardrail_log.py)
가드레일 차단/리댁션 로그.
- `GET /`: 페이지네이션 + 필터 (user_id, guardrail_id, action, detection_source)
- `GET /actions`, `/detection-sources`: 필터 옵션
- `GET /{guardrail_log_id}`: 단일 조회
- 의존성: admin 또는 `admin.monitoring` 권한

## 프론트엔드
- Admin Monitoring 탭: `src/lib/components/admin/Monitoring/` (Usage, AuditLogs, Traces, GuardrailLogs)
- Admin Evaluations 탭: `src/lib/components/admin/Evaluations/` (Feedbacks, AutoEvaluations)
- API 클라이언트: `src/lib/apis/traces/`, `trace-analysis/`, `evaluations/`, `auto-evaluations/`, `guardrail-logs/`

## 참조 파일
- `routers/traces.py` / `models/message_trace.py`: 트레이스
- `routers/trace_analysis.py` / `models/trace_analysis.py` / `extension_modules/trace_analysis/`: 분석
- `routers/evaluations.py` / `models/feedbacks.py`: 피드백
- `routers/auto_evaluations.py` / `models/auto_evaluations.py` / `extension_modules/auto_evaluation/`: 자동 평가
- `routers/guardrail_logs.py` / `models/guardrail_log.py`: 가드레일 로그
