---
paths:
  - "backend/open_webui/routers/usage.py"
  - "backend/open_webui/routers/audit_logs.py"
  - "backend/open_webui/models/usage.py"
  - "backend/open_webui/models/audit_log.py"
  - "backend/open_webui/utils/audit*.py"
  - "src/lib/components/admin/Monitoring/**/*.svelte"
---

# 모니터링(Usage/Audit) 규칙

## Usage 라우터 (routers/usage.py)
- `/`: GET 사용량 통계 (필터: 날짜, 사용자, 에이전트, 모델)
- `/export`: GET CSV 내보내기
- admin 또는 `admin.monitoring` 권한 필요

## Usage 모델
```python
class Usage(Base):
    __tablename__ = "log_usage"
    id, user_id, chat_id, agent_id(nullable)
    model_id, message_id, message_step
    message_type, total_tokens
    usage(JSON), tool_calls(JSON)
    created_at
```
- `message_type`: UsageMessageType Enum (chat, embedding, generation, agent_state,
  tool_call, title_generation, tags_generation, emoji_generation, query_generation...)
- `agent_id`: 워크스페이스 에이전트 (base_model_id가 있는 경우)
- `model_id`: 실제 사용된 LLM 모델

## Audit Log 라우터 (routers/audit_logs.py)
- `/`: GET 감사 로그 목록
- `/export`: GET CSV 내보내기

## Audit Log 모델
```python
class AuditLog(Base):
    __tablename__ = "log_audit"
    id, user_id, action, resource_type, resource_id
    details(JSON), ip_address, user_agent
    created_at
```

## 감사 로깅 유틸리티 (utils/audit_logger.py)
```python
AuditLogger.log_audit(
    user_id, action, resource_type, resource_id,
    details=None, request=None,
)
```

## 프론트엔드 (admin/Monitoring/)
- `Usage.svelte`: 사용량 통계, 필터, 차트
- `AuditLogs.svelte`: 감사 로그 목록, CSV 내보내기
- `SystemInfo.svelte`: 시스템 정보

## 참조 파일
- `routers/usage.py`, `routers/audit_logs.py`
- `models/usage.py`, `models/audit_log.py`
- `utils/audit_logger.py`: 감사 로깅 유틸리티
