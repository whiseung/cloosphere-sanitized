#!/usr/bin/env bash
#
# Cloosphere ACR 이미지를 고객사 전용 레포지토리로 복사한다.
#
# 사용법:
#   ./promote-customer-image.sh <고객사> <버전>
#
# 예시:
#   ./promote-customer-image.sh samsung 1.2.0
#   → acrcloosphere.azurecr.io/cloosphere:1.2.0
#     → acrcloosphere.azurecr.io/cloosphere-samsung:1.2.0
#     → acrcloosphere.azurecr.io/cloosphere-samsung:stable
#
set -euo pipefail

###############################################################################
# 설정 (필요시 여기를 수정)
###############################################################################

ACR="acrcloosphere"          # ACR 이름
SOURCE_REPO="cloosphere"     # 원본 레포
TARGET_PREFIX="cloosphere-"  # 결과: cloosphere-<고객사>
TAG_STABLE=true              # stable 태그도 함께 갱신할지

###############################################################################

CUSTOMER="${1:-}"
VERSION="${2:-}"

if [[ -z "$CUSTOMER" || -z "$VERSION" ]]; then
    echo "사용법: $0 <고객사> <버전>"
    echo "  예시: $0 samsung 1.2.0"
    exit 1
fi

VERSION="${VERSION#v}"   # v1.2.0 → 1.2.0
TARGET_REPO="${TARGET_PREFIX}${CUSTOMER}"
SOURCE="${ACR}.azurecr.io/${SOURCE_REPO}:${VERSION}"

echo "Source : ${SOURCE}"
echo "Target : ${ACR}.azurecr.io/${TARGET_REPO}:${VERSION}"
[[ "$TAG_STABLE" == "true" ]] && echo "         ${ACR}.azurecr.io/${TARGET_REPO}:stable"
echo

IMPORT_ARGS=(
    --name "$ACR"
    --source "$SOURCE"
    --image "${TARGET_REPO}:${VERSION}"
    --force
)
[[ "$TAG_STABLE" == "true" ]] && IMPORT_ARGS+=(--image "${TARGET_REPO}:stable")

az acr import "${IMPORT_ARGS[@]}"

echo
echo "✓ 완료: ${TARGET_REPO}:${VERSION}"
