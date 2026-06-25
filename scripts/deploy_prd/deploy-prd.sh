#!/usr/bin/env bash
#
# Cloosphere Production 환경 배포 스크립트
# Azure CLI 기반 — 전체 리소스 Private Endpoint + 사설 통신
#
# 사용법:
#   1. cp example.conf <고객사명>.conf  →  파라미터 수정
#   2. ./deploy-prd.sh <고객사명>.conf          # 배포
#   3. ./deploy-prd.sh <고객사명>.conf delete   # 삭제
#
# 배포 리소스 (모든 리소스 사설 통신):
#   VNet (3 서브넷), Private DNS Zones (7개),
#   Storage (Blob+FileShare+PE), App Service (P1V4 Container + VNet),
#   PostgreSQL Flexible (GeneralPurpose, 위임 서브넷),
#   AI Search (S1+PE), Redis (Basic+PE),
#   Azure OpenAI (+PE), Document Intelligence (+PE),
#   [선택] Front Door + WAF (Standard/Premium)
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

# Front Door 옵션 기본값 (기존 conf 호환)
AFD_ENABLED="${AFD_ENABLED:-}"
AFD_SKU="${AFD_SKU:-Standard_AzureFrontDoor}"
AFD_WAF_MODE="${AFD_WAF_MODE:-Prevention}"

if [[ "$AFD_ENABLED" == "true" ]]; then
    TOTAL_STEPS=11
else
    TOTAL_STEPS=10
fi

###############################################################################
# 헬퍼
###############################################################################

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }
step()  { echo -e "\n${CYAN}${BOLD}[$1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"; }

exists() { "$@" &>/dev/null; }

###############################################################################
# Private Endpoint 생성 헬퍼
###############################################################################

create_private_endpoint() {
    local pe_name="$1"          # PE 리소스 이름
    local resource_id="$2"      # 대상 리소스 ID
    local group_id="$3"         # 서브리소스 (blob, file, searchService, redisCache, account 등)
    local dns_zone_name="$4"    # Private DNS Zone 이름

    if exists az network private-endpoint show -g "$RG" -n "$pe_name"; then
        log "PE 이미 존재: $pe_name"
        return 0
    fi

    az network private-endpoint create \
        -g "$RG" -n "$pe_name" \
        --location "$LOCATION" \
        --vnet-name "$VNET" --subnet "pe-subnet" \
        --private-connection-resource-id "$resource_id" \
        --group-id "$group_id" \
        --connection-name "${pe_name}-conn" \
        --output none
    log "PE 생성: $pe_name → $group_id"

    # DNS Zone Group (PE ↔ Private DNS Zone 연결)
    local dns_zone_id="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG}/providers/Microsoft.Network/privateDnsZones/${dns_zone_name}"
    az network private-endpoint dns-zone-group create \
        -g "$RG" --endpoint-name "$pe_name" \
        -n "default" \
        --private-dns-zone "$dns_zone_id" \
        --zone-name "${dns_zone_name//./-}" \
        --output none
    log "DNS Zone Group: $pe_name → $dns_zone_name"
}

###############################################################################
# 리소스 이름 생성
###############################################################################

C=$(echo "$CUSTOMER" | tr '[:upper:]' '[:lower:]')

if [[ ! "$C" =~ ^[a-z][a-z0-9-]{0,19}$ ]]; then
    error "고객사명: 영문 소문자로 시작, 소문자/숫자/하이픈만, 최대 20자"
    exit 1
fi

if [[ -z "$SUBSCRIPTION_ID" ]]; then
    error "SUBSCRIPTION_ID가 설정되지 않았습니다. (Private DNS Zone ID 생성에 필수)"
    exit 1
fi

RG="${C}-prd-rg"
VNET="${C}-vnet"
ASP="${C}-asp"
APP="${C}-app"
SA=$(echo "${C}prdsa" | tr -d '-')        # Storage Account (영숫자만, 최대 24자)
SEARCH="${C}-search"
PGSQL="${C}-pgsql"
DOCITG="${C}-docitg"
REDIS="${C}-redis"
OPENAI="${C}-openai"
AFD="${C}-afd"
AFD_EP="${C}-ep"
AFD_WAF="${C}-waf-policy"
if [[ ${#SA} -gt 24 ]]; then
    SA="${SA:0:24}"
    warn "Storage Account 이름이 24자 초과하여 잘림: $SA"
fi

###############################################################################
# Private DNS Zone 목록
###############################################################################

declare -A DNS_ZONES=(
    [blob]="privatelink.blob.core.windows.net"
    [file]="privatelink.file.core.windows.net"
    [postgres]="privatelink.postgres.database.azure.com"
    [search]="privatelink.search.windows.net"
    [redis]="privatelink.redis.cache.windows.net"
    [openai]="privatelink.openai.azure.com"
    [cognitiveservices]="privatelink.cognitiveservices.azure.com"
)

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
    if [[ "$AFD_ENABLED" == "true" ]]; then
        providers+=("Microsoft.Cdn")
    fi
    for ns in "${providers[@]}"; do
        local state
        state=$(az provider show --namespace "$ns" --query "registrationState" -o tsv 2>/dev/null || echo "NotRegistered")
        if [[ "$state" != "Registered" ]]; then
            log "리소스 프로바이더 등록: $ns"
            az provider register --namespace "$ns" --output none
        fi
    done

    # 등록 완료 대기
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
    echo -e "${BOLD} Cloosphere Production 배포: ${CYAN}${CUSTOMER}${NC}"
    echo -e "${BOLD} 리전: ${LOCATION} | 모든 리소스 사설 통신${NC}"
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
    step 2 "VNet + 서브넷 (3개)"
    if exists az network vnet show -g "$RG" -n "$VNET"; then
        log "이미 존재: $VNET"
    else
        az network vnet create \
            -g "$RG" -n "$VNET" \
            --location "$LOCATION" \
            --address-prefix "$VNET_CIDR" \
            --output none
        log "VNet: $VNET ($VNET_CIDR)"
    fi

    # ap-subnet (App Service VNet Integration)
    if ! exists az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "ap-subnet"; then
        az network vnet subnet create \
            -g "$RG" --vnet-name "$VNET" \
            -n "ap-subnet" \
            --address-prefix "$SUBNET_APP" \
            --delegations "Microsoft.Web/serverFarms" \
            --output none
        log "서브넷: ap-subnet ($SUBNET_APP) — App Service"
    else
        log "서브넷 이미 존재: ap-subnet"
    fi

    # pe-subnet (Private Endpoints)
    if ! exists az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "pe-subnet"; then
        az network vnet subnet create \
            -g "$RG" --vnet-name "$VNET" \
            -n "pe-subnet" \
            --address-prefix "$SUBNET_PE" \
            --output none
        log "서브넷: pe-subnet ($SUBNET_PE) — Private Endpoints"
    else
        log "서브넷 이미 존재: pe-subnet"
    fi

    # pg-subnet (PostgreSQL Flexible Server 위임)
    if ! exists az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "pg-subnet"; then
        az network vnet subnet create \
            -g "$RG" --vnet-name "$VNET" \
            -n "pg-subnet" \
            --address-prefix "$SUBNET_PG" \
            --delegations "Microsoft.DBforPostgreSQL/flexibleServers" \
            --output none
        log "서브넷: pg-subnet ($SUBNET_PG) — PostgreSQL"
    else
        log "서브넷 이미 존재: pg-subnet"
    fi

    # ── 3. Private DNS Zones ─────────────────────────────
    step 3 "Private DNS Zones (${#DNS_ZONES[@]}개)"
    for key in "${!DNS_ZONES[@]}"; do
        local zone="${DNS_ZONES[$key]}"
        if exists az network private-dns zone show -g "$RG" -n "$zone"; then
            log "DNS Zone 이미 존재: $zone"
        else
            az network private-dns zone create \
                -g "$RG" -n "$zone" \
                --output none
            log "DNS Zone 생성: $zone"
        fi

        # VNet 링크
        local link_name="${C}-${key}-link"
        if exists az network private-dns link vnet show -g "$RG" -z "$zone" -n "$link_name"; then
            log "VNet 링크 이미 존재: $link_name"
        else
            az network private-dns link vnet create \
                -g "$RG" -z "$zone" \
                -n "$link_name" \
                --virtual-network "$VNET" \
                --registration-enabled false \
                --output none
            log "VNet 링크: $link_name → $VNET"
        fi
    done

    # ── 4. Storage Account + Private Endpoints ───────────
    step 4 "Storage Account (Blob + File Share + PE)"
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

    # Private Endpoints (blob, file)
    local sa_id
    sa_id=$(az storage account show -g "$RG" -n "$SA" --query "id" -o tsv)
    create_private_endpoint "${C}-sa-blob-pe" "$sa_id" "blob" "${DNS_ZONES[blob]}"
    create_private_endpoint "${C}-sa-file-pe" "$sa_id" "file" "${DNS_ZONES[file]}"

    # 퍼블릭 접근 차단
    az storage account update \
        -g "$RG" -n "$SA" \
        --default-action Deny \
        --public-network-access Disabled \
        --output none 2>/dev/null || true
    log "Storage 퍼블릭 접근 차단 완료"

    # ── 5. PostgreSQL Flexible Server ────────────────────
    step 5 "PostgreSQL Flexible Server (위임 서브넷, 사설 접근)"
    if exists az postgres flexible-server show -g "$RG" -n "$PGSQL"; then
        log "이미 존재: $PGSQL"
    else
        log "PostgreSQL 생성 중 (5-10분 소요)..."
        local pg_subnet_id
        pg_subnet_id=$(az network vnet subnet show \
            -g "$RG" --vnet-name "$VNET" -n "pg-subnet" \
            --query "id" -o tsv)
        local pg_dns_zone_id
        pg_dns_zone_id=$(az network private-dns zone show \
            -g "$RG" -n "${DNS_ZONES[postgres]}" \
            --query "id" -o tsv)

        az postgres flexible-server create \
            -g "$RG" -n "$PGSQL" \
            --location "$LOCATION" \
            --admin-user "$PG_ADMIN" \
            --admin-password "$PG_PASSWORD" \
            --sku-name "$PG_SKU" \
            --tier "$PG_TIER" \
            --storage-size "$PG_STORAGE" \
            --version "$PG_VERSION" \
            --subnet "$pg_subnet_id" \
            --private-dns-zone "$pg_dns_zone_id" \
            --yes \
            --output none
        log "생성: $PGSQL (사설 접근, pg-subnet)"
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

    # ── 6. Azure AI Search + Private Endpoint ────────────
    step 6 "Azure AI Search (S1 + PE)"
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

    local search_id
    search_id=$(az search service show -g "$RG" -n "$SEARCH" --query "id" -o tsv)
    create_private_endpoint "${C}-search-pe" "$search_id" "searchService" "${DNS_ZONES[search]}"

    # 퍼블릭 접근 차단
    az search service update \
        -g "$RG" -n "$SEARCH" \
        --public-access Disabled \
        --output none 2>/dev/null || true
    log "Search 퍼블릭 접근 차단 완료"

    # ── 7. Document Intelligence + Private Endpoint ──────
    step 7 "Document Intelligence (PE)"
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

    local docitg_id
    docitg_id=$(az cognitiveservices account show -g "$RG" -n "$DOCITG" --query "id" -o tsv)
    create_private_endpoint "${C}-docitg-pe" "$docitg_id" "account" "${DNS_ZONES[cognitiveservices]}"

    # 퍼블릭 접근 차단
    az cognitiveservices account update \
        -g "$RG" -n "$DOCITG" \
        --public-network-access Disabled \
        --output none 2>/dev/null || true
    log "Document Intelligence 퍼블릭 접근 차단 완료"

    # ── 8. Redis Cache (PE) ────────────────────
    step 8 "Azure Redis Cache (PE)"
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

    local redis_id
    redis_id=$(az redis show -g "$RG" -n "$REDIS" --query "id" -o tsv)
    create_private_endpoint "${C}-redis-pe" "$redis_id" "redisCache" "${DNS_ZONES[redis]}"

    # Redis: 퍼블릭 접근 차단
    az redis update \
        -g "$RG" -n "$REDIS" \
        --set publicNetworkAccess=Disabled \
        --output none 2>/dev/null || true
    log "Redis 퍼블릭 접근 차단 완료"

    # ── 9. Azure OpenAI + Private Endpoint ───────────────
    step 9 "Azure OpenAI (PE)"
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

    local openai_id
    openai_id=$(az cognitiveservices account show -g "$RG" -n "$OPENAI" --query "id" -o tsv)
    create_private_endpoint "${C}-openai-pe" "$openai_id" "account" "${DNS_ZONES[openai]}"

    # 퍼블릭 접근 차단
    az cognitiveservices account update \
        -g "$RG" -n "$OPENAI" \
        --public-network-access Disabled \
        --output none 2>/dev/null || true
    log "OpenAI 퍼블릭 접근 차단 완료"

    # ── 10. App Service + VNet + Container + Volume Mount ─
    step 10 "App Service (P1V4 Container + VNet Integration)"

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

    # Route all outbound through VNet (사설 통신을 위해 필수)
    az webapp config set \
        -g "$RG" -n "$APP" \
        --vnet-route-all-enabled true \
        --output none 2>/dev/null || true
    log "모든 아웃바운드 트래픽 VNet 경유"

    # Private DNS: App Service → VNet DNS 사용
    az webapp config appsettings set \
        -g "$RG" -n "$APP" \
        --settings WEBSITE_DNS_SERVER="168.63.129.16" \
        --output none 2>/dev/null || true
    log "DNS: Azure Private DNS Resolver 설정"

    # Always On
    az webapp config set \
        -g "$RG" -n "$APP" \
        --always-on true \
        --output none 2>/dev/null || true

    # Storage Volume Mount (storage key를 사용하므로 PE 경유로도 동작)
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

    # ── 11. Front Door + WAF (선택) ───────────────────────
    if [[ "$AFD_ENABLED" == "true" ]]; then
        step 11 "Front Door + WAF ($AFD_SKU)"

        # WAF 정책
        if exists az network front-door waf-policy show -g "$RG" -n "$AFD_WAF"; then
            log "WAF 정책 이미 존재: $AFD_WAF"
        else
            az network front-door waf-policy create \
                -g "$RG" -n "$AFD_WAF" \
                --sku "$AFD_SKU" \
                --mode "$AFD_WAF_MODE" \
                --output none
            log "WAF 정책: $AFD_WAF (모드: $AFD_WAF_MODE)"
        fi

        # Premium: OWASP 관리형 규칙 + Bot Manager 추가
        if [[ "$AFD_SKU" == "Premium_AzureFrontDoor" ]]; then
            az network front-door waf-policy managed-rules add \
                -g "$RG" --policy-name "$AFD_WAF" \
                --type Microsoft_DefaultRuleSet \
                --version 2.1 \
                --output none 2>/dev/null || true
            log "OWASP 관리형 규칙 추가 (DRS 2.1)"

            az network front-door waf-policy managed-rules add \
                -g "$RG" --policy-name "$AFD_WAF" \
                --type Microsoft_BotManagerRuleSet \
                --version 1.1 \
                --output none 2>/dev/null || true
            log "Bot Manager 규칙 추가"
        fi

        # Front Door 프로필
        if exists az afd profile show -g "$RG" -n "$AFD"; then
            log "Front Door 이미 존재: $AFD"
        else
            az afd profile create \
                -g "$RG" -n "$AFD" \
                --sku "$AFD_SKU" \
                --output none
            log "Front Door: $AFD ($AFD_SKU)"
        fi

        # 엔드포인트
        if exists az afd endpoint show -g "$RG" --profile-name "$AFD" -n "$AFD_EP"; then
            log "엔드포인트 이미 존재: $AFD_EP"
        else
            az afd endpoint create \
                -g "$RG" --profile-name "$AFD" \
                -n "$AFD_EP" \
                --output none
            log "엔드포인트: $AFD_EP"
        fi

        # Origin Group
        if ! az afd origin-group show -g "$RG" --profile-name "$AFD" -n "default-origin-group" &>/dev/null; then
            az afd origin-group create \
                -g "$RG" --profile-name "$AFD" \
                -n "default-origin-group" \
                --probe-request-type GET \
                --probe-protocol Https \
                --probe-interval-in-seconds 30 \
                --probe-path "/" \
                --sample-size 4 \
                --successful-samples-required 3 \
                --output none
            log "Origin Group 생성"
        fi

        # Origin (App Service)
        if ! az afd origin show -g "$RG" --profile-name "$AFD" --origin-group-name "default-origin-group" -n "app-origin" &>/dev/null; then
            az afd origin create \
                -g "$RG" --profile-name "$AFD" \
                --origin-group-name "default-origin-group" \
                -n "app-origin" \
                --host-name "${APP}.azurewebsites.net" \
                --origin-host-header "${APP}.azurewebsites.net" \
                --http-port 80 \
                --https-port 443 \
                --priority 1 \
                --weight 1000 \
                --enabled-state Enabled \
                --output none
            log "Origin: ${APP}.azurewebsites.net"
        fi

        # Route
        if ! az afd route show -g "$RG" --profile-name "$AFD" --endpoint-name "$AFD_EP" -n "default-route" &>/dev/null; then
            az afd route create \
                -g "$RG" --profile-name "$AFD" \
                --endpoint-name "$AFD_EP" \
                -n "default-route" \
                --origin-group "default-origin-group" \
                --supported-protocols Https \
                --https-redirect Enabled \
                --forwarding-protocol HttpsOnly \
                --patterns-to-match "/*" \
                --link-to-default-domain Enabled \
                --output none
            log "Route: /* → App Service (HTTPS Only)"
        fi

        # WAF 정책 연결
        local afd_ep_id="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG}/providers/Microsoft.Cdn/profiles/${AFD}/afdEndpoints/${AFD_EP}"
        local waf_policy_id="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RG}/providers/Microsoft.Network/FrontDoorWebApplicationFirewallPolicies/${AFD_WAF}"
        if ! az afd security-policy show -g "$RG" --profile-name "$AFD" -n "waf-security-policy" &>/dev/null; then
            az afd security-policy create \
                -g "$RG" --profile-name "$AFD" \
                -n "waf-security-policy" \
                --domains "$afd_ep_id" \
                --waf-policy "$waf_policy_id" \
                --output none
            log "WAF 정책 연결 완료"
        fi

        # App Service 접근 제한 (Front Door만 허용)
        local afd_id
        afd_id=$(az afd profile show -g "$RG" -n "$AFD" --query "frontDoorId" -o tsv)
        az webapp config access-restriction add \
            -g "$RG" -n "$APP" \
            --priority 100 \
            --service-tag AzureFrontDoor.Backend \
            --http-header x-azure-fdid="$afd_id" \
            --action Allow \
            --output none 2>/dev/null || true
        log "App Service 접근 제한: Front Door만 허용 (FDID: $afd_id)"
    fi

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
    echo -e "${BOLD} Production 배포 완료: ${CYAN}${CUSTOMER}${NC}"
    echo -e "${BOLD} 모든 리소스 사설 통신 (Private Endpoint / 위임 서브넷)${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  리소스 그룹:  $RG"
    echo "  리전:         $LOCATION"
    echo ""
    echo -e "${BOLD}── 네트워크 ──${NC}"
    echo "  VNet:         $VNET ($VNET_CIDR)"
    echo "  ap-subnet:    $SUBNET_APP (App Service)"
    echo "  pe-subnet:    $SUBNET_PE (Private Endpoints)"
    echo "  pg-subnet:    $SUBNET_PG (PostgreSQL)"
    echo ""
    echo -e "${BOLD}── App Service ──${NC}"
    echo "  URL:          https://${APP}.azurewebsites.net"
    echo "  Volume:       /app/backend/data → ${SA}/${FILE_SHARE}"
    echo "  VNet:         ap-subnet (모든 아웃바운드 VNet 경유)"
    echo ""
    echo -e "${BOLD}── PostgreSQL (사설 접근) ──${NC}"
    echo "  Host:         $pg_fqdn"
    echo "  Admin:        $PG_ADMIN"
    echo "  Password:     $PG_PASSWORD"
    echo "  Subnet:       pg-subnet (위임)"
    echo "  DATABASE_URL: postgresql://${PG_ADMIN}:${PG_PASSWORD}@${pg_fqdn}:5432/db_cloosphere?sslmode=require"
    echo ""
    echo -e "${BOLD}── Redis (PE) ──${NC}"
    echo "  Host:         $redis_host"
    echo "  Port:         6380 (SSL)"
    echo "  Key:          $redis_key"
    echo "  REDIS_URL:    rediss://:${redis_key}@${redis_host}:6380/0"
    echo ""
    echo -e "${BOLD}── Azure AI Search (PE) ──${NC}"
    echo "  Endpoint:     https://${SEARCH}.search.windows.net"
    echo "  Admin Key:    $search_key"
    echo ""
    echo -e "${BOLD}── Azure OpenAI (PE) ──${NC}"
    echo "  Endpoint:     $openai_ep"
    echo "  Key:          $openai_key"
    echo ""
    echo -e "${BOLD}── Document Intelligence (PE) ──${NC}"
    echo "  Endpoint:     $docitg_ep"
    echo "  Key:          $docitg_key"
    echo ""
    echo -e "${BOLD}── Storage Account (PE) ──${NC}"
    echo "  Name:         $SA"
    echo "  Blob:         $BLOB_CONTAINER (PE: blob)"
    echo "  File Share:   $FILE_SHARE (PE: file)"
    echo "  Key:          $storage_key"
    echo ""
    if [[ "$AFD_ENABLED" == "true" ]]; then
        local afd_hostname afd_id_summary
        afd_hostname=$(az afd endpoint show -g "$RG" --profile-name "$AFD" -n "$AFD_EP" --query "hostName" -o tsv 2>/dev/null || echo "(조회 실패)")
        afd_id_summary=$(az afd profile show -g "$RG" -n "$AFD" --query "frontDoorId" -o tsv 2>/dev/null || echo "(조회 실패)")
        echo -e "${BOLD}── Front Door + WAF ──${NC}"
        echo "  URL:          https://${afd_hostname}"
        echo "  SKU:          $AFD_SKU"
        echo "  WAF 모드:     $AFD_WAF_MODE"
        echo "  FDID:         $afd_id_summary"
        echo "  App 접근:     Front Door만 허용"
        echo ""
    fi

    echo -e "${BOLD}── Private Endpoints ──${NC}"
    az network private-endpoint list -g "$RG" \
        --query "[].{Name:name, Subnet:subnet.id, Status:privateLinkServiceConnections[0].privateLinkServiceConnectionState.status}" \
        -o table 2>/dev/null || echo "  (조회 실패)"
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
    warn "Production 환경 삭제: $CUSTOMER"
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
