# Presenton 독립 서비스 편의 명령어
# 사용 전: cp .env.example .env && (LLM 키 등 채우기)

COMPOSE := docker compose

.PHONY: help up down restart logs ps pull health mcp-url

help:                ## 명령어 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:                  ## 백그라운드 기동 (최초엔 GB급 이미지 pull — 수 분 소요)
	$(COMPOSE) up -d

down:                ## 중지 + 컨테이너 제거 (app_data 볼륨은 보존)
	$(COMPOSE) down

restart:             ## 재기동
	$(COMPOSE) restart

logs:                ## 로그 follow
	$(COMPOSE) logs -f --tail=200

ps:                  ## 상태 + healthcheck 확인
	$(COMPOSE) ps

pull:                ## 최신 이미지 받기
	$(COMPOSE) pull

health:              ## API 살아있는지 점검
	@curl -fsS "$${NEXT_PUBLIC_URL:-http://localhost:5001}/" >/dev/null \
		&& echo "OK: Presenton 응답함" || echo "DOWN: 아직 기동 중이거나 실패 (make logs 로 확인)"

mcp-url:             ## Cloosphere Tool Connections 에 넣을 MCP URL 출력
	@echo "MCP(HTTP) URL: $${NEXT_PUBLIC_URL:-http://localhost:5001}/mcp"
	@echo "  (Cloosphere 가 docker 안이면 host.docker.internal 또는 호스트 IP 로 치환)"
