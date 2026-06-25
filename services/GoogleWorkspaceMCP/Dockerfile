# Google Workspace MCP (taylorwilsdon/google_workspace_mcp) — external OAuth 2.1 passthrough.
# Cloosphere 와 "완전 별개"로 배포되는 독립 컨테이너. Cloosphere 는 이 컨테이너의 /mcp/
# 엔드포인트에 기존 Tool Connections(Auth Type=OAuth 2.0 / Provider=Google)로만 연결한다.
#   → Cloosphere 백엔드 코드 변경 0.
FROM python:3.12-slim

# 재현성: PyPI 패키지 버전 고정. 업그레이드 시 이 ARG(또는 .env 의 WORKSPACE_MCP_VERSION)만
# 올리고 재빌드. external OAuth 2.1 provider 모드는 OAuth 2.1(2025-06-18 spec) 도입 이후 버전 필요.
ARG WORKSPACE_MCP_VERSION=1.21.0

RUN pip install --no-cache-dir "workspace-mcp==${WORKSPACE_MCP_VERSION}"

# 비루트 실행
RUN useradd -m -u 10001 gwsmcp
USER gwsmcp

EXPOSE 8000

# streamable HTTP 전송 + 전체 GWS 서비스 노출 (Cloosphere GMAIL_DELEGATED_SCOPES 와 정합).
# 도구 추가/제거 시: 아래 --tools 목록과 Cloosphere 로그인 스코프(config.py GMAIL_DELEGATED_SCOPES),
# marketplace_tool_meta.py 의 google-workspace 카테고리 맵을 함께 갱신할 것.
# OAuth 2.1 / external provider 토글은 환경변수(docker-compose)로 주입.
CMD ["workspace-mcp", "--transport", "streamable-http", "--tools", \
     "gmail", "calendar", "drive", "docs", "sheets", \
     "slides", "forms", "tasks", "contacts", "chat"]
