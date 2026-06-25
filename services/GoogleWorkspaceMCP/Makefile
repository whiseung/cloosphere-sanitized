# Google Workspace MCP 독립 서비스 편의 명령어
# 사용 전: cp .env.example .env && (GOOGLE_OAUTH_CLIENT_ID 등 채우기)

COMPOSE := docker compose

.PHONY: help up down restart logs ps build acr health mcp-url

help:                ## 명령어 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:                  ## 빌드 + 백그라운드 기동
	$(COMPOSE) up -d --build

down:                ## 중지 + 컨테이너 제거
	$(COMPOSE) down

restart:             ## 재기동
	$(COMPOSE) restart

logs:                ## 로그 follow
	$(COMPOSE) logs -f --tail=200

ps:                  ## 상태 + healthcheck 확인
	$(COMPOSE) ps

build:               ## 이미지 재빌드 (WORKSPACE_MCP_VERSION 변경 시)
	$(COMPOSE) build

acr:                 ## ACR 에 이미지 빌드+푸시 (az acr build). 예: make acr VERSION=1.22.0
	@./deploy-acr.sh $(VERSION)

health:              ## 포트 응답 점검 (auth-gated 라 401/406 이어도 살아있는 것)
	@curl -s -o /dev/null -w "HTTP %{http_code} (401 이면 정상 기동, 000 이면 DOWN)\n" \
		"http://localhost:$${GWS_MCP_PORT:-8000}/mcp" || echo "DOWN: 기동 중이거나 실패 (make logs 로 확인)"

mcp-url:             ## Cloosphere Tool Connections 에 넣을 MCP URL 출력
	@echo "MCP(HTTP) URL: http://localhost:$${GWS_MCP_PORT:-8000}/mcp   (끝 슬래시 없이 — /mcp/ 는 307)"
	@echo "  Auth Type: OAuth 2.0 (User SSO) / Provider: Google"
	@echo "  (Cloosphere 가 docker 안이면 host.docker.internal 또는 호스트 IP 로 치환)"
