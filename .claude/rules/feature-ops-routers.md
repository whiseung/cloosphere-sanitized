---
paths:
  - "backend/open_webui/routers/notifications.py"
  - "backend/open_webui/routers/schedules.py"
  - "backend/open_webui/routers/data_retention.py"
  - "backend/open_webui/routers/admin_memory.py"
  - "backend/open_webui/routers/bi_dashboard.py"
  - "backend/open_webui/routers/workspace_tags.py"
  - "backend/open_webui/routers/document_profiles.py"
  - "backend/open_webui/routers/embed_widgets.py"
  - "backend/open_webui/routers/guide.py"
  - "backend/open_webui/routers/sr.py"
  - "backend/open_webui/routers/cloocus.py"
  - "backend/open_webui/routers/devtools.py"
  - "backend/open_webui/models/schedules.py"
  - "backend/open_webui/models/memory_retention_policy.py"
  - "backend/open_webui/models/memory_entity.py"
  - "backend/open_webui/models/bi_dashboard.py"
  - "backend/open_webui/models/workspace_tags.py"
  - "backend/open_webui/models/document_profile.py"
  - "backend/open_webui/models/embed_widgets.py"
  - "backend/open_webui/models/cloocus_admin.py"
---

# 운영/관리 라우터 묶음

작은 규모의 관리/운영 라우터들. 대부분 admin 또는 `admin.*` 권한 필요.
공통 CRUD 패턴은 `backend-router.md` 참조.

## Notifications (routers/notifications.py, models: 설정만 config)
다채널 알림 발송 설정 (Email/Webhook/Slack 등).
- `GET /channels`: 사용 가능한 채널 목록
- `GET/POST /config`: 채널별 설정 (SMTP, Webhook URL 등)
- `POST /email/test-connection`, `/email/test`: SMTP 연결/전송 테스트
- `POST /webhook/test`: Webhook 발송 테스트

## Schedules (routers/schedules.py, models/schedules.py)
Cron 기반 예약 작업 (에이전트/프롬프트를 주기적으로 실행).
- CRUD 표준 + `toggle`, `run` (즉시 실행), `share`
- `GET /{id}/tasks`: 실행 이력
- `GET /tasks/recent`: 전체 최근 실행 이력
- 내부 consumer가 Redis Streams로 소비

## Data Retention (routers/data_retention.py)
채팅/트레이스/로그 보존 정책 + 주기적 정리.
- `GET/POST /`: 설정 조회/저장
- `GET /stats`: 대상 레코드 수 미리보기
- `POST /cleanup`: 수동 정리 실행

## Admin Memory (routers/admin_memory.py, models/memory_retention_policy.py, models/memory_entity.py)
조직/사용자 장기 기억 관리자 도구.
- `/retention-policies`: 기억 보존 정책 CRUD
- `/audit-logs`: 기억 변경 감사 로그
- `/org`, `/org/{id}`: 조직 공용 기억
- `/users/{uid}/memories`: 특정 사용자 기억 조회/삭제
- `/entity-types`, `/entities`: 엔티티 타입/인스턴스 관리
- 연동: `extension_modules/agent/memory_*` 모듈이 실제 추출/병합 수행

## BI Dashboard (routers/bi_dashboard.py, models/bi_dashboard.py)
DbSphere 대시보드(여러 SQL 쿼리 + 차트 조합) 저장/공유.
- 생성/수정/삭제 + 실행 시 `dashboard_builder_agent` 사용

## Workspace Tags (routers/workspace_tags.py, models/workspace_tags.py)
워크스페이스 리소스(Agent/Knowledge/DbSphere/Prompt/Tool 등) 공용 태그.
- 프론트엔드: `WorkspaceTagSelector.svelte`가 소비

## Document Profiles (routers/document_profiles.py, models/document_profile.py)
KB 파일 업로드 시 적용할 파싱/청킹 프로파일 (PDF OCR, 표 추출 등 옵션 세트).

## Embed Widgets (routers/embed_widgets.py, models/embed_widgets.py, extension_modules/embed_sso/)
외부 사이트 임베드용 위젯 + SSO 토큰 발급. 위젯 단위로 에이전트/허용 도메인 화이트리스트 설정.

## Guide (routers/guide.py, extension_modules/guide_agent/)
사용자 가이드 에이전트 — 제품 사용법 질의에 답변. 관리자가 가이드 소스 관리.

## SR (routers/sr.py)
Speech Recognition / Summary Report 계열 — audio.py와 별개. 세부 용도는 라우터 docstring 참조.

## Cloocus (routers/cloocus.py, models/cloocus_admin.py)
Cloocus 브랜딩/조직 특화 관리자 기능 (라이선스·내부 관리 도구).

## DevTools (routers/devtools.py)
개발/디버그용 엔드포인트. 프로덕션 환경에서는 비활성화되어야 함.

## 공통 사항
- 권한: 대부분 `get_admin_user` 또는 `admin.settings`/`admin.monitoring` 그룹 권한
- Config 엔드포인트는 `open_webui.config`의 `PersistentConfig` 값 읽기/쓰기
- Background 작업은 Redis Streams 내부 consumer 사용 (외부 워커 제거 완료)

## 참조 파일
- `routers/<name>.py`: 각 라우터
- `models/<name>.py`: 데이터 모델 (있는 경우)
- 관련 프론트엔드: 주로 `src/lib/components/admin/Settings/`의 해당 탭
