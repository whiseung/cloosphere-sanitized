#!/usr/bin/env bash
#
# Cloosphere Demo 환경 배포 스크립트
# Azure CLI 기반 — 기존 공유 리소스(DB, OpenAI 등)에 연결하는 경량 배포
#
# 사용법:
#   1. cp example.conf <환경명>.conf  →  파라미터 수정
#   2. ./deploy-demo.sh <환경명>.conf          # 배포
#   3. ./deploy-demo.sh <환경명>.conf delete   # 삭제
#
# 배포 리소스 (신규 생성):
#   Storage (Blob+FileShare), Redis (Basic C1),
#   App Service (P1V4 Container + Volume Mount)
#
# 기존 리소스 (conf에서 연결 정보 입력):
#   PostgreSQL, Azure OpenAI, AI Search, Document Intelligence
#
set -euo pipefail

###############################################################################
# 파라미터 파일 로드
###############################################################################

CONF_FILE="${1:-}"
CMD="${2:-deploy}"

if [[ -z "$CONF_FILE" ]]; then
    echo "사용법: $0 <환경명>.conf [deploy|delete]"
    echo "  예시: $0 cloocus.conf"
    echo "        $0 cloocus.conf delete"
    exit 1
fi

if [[ ! -f "$CONF_FILE" ]]; then
    echo "파일을 찾을 수 없습니다: $CONF_FILE"
    exit 1
fi

# shellcheck source=/dev/null
source "$CONF_FILE"

TOTAL_STEPS=6

###############################################################################
# 헬퍼
###############################################################################

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }
step()  { echo -e "\n${CYAN}${BOLD}[$1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"; }

exists() { "$@" &>/dev/null 2>&1; }

# APP_ENV_VARS에서 특정 키의 값을 가져오기
get_env_var() {
    local key="$1"
    for entry in "${APP_ENV_VARS[@]+"${APP_ENV_VARS[@]}"}"; do
        if [[ "${entry%%=*}" == "$key" ]]; then
            echo "${entry#*=}"
            return
        fi
    done
}

# APP_ENV_VARS에 특정 키가 값 포함으로 존재하는지
has_env_var() {
    local val
    val=$(get_env_var "$1")
    [[ -n "$val" ]]
}

###############################################################################
# 리소스 이름 생성
###############################################################################

C=$(echo "$ENV_NAME" | tr '[:upper:]' '[:lower:]')

if [[ ! "$C" =~ ^[a-z][a-z0-9-]{0,19}$ ]]; then
    error "환경명: 영문 소문자로 시작, 소문자/숫자/하이픈만, 최대 20자"
    exit 1
fi

RG="${C}-demo-rg"
ASP="${C}-asp"
APP="${APP_NAME}"
SA=$(echo "${SA_NAME:-${C}demosa}" | tr -d '-')   # Storage Account (영숫자만, 최대 24자)
REDIS="${REDIS_NAME:-${C}-redis}"

if [[ -z "$APP_NAME" ]]; then
    error "APP_NAME이 설정되지 않았습니다. conf에서 App Service 이름을 지정하세요."
    exit 1
fi

if [[ ${#SA} -gt 24 ]]; then
    SA="${SA:0:24}"
    warn "Storage Account 이름이 24자 초과하여 잘림: $SA"
fi

###############################################################################
# Azure CLI 확인 및 로그인
###############################################################################

check_az() {
    if ! command -v az &>/dev/null; then
        error "Azure CLI가 설치되어 있지 않습니다."
        error "설치: https://learn.microsoft.com/cli/azure/install-azure-cli"
        exit 1
    fi

    if [[ -n "$TENANT_ID" ]]; then
        local current_tenant
        current_tenant=$(az account show --query "tenantId" -o tsv 2>/dev/null || echo "")
        if [[ "$current_tenant" != "$TENANT_ID" ]]; then
            log "테넌트 로그인: $TENANT_ID"
            az login --tenant "$TENANT_ID" --output none
        fi
    elif ! az account show &>/dev/null 2>&1; then
        error "Azure에 로그인되어 있지 않습니다."
        error "TENANT_ID를 설정하거나 'az login'을 실행하세요."
        exit 1
    fi

    if [[ -n "$SUBSCRIPTION_ID" ]]; then
        az account set --subscription "$SUBSCRIPTION_ID" --output none
    fi

    log "구독: $(az account show --query 'name' -o tsv) ($(az account show --query 'id' -o tsv))"

    local providers=("Microsoft.Storage" "Microsoft.Web" "Microsoft.Cache")
    for ns in "${providers[@]}"; do
        local state
        state=$(az provider show --namespace "$ns" --query "registrationState" -o tsv 2>/dev/null || echo "NotRegistered")
        if [[ "$state" != "Registered" ]]; then
            log "리소스 프로바이더 등록: $ns"
            az provider register --namespace "$ns" --output none
        fi
    done
    log "리소스 프로바이더 준비 완료"
}

###############################################################################
# 배포
###############################################################################

deploy() {
    check_az

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} Cloosphere Demo 배포: ${CYAN}${ENV_NAME}${NC}"
    echo -e "${BOLD} 리전: ${LOCATION}${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"

    # ── 1. Resource Group ────────────────────────────────
    step 1 "리소스 그룹"
    if exists az group show --name "$RG"; then
        log "이미 존재: $RG"
    else
        az group create --name "$RG" --location "$LOCATION" --output none
        log "생성: $RG"
    fi

    # ── 2. Storage Account ───────────────────────────────
    step 2 "Storage Account (Blob + File Share)"
    if exists az storage account show -g "$RG" -n "$SA"; then
        log "이미 존재: $SA"
    else
        az storage account create \
            -g "$RG" -n "$SA" \
            --location "$LOCATION" \
            --sku Standard_LRS \
            --kind StorageV2 \
            --min-tls-version TLS1_2 \
            --output none
        log "생성: $SA"
    fi

    local storage_key
    storage_key=$(az storage account keys list \
        -g "$RG" --account-name "$SA" \
        --query "[0].value" -o tsv)

    if exists az storage container show -n "$BLOB_CONTAINER" --account-name "$SA" --account-key "$storage_key"; then
        log "Blob 컨테이너 이미 존재: $BLOB_CONTAINER"
    else
        az storage container create \
            -n "$BLOB_CONTAINER" \
            --account-name "$SA" --account-key "$storage_key" \
            --output none
        log "Blob 컨테이너: $BLOB_CONTAINER"
    fi

    if exists az storage share show -n "$FILE_SHARE" --account-name "$SA" --account-key "$storage_key"; then
        log "File Share 이미 존재: $FILE_SHARE"
    else
        az storage share create \
            -n "$FILE_SHARE" \
            --account-name "$SA" --account-key "$storage_key" \
            --quota 100 \
            --output none
        log "File Share: $FILE_SHARE (100 GiB)"
    fi

    # ── 3. Redis Cache ───────────────────────────────────
    step 3 "Azure Redis Cache"
    if has_env_var "REDIS_URL"; then
        log "기존 Redis 사용 (APP_ENV_VARS에서 REDIS_URL 제공됨)"
    elif exists az redis show -g "$RG" -n "$REDIS"; then
        log "이미 존재: $REDIS"
    else
        log "Redis 생성 중 (15-20분 소요)..."
        az redis create \
            -g "$RG" -n "$REDIS" \
            --location "$LOCATION" \
            --sku "$REDIS_SKU" \
            --vm-size "$REDIS_SIZE" \
            --output none
        log "생성: $REDIS"
    fi

    # ── 4. App Service (Container) ───────────────────────
    step 4 "App Service (${APP_SKU} Container)"

    if exists az appservice plan show -g "$RG" -n "$ASP"; then
        log "Plan 이미 존재: $ASP"
    else
        az appservice plan create \
            -g "$RG" -n "$ASP" \
            --location "$LOCATION" \
            --sku "$APP_SKU" \
            --is-linux \
            --output none
        log "Plan: $ASP ($APP_SKU)"
    fi

    if exists az webapp show -g "$RG" -n "$APP"; then
        log "App 이미 존재: $APP"
    else
        local container_image="mcr.microsoft.com/appsvc/staticsite:latest"
        if [[ -n "$ACR_IMAGE" ]]; then
            container_image="$ACR_IMAGE"
        fi
        az webapp create \
            -g "$RG" -n "$APP" \
            --plan "$ASP" \
            --container-image-name "$container_image" \
            --https-only true \
            --output none
        log "App: $APP"
    fi

    # ACR 컨테이너 설정 (토큰 인증)
    if [[ -n "$ACR_URL" && -n "$ACR_TOKEN_NAME" && -n "$ACR_TOKEN_PASSWORD" && -n "$ACR_IMAGE" ]]; then
        az webapp config container set \
            -g "$RG" -n "$APP" \
            --container-image-name "$ACR_IMAGE" \
            --container-registry-url "$ACR_URL" \
            --container-registry-user "$ACR_TOKEN_NAME" \
            --container-registry-password "$ACR_TOKEN_PASSWORD" \
            --output none
        log "컨테이너: $ACR_IMAGE (ACR 토큰 인증)"
    elif [[ -n "$ACR_IMAGE" ]]; then
        warn "ACR_URL, ACR_TOKEN_NAME, ACR_TOKEN_PASSWORD를 모두 설정하세요"
    fi

    # Always On
    az webapp config set \
        -g "$RG" -n "$APP" \
        --always-on true \
        --output none 2>/dev/null || true

    # ── 5. Storage Volume Mount ──────────────────────────
    step 5 "Storage Volume Mount"
    az webapp config storage-account add \
        -g "$RG" -n "$APP" \
        --custom-id "appdata" \
        --storage-type AzureFiles \
        --share-name "$FILE_SHARE" \
        --account-name "$SA" \
        --access-key "$storage_key" \
        --mount-path "/app/backend/data" \
        --output none 2>/dev/null || true
    log "Mount: $SA/$FILE_SHARE → /app/backend/data"

    # ── 6. App Service 환경변수 등록 ─────────────────────
    step 6 "App Service 환경변수"

    local settings=()

    # 자동 생성 값
    # 데모 환경 고정 키 (동일 키 → 동일 Fernet 암호화 → config 공유 가능)
    settings+=("WEBUI_SECRET_KEY=1628d42ddaff4e962a0140bac9a6256c1b19d0d0c970261f4f461239d02e4fc1")

    # Redis: APP_ENV_VARS에 REDIS_URL이 없으면 신규 Redis에서 자동 생성
    if ! has_env_var "REDIS_URL"; then
        local redis_host redis_key
        redis_host=$(az redis show -g "$RG" -n "$REDIS" --query "hostName" -o tsv 2>/dev/null || echo "")
        redis_key=$(az redis list-keys -g "$RG" -n "$REDIS" --query "primaryKey" -o tsv 2>/dev/null || echo "")
        if [[ -n "$redis_host" && -n "$redis_key" ]]; then
            settings+=("REDIS_URL=rediss://:${redis_key}@${redis_host}:6380/0")
        fi
    fi

    # conf의 APP_ENV_VARS에서 값이 있는 항목만 등록
    for entry in "${APP_ENV_VARS[@]+"${APP_ENV_VARS[@]}"}"; do
        local val="${entry#*=}"
        [[ -n "$val" ]] && settings+=("$entry")
    done

    if [[ ${#settings[@]} -gt 0 ]]; then
        az webapp config appsettings set \
            -g "$RG" -n "$APP" \
            --settings "${settings[@]}" \
            --output none
        log "환경변수 ${#settings[@]}개 등록 완료"
    fi

    # ══════════════════════════════════════════════════════
    print_summary "$storage_key"
}

###############################################################################
# 결과 출력
###############################################################################

print_summary() {
    local storage_key="$1"

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} Demo 배포 완료: ${CYAN}${ENV_NAME}${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  리소스 그룹:  $RG"
    echo "  리전:         $LOCATION"
    echo ""
    echo -e "${BOLD}── App Service ──${NC}"
    echo "  URL:          https://${APP}.azurewebsites.net"
    echo "  Volume:       /app/backend/data → ${SA}/${FILE_SHARE}"
    echo ""
    echo -e "${BOLD}── Storage Account (신규) ──${NC}"
    echo "  Name:         $SA"
    echo "  Blob:         $BLOB_CONTAINER"
    echo "  File Share:   $FILE_SHARE"
    echo "  Key:          $storage_key"
    echo ""

    if ! has_env_var "REDIS_URL"; then
        local redis_host redis_key
        redis_host=$(az redis show -g "$RG" -n "$REDIS" --query "hostName" -o tsv 2>/dev/null || echo "(프로비저닝 중)")
        redis_key=$(az redis list-keys -g "$RG" -n "$REDIS" --query "primaryKey" -o tsv 2>/dev/null || echo "(프로비저닝 중)")
        echo -e "${BOLD}── Redis (신규) ──${NC}"
        echo "  Host:         $redis_host"
        echo "  Port:         6380 (SSL)"
        echo "  REDIS_URL:    rediss://:${redis_key}@${redis_host}:6380/0"
        echo ""
    fi

    echo -e "${BOLD}── 등록된 환경변수 ──${NC}"
    echo "  WEBUI_SECRET_KEY:  (자동 생성됨)"
    for entry in "${APP_ENV_VARS[@]+"${APP_ENV_VARS[@]}"}"; do
        local key="${entry%%=*}" val="${entry#*=}"
        if [[ -n "$val" ]]; then
            # 키/비밀번호는 마스킹
            if [[ "$key" == *KEY* || "$key" == *PASSWORD* || "$key" == *SECRET* ]]; then
                echo "  ${key}:  ${val:0:8}..."
            else
                echo "  ${key}:  ${val}"
            fi
        fi
    done
    echo ""
    echo -e "${BOLD}── 다음 단계 ──${NC}"
    echo ""
    echo "  1. 나머지 설정은 웹 관리자 화면에서 조정"
    echo ""
    echo "  2. 환경 삭제:"
    echo "     $0 $CONF_FILE delete"
    echo ""
}

###############################################################################
# 삭제
###############################################################################

delete() {
    check_az

    if ! exists az group show --name "$RG"; then
        error "리소스 그룹 '$RG'를 찾을 수 없습니다."
        exit 1
    fi

    echo ""
    warn "Demo 환경 삭제: $ENV_NAME"
    warn "리소스 그룹 '$RG' 내 모든 리소스가 삭제됩니다."
    warn "기존 공유 리소스(DB, OpenAI 등)는 영향받지 않습니다."
    echo ""

    az resource list -g "$RG" --query "[].{Name:name, Type:type}" -o table 2>/dev/null || true
    echo ""

    read -rp "삭제하시겠습니까? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "취소됨."
        exit 0
    fi

    log "리소스 그룹 삭제 중: $RG"
    az group delete --name "$RG" --yes --no-wait
    log "삭제 요청 완료 (백그라운드 진행, 수 분 소요)"
}

###############################################################################
# 메인
###############################################################################

case "$CMD" in
    deploy)  deploy ;;
    delete)  delete ;;
    *)
        error "알 수 없는 명령: $CMD"
        echo "사용법: $0 <환경명>.conf [deploy|delete]"
        exit 1
        ;;
esac
