# Microsoft 365 MCP (softeria/ms-365-mcp-server) — external OAuth 2.1 passthrough.
# Cloosphere 와 "완전 별개"로 배포되는 독립 컨테이너. Cloosphere 는 이 컨테이너의 /mcp
# 엔드포인트에 기존 Tool Connections(Auth Type=OAuth 2.0 / Provider=Microsoft)로만 연결한다.
#   → Cloosphere 백엔드 코드 변경 0.  (Google 측 services/GoogleWorkspaceMCP 와 대칭)
FROM node:20-alpine

# 재현성: npm 패키지 버전 고정. 업그레이드 시 이 ARG(또는 .env 의 MS365_MCP_VERSION)만
# 올리고 재빌드. softeria 는 릴리스 주기가 빠르므로(npm 220+ 버전) 의도적으로 핀한다.
# 공식 OCI 이미지는 없어 npm 글로벌 설치로 자체 이미지를 만든다.
ARG MS365_MCP_VERSION=0.114.0

RUN npm install -g @softeria/ms-365-mcp-server@${MS365_MCP_VERSION} \
    && npm cache clean --force

# 비루트 실행
RUN adduser -D -u 10001 m365mcp
USER m365mcp

# streamable HTTP 전송 + /mcp 엔드포인트(끝 슬래시 없이). 컨테이너 내부 포트 8001
# (Cloosphere 마켓플레이스 Microsoft 365 기본 URL :8001/mcp 와 정합).
# 인바운드 Authorization: Bearer(사용자별 Graph 토큰)는 Cloosphere 가 매 호출 주입한다.
# org/work 계정 도구(Teams/SharePoint/공유메일함)는 docker-compose 의 MS365_MCP_ORG_MODE 로 토글.
# ⚠️ MS365_MCP_OAUTH_TOKEN(정적 단일토큰) / --obo / --trust-proxy-auth 는 절대 쓰지 말 것
#    (멀티유저 격리 또는 토큰 audience 가 깨진다 — README 참조).
EXPOSE 8001
ENTRYPOINT ["ms-365-mcp-server"]
CMD ["--http", "8001"]
