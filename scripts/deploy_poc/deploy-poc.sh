#!/usr/bin/env bash
#
# Cloosphere PoC 환경 배포 스크립트
# Azure CLI 기반 — 고객사별 PoC 인프라 원클릭 배포
#
# 사용법:
#   1. cp example.conf <고객사명>.conf  →  파라미터 수정
#   2. ./deploy-poc.sh <고객사명>.conf          # 배포
#   3. ./deploy-poc.sh <고객사명>.conf delete   # 삭제
#
# 배포 리소스:
#   VNet, Storage (Blob+FileShare), App Service (P1V4 Container + Volume Mount),
#   PostgreSQL Flexible (Burstable B2s), AI Search (S1), Redis (Basic C1),
#   Azure OpenAI, Document Intelligence
#
set -euo pipefail

###############################################################################
# 파라미터 파일 로드
###############################################################################

CONF_FILE="${1:-}"
CMD="${2:-deploy}"

if [[ -z "$CONF_FILE" ]]; then
    echo "사용법: $0 <고객사>.conf [deploy|delete]"
    echo "  예시: $0 wemade.conf"
    echo "        $0 wemade.conf delete"
    exit 1
fi

if [[ ! -f "$CONF_FILE" ]]; then
    echo "파일을 찾을 수 없습니다: $CONF_FILE"
    exit 1
fi

# shellcheck source=/dev/null
source "$CONF_FILE"

TOTAL_STEPS=10

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

###############################################################################
# 리소스 이름 생성
###############################################################################

C=$(echo "$CUSTOMER" | tr '[:upper:]' '[:lower:]')

if [[ ! "$C" =~ ^[a-z][a-z0-9-]{0,19}$ ]]; then
    error "고객사명: 영문 소문자로 시작, 소문자/숫자/하이픈만, 최대 20자"
    exit 1
fi

RG="${C}-poc-rg"
VNET="${C}-vnet"
ASP="${C}-asp"
APP="${C}-app"
SA=$(echo "${C}pocsa" | tr -d '-')        # Storage Account (영숫자만, 최대 24자)
SEARCH="${SEARCH_NAME:-${C}-search}"
PGSQL="${PGSQL_NAME:-${C}-pgsql}"
DOCITG="${DOCITG_NAME:-${C}-docitg}"
REDIS="${REDIS_NAME:-${C}-redis}"
OPENAI="${OPENAI_NAME:-${C}-openai}"
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

    # 필요한 리소스 프로바이더 등록
    local providers=(
        "Microsoft.Network"
        "Microsoft.Storage"
        "Microsoft.Web"
        "Microsoft.DBforPostgreSQL"
        "Microsoft.Search"
        "Microsoft.CognitiveServices"
        "Microsoft.Cache"
    )
    for ns in "${providers[@]}"; do
        local state
        state=$(az provider show --namespace "$ns" --query "registrationState" -o tsv 2>/dev/null || echo "NotRegistered")
        if [[ "$state" != "Registered" ]]; then
            log "리소스 프로바이더 등록: $ns"
            az provider register --namespace "$ns" --output none
        fi
    done

    # 등록 완료 대기 (비동기 등록이므로 확인)
    local pending=()
    for ns in "${providers[@]}"; do
        local state
        state=$(az provider show --namespace "$ns" --query "registrationState" -o tsv 2>/dev/null)
        if [[ "$state" != "Registered" ]]; then
            pending+=("$ns")
        fi
    done

    if [[ ${#pending[@]} -gt 0 ]]; then
        echo -ne "${YELLOW}[!]${NC} 프로바이더 등록 대기 중 (${#pending[@]}개, 1-3분 소요)..."
        local retry=0
        while [[ ${#pending[@]} -gt 0 && $retry -lt 60 ]]; do
            sleep 5
            local still_pending=()
            for ns in "${pending[@]}"; do
                local state
                state=$(az provider show --namespace "$ns" --query "registrationState" -o tsv 2>/dev/null)
                if [[ "$state" != "Registered" ]]; then
                    still_pending+=("$ns")
                fi
            done
            pending=("${still_pending[@]+"${still_pending[@]}"}")
            echo -n "."
            retry=$((retry + 1))
        done
        echo ""
        if [[ ${#pending[@]} -gt 0 ]]; then
            error "리소스 프로바이더 등록 타임아웃: ${pending[*]}"
            exit 1
        fi
    fi
    log "리소스 프로바이더 준비 완료"
}

###############################################################################
# 배포
###############################################################################

deploy() {
    check_az

    if [[ -z "$PG_PASSWORD" ]]; then
        PG_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)
        warn "PostgreSQL 비밀번호 자동 생성 (배포 완료 후 표시)"
    fi

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} Cloosphere PoC 배포: ${CYAN}${CUSTOMER}${NC}"
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

    # ── 2. VNet + Subnets ────────────────────────────────
    step 2 "VNet + 서브넷"
    if exists az network vnet show -g "$RG" -n "$VNET"; then
        log "이미 존재: $VNET"
        # VNet은 있지만 서브넷이 없는 경우 생성
        if ! exists az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "ap-subnet"; then
            az network vnet subnet create \
                -g "$RG" --vnet-name "$VNET" \
                -n "ap-subnet" \
                --address-prefix "$SUBNET_APP" \
                --delegations "Microsoft.Web/serverFarms" \
                --output none
            log "서브넷 생성: ap-subnet ($SUBNET_APP)"
        fi
    else
        az network vnet create \
            -g "$RG" -n "$VNET" \
            --location "$LOCATION" \
            --address-prefix "$VNET_CIDR" \
            --output none
        log "VNet: $VNET ($VNET_CIDR)"

        az network vnet subnet create \
            -g "$RG" --vnet-name "$VNET" \
            -n "ap-subnet" \
            --address-prefix "$SUBNET_APP" \
            --delegations "Microsoft.Web/serverFarms" \
            --output none
        log "서브넷: ap-subnet ($SUBNET_APP)"
    fi

    # ── 3. Storage Account ───────────────────────────────
    step 3 "Storage Account (Blob + File Share)"
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

    # ── 4. PostgreSQL Flexible Server ────────────────────
    step 4 "PostgreSQL Flexible Server (Burstable B2s, 퍼블릭)"

    if exists az postgres flexible-server show -g "$RG" -n "$PGSQL"; then
        log "이미 존재: $PGSQL"
    else
        log "PostgreSQL 생성 중 (5-10분 소요)..."
        az postgres flexible-server create \
            -g "$RG" -n "$PGSQL" \
            --location "$LOCATION" \
            --admin-user "$PG_ADMIN" \
            --admin-password "$PG_PASSWORD" \
            --sku-name "$PG_SKU" \
            --tier "$PG_TIER" \
            --storage-size "$PG_STORAGE" \
            --version "$PG_VERSION" \
            --public-access "0.0.0.0" \
            --yes \
            --output none
        log "생성: $PGSQL"

        # Azure 서비스 접근 허용 (App Service → PostgreSQL)
        az postgres flexible-server firewall-rule create \
            -g "$RG" -n "$PGSQL" \
            --rule-name "AllowAzureServices" \
            --start-ip-address "0.0.0.0" \
            --end-ip-address "0.0.0.0" \
            --output none 2>/dev/null || true

        # 현재 클라이언트 IP 허용 (외부 접근용)
        local my_ip
        my_ip=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "")
        if [[ -n "$my_ip" ]]; then
            az postgres flexible-server firewall-rule create \
                -g "$RG" -n "$PGSQL" \
                --rule-name "AllowClientIP" \
                --start-ip-address "$my_ip" \
                --end-ip-address "$my_ip" \
                --output none 2>/dev/null || true
            log "방화벽: Azure 서비스 + 클라이언트 IP ($my_ip) 허용"
        else
            log "방화벽: Azure 서비스 허용 (클라이언트 IP 감지 실패, 수동 추가 필요)"
        fi
    fi

    # db_cloosphere 데이터베이스 생성
    if ! az postgres flexible-server db show \
        -g "$RG" -s "$PGSQL" -d "db_cloosphere" &>/dev/null; then
        az postgres flexible-server db create \
            -g "$RG" -s "$PGSQL" -d "db_cloosphere" \
            --output none
        log "데이터베이스 생성: db_cloosphere"
    else
        log "데이터베이스 이미 존재: db_cloosphere"
    fi

    # ── 5. Azure AI Search ───────────────────────────────
    step 5 "Azure AI Search (S1)"
    if exists az search service show -g "$RG" -n "$SEARCH"; then
        log "이미 존재: $SEARCH"
    else
        az search service create \
            -g "$RG" -n "$SEARCH" \
            --location "$LOCATION" \
            --sku "$SEARCH_SKU" \
            --partition-count 1 \
            --replica-count 1 \
            --output none
        log "생성: $SEARCH"
    fi

    # ── 6. Document Intelligence ─────────────────────────
    step 6 "Document Intelligence"
    if exists az cognitiveservices account show -g "$RG" -n "$DOCITG"; then
        log "이미 존재: $DOCITG"
    else
        az cognitiveservices account create \
            -g "$RG" -n "$DOCITG" \
            --location "$LOCATION" \
            --kind FormRecognizer \
            --sku S0 \
            --custom-domain "$DOCITG" \
            --output none
        log "생성: $DOCITG"
    fi

    # ── 7. Redis Cache ───────────────────────────────────
    step 7 "Azure Redis Cache (Basic C1)"
    if exists az redis show -g "$RG" -n "$REDIS"; then
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

    # ── 8. Azure OpenAI ──────────────────────────────────
    step 8 "Azure OpenAI"
    if exists az cognitiveservices account show -g "$RG" -n "$OPENAI"; then
        log "이미 존재: $OPENAI"
    else
        az cognitiveservices account create \
            -g "$RG" -n "$OPENAI" \
            --location "$LOCATION" \
            --kind OpenAI \
            --sku S0 \
            --custom-domain "$OPENAI" \
            --output none
        log "생성: $OPENAI (모델은 별도 배포 필요)"
    fi

    # ── 9. App Service (P1V4 Container) ──────────────────
    step 9 "App Service (P1V4 Container)"

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

    # VNet Integration
    az webapp vnet-integration add \
        -g "$RG" -n "$APP" \
        --vnet "$VNET" --subnet "ap-subnet" \
        --output none 2>/dev/null || true
    log "VNet 통합: ap-subnet"

    # Route all outbound through VNet
    az webapp update \
        -g "$RG" -n "$APP" \
        --set vnetRouteAllEnabled=true \
        --output none 2>/dev/null || true

    # Always On
    az webapp config set \
        -g "$RG" -n "$APP" \
        --always-on true \
        --output none 2>/dev/null || true

    # ── 10. Storage Volume Mount ─────────────────────────
    step 10 "Storage Volume Mount"
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

    # ══════════════════════════════════════════════════════
    print_summary "$storage_key"
}

###############################################################################
# 결과 출력
###############################################################################

print_summary() {
    local storage_key="$1"

    local search_key redis_key redis_host openai_key openai_ep docitg_key docitg_ep pg_fqdn

    pg_fqdn=$(az postgres flexible-server show -g "$RG" -n "$PGSQL" --query "fullyQualifiedDomainName" -o tsv 2>/dev/null || echo "${PGSQL}.postgres.database.azure.com")
    search_key=$(az search admin-key show -g "$RG" --service-name "$SEARCH" --query "primaryKey" -o tsv 2>/dev/null || echo "(조회 실패)")
    redis_host=$(az redis show -g "$RG" -n "$REDIS" --query "hostName" -o tsv 2>/dev/null || echo "(프로비저닝 중)")
    redis_key=$(az redis list-keys -g "$RG" -n "$REDIS" --query "primaryKey" -o tsv 2>/dev/null || echo "(프로비저닝 중)")
    openai_ep=$(az cognitiveservices account show -g "$RG" -n "$OPENAI" --query "properties.endpoint" -o tsv 2>/dev/null || echo "(조회 실패)")
    openai_key=$(az cognitiveservices account keys list -g "$RG" -n "$OPENAI" --query "key1" -o tsv 2>/dev/null || echo "(조회 실패)")
    docitg_ep=$(az cognitiveservices account show -g "$RG" -n "$DOCITG" --query "properties.endpoint" -o tsv 2>/dev/null || echo "(조회 실패)")
    docitg_key=$(az cognitiveservices account keys list -g "$RG" -n "$DOCITG" --query "key1" -o tsv 2>/dev/null || echo "(조회 실패)")

    echo ""
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} PoC 배포 완료: ${CYAN}${CUSTOMER}${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  리소스 그룹:  $RG"
    echo "  리전:         $LOCATION"
    echo ""
    echo -e "${BOLD}── App Service ──${NC}"
    echo "  URL:          https://${APP}.azurewebsites.net"
    echo "  Volume:       /app/backend/data → ${SA}/${FILE_SHARE}"
    echo ""
    echo -e "${BOLD}── PostgreSQL ──${NC}"
    echo "  Host:         $pg_fqdn"
    echo "  Admin:        $PG_ADMIN"
    echo "  Password:     $PG_PASSWORD"
    echo "  DATABASE_URL: postgresql://${PG_ADMIN}:${PG_PASSWORD}@${pg_fqdn}:5432/db_cloosphere?sslmode=require"
    echo ""
    echo -e "${BOLD}── Redis ──${NC}"
    echo "  Host:         $redis_host"
    echo "  Port:         6380 (SSL)"
    echo "  Key:          $redis_key"
    echo "  REDIS_URL:    rediss://:${redis_key}@${redis_host}:6380/0"
    echo ""
    echo -e "${BOLD}── Azure AI Search ──${NC}"
    echo "  Endpoint:     https://${SEARCH}.search.windows.net"
    echo "  Admin Key:    $search_key"
    echo ""
    echo -e "${BOLD}── Azure OpenAI ──${NC}"
    echo "  Endpoint:     $openai_ep"
    echo "  Key:          $openai_key"
    echo ""
    echo -e "${BOLD}── Document Intelligence ──${NC}"
    echo "  Endpoint:     $docitg_ep"
    echo "  Key:          $docitg_key"
    echo ""
    echo -e "${BOLD}── Storage Account ──${NC}"
    echo "  Name:         $SA"
    echo "  Blob:         $BLOB_CONTAINER"
    echo "  File Share:   $FILE_SHARE"
    echo "  Key:          $storage_key"
    echo ""
    echo -e "${BOLD}── 다음 단계 ──${NC}"
    echo ""
    echo "  1. Azure OpenAI 모델 배포 (포탈 또는 CLI)"
    echo ""
    echo "  2. App Service 환경변수 설정:"
    echo "     az webapp config appsettings set -g $RG -n $APP --settings \\"
    echo "       DATABASE_URL='postgresql://...' \\"
    echo "       REDIS_URL='rediss://...' \\"
    echo "       WEBUI_SECRET_KEY='$(openssl rand -hex 32)'"
    echo ""
    echo "  3. 환경 삭제:"
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
    warn "PoC 환경 삭제: $CUSTOMER"
    warn "리소스 그룹 '$RG' 내 모든 리소스가 삭제됩니다."
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
        echo "사용법: $0 <고객사>.conf [deploy|delete]"
        exit 1
        ;;
esac
