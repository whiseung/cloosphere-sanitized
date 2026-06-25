---
paths:
  - "backend/open_webui/routers/tools.py"
  - "backend/open_webui/routers/functions.py"
  - "backend/open_webui/routers/tool_connections.py"
  - "backend/open_webui/models/tools.py"
  - "backend/open_webui/models/functions.py"
  - "backend/open_webui/utils/plugin.py"
  - "src/lib/components/workspace/Tools/**/*.svelte"
---

# 도구/함수 관리 규칙

## Tools 라우터 (routers/tools.py)
- CRUD 표준 패턴 — `workspace.tools` 권한
- `/id/valves`: GET/POST 도구 설정값
- `/id/valves/spec`: GET 설정 스펙 (Pydantic 스키마)
- 코드 에디터: Python 코드로 도구 정의

## Functions 라우터 (routers/functions.py)
- CRUD 표준 패턴
- `/id/toggle`: POST 활성/비활성
- 파이프라인: filter, pipe, action 타입
- 코드 에디터: Python 코드로 함수 정의

## Tool Connections (routers/tool_connections.py)
- MCP (Model Context Protocol) 서버 연결
- OpenAPI 스키마 기반 도구 자동 등록
- 외부 서버와 도구 동기화

## 플러그인 시스템 (utils/plugin.py)
- 동적 Python 모듈 로딩
- Valves: Pydantic 기반 설정 모델
- 도구/함수 실행 환경 격리

## 프론트엔드
- 코드 에디터: Monaco/CodeMirror 기반
- 도구 목록, 설정 패널

## 참조 파일
- `routers/tools.py`: 도구 CRUD + Valves
- `routers/functions.py`: 함수 CRUD + 파이프라인
- `routers/tool_connections.py`: MCP/OpenAPI 연결
- `utils/plugin.py`: 동적 모듈 로딩
