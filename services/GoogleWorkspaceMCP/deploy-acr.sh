#!/usr/bin/env bash
# Google Workspace MCP 이미지를 Azure Container Registry 에 빌드 + 푸시한다.
# `az acr build` 를 사용 → 빌드를 ACR 가 클라우드에서 수행하므로 로컬 docker 가 불필요하고
# 항상 linux/amd64 로 빌드된다(로컬 아키텍처 무관). 버전 태그 + latest 두 개를 함께 푸시.
#
# 사용 예:
#   ./deploy-acr.sh                 # 기본값 (acrcloosphere / gws-mcp / .env 의 버전)
#   ./deploy-acr.sh 1.22.0          # 버전 지정 (이미지 태그 + Dockerfile build-arg 동시 적용)
#   REGISTRY=otheracr ./deploy-acr.sh
#   VERSION=1.22.0 ./deploy-acr.sh
#
# 사전 조건: `az login` 완료 + 대상 ACR push 권한.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REGISTRY="${REGISTRY:-acrcloosphere}"   # ACR 이름 (login server 의 앞부분)
IMAGE="${IMAGE:-gws-mcp}"               # 리포지토리 이름
DEFAULT_VERSION="1.21.0"

# 버전 우선순위: 1번째 인자 > $VERSION > .env 의 WORKSPACE_MCP_VERSION > 기본값
ENV_VERSION=""
if [ -f .env ]; then
  ENV_VERSION="$(grep -E '^WORKSPACE_MCP_VERSION=' .env | cut -d= -f2- | tr -d '[:space:]' || true)"
fi
VERSION="${1:-${VERSION:-${ENV_VERSION:-$DEFAULT_VERSION}}}"

echo "▶ ACR 빌드 + 푸시 (Google Workspace MCP)"
echo "   레지스트리 : ${REGISTRY}.azurecr.io"
echo "   이미지     : ${IMAGE}:${VERSION}  (+ :latest)"
echo "   컨텍스트   : ${SCRIPT_DIR}"
echo

if ! az account show >/dev/null 2>&1; then
  echo "✗ Azure 로그인이 필요합니다 → az login" >&2
  exit 1
fi

az acr build \
  --registry "${REGISTRY}" \
  --image "${IMAGE}:${VERSION}" \
  --image "${IMAGE}:latest" \
  --build-arg "WORKSPACE_MCP_VERSION=${VERSION}" \
  --file Dockerfile \
  .

echo
echo "✓ 푸시 완료: ${REGISTRY}.azurecr.io/${IMAGE}:{${VERSION},latest}"
echo "  태그 확인: az acr repository show-tags --name ${REGISTRY} --repository ${IMAGE} -o table"
