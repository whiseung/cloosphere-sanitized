#!/usr/bin/env bash
#
# Cloosphere Demo Environment Manager
# Azure Container Apps 기반 고객별 데모 환경 관리
#
# 사용법:
#   ./scripts/demo-env.sh create <customer-name>    # 데모 환경 생성
#   ./scripts/demo-env.sh delete <customer-name>    # 데모 환경 삭제
#   ./scripts/demo-env.sh list                      # 전체 데모 환경 목록
#   ./scripts/demo-env.sh info <customer-name>      # 환경 상세 정보
#   ./scripts/demo-env.sh logs <customer-name>      # 로그 확인
#   ./scripts/demo-env.sh restart <customer-name>   # 재시작
#   ./scripts/demo-env.sh init                      # 인프라 초기 구성 (최초 1회)
#
# 설정 파일 (우선순위: 고객별 > 공통):
#   .env.demo              공통 설정 (LLM, 인프라 등)
#   .env.demo.<customer>   고객별 오버라이드 (인덱스 접두사, OAuth 등)
#
# 예시:
#   scripts/.env.demo              ← 공통 (API 키, 인프라)
#   scripts/.env.demo.samsung      ← 삼성 전용 오버라이드
#   scripts/.env.demo.hyundai      ← 현대 전용 오버라이드
#
set -euo pipefail

###############################################################################
# 설정 파일 로드
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 공통 .env.demo 로드
load_base_env() {
    for envfile in "$SCRIPT_DIR/.env.demo" "$PROJECT_ROOT/.env.demo"; do
        if [[ -f "$envfile" ]]; then
            # shellcheck disable=SC1090
            source "$envfile"
            return
        fi
    done
}

# 고객별 .env.demo.<customer> 오버라이드 로드
load_customer_env() {
    local customer="$1"
    for envfile in "$SCRIPT_DIR/.env.demo.${customer}" "$PROJECT_ROOT/.env.demo.${customer}"; do
        if [[ -f "$envfile" ]]; then
            log "고객 설정 로드: $(basename "$envfile")"
            # shellcheck disable=SC1090
            source "$envfile"
            return
        fi
    done
}

load_base_env

###############################################################################
# 설정 — 환경변수 또는 .env.demo 로 오버라이드
###############################################################################

# Azure 구독/테넌트 (선택)
AZURE_SUBSCRIPTION="${DEMO_AZURE_SUBSCRIPTION:-}"
AZURE_TENANT="${DEMO_AZURE_TENANT:-}"

# Azure 리소스
RESOURCE_GROUP="${DEMO_RESOURCE_GROUP:-cloosphere-demo}"
LOCATION="${DEMO_LOCATION:-koreacentral}"
ENVIRONMENT_NAME="${DEMO_ENV_NAME:-cloosphere-demo-env}"

# 스토리지
STORAGE_ACCOUNT="${DEMO_STORAGE_ACCOUNT:-cloospheredemo}"
FILE_SHARE_NAME="${DEMO_FILE_SHARE:-demo-data}"
STORAGE_LINK_NAME="${DEMO_STORAGE_LINK_NAME:-demostorage}"   # Environment 내 스토리지 별칭

# 컨테이너 이미지
ACR_NAME="${DEMO_ACR_NAME:-clolodsphere}"
IMAGE_NAME="${DEMO_IMAGE:-cloosphere}"
IMAGE_TAG="${DEMO_IMAGE_TAG:-latest}"

# ACR 인증 (username/password 방식, 비어있으면 az acr login 시도)
ACR_USERNAME="${DEMO_ACR_USERNAME:-}"
ACR_PASSWORD="${DEMO_ACR_PASSWORD:-}"

# 컨테이너 리소스
CONTAINER_PORT=8080
MIN_REPLICAS="${DEMO_MIN_REPLICAS:-0}"
MAX_REPLICAS="${DEMO_MAX_REPLICAS:-1}"
CPU="${DEMO_CPU:-1.0}"
MEMORY="${DEMO_MEMORY:-2.0Gi}"

###############################################################################
# 헬퍼
###############################################################################

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()   { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*" >&2; }

check_az() {
    if ! command -v az &>/dev/null; then
        error "Azure CLI가 설치되어 있지 않습니다."
        error "설치: https://docs.microsoft.com/cli/azure/install-azure-cli"
        exit 1
    fi

    if ! az account show &>/dev/null 2>&1; then
        error "Azure에 로그인되어 있지 않습니다. 'az login'을 실행하세요."
        exit 1
    fi

    # 구독 선택
    if [[ -n "$AZURE_SUBSCRIPTION" ]]; then
        az account set --subscription "$AZURE_SUBSCRIPTION" --output none
        log "구독: ${AZURE_SUBSCRIPTION}"
    fi

    # Microsoft.App 리소스 프로바이더 등록 확인
    local provider_state
    provider_state=$(az provider show --namespace Microsoft.App --query "registrationState" -o tsv 2>/dev/null || echo "NotRegistered")
    if [[ "$provider_state" != "Registered" ]]; then
        log "Microsoft.App 리소스 프로바이더 등록 중 (최초 1회, 1-2분 소요)..."
        az provider register --namespace Microsoft.App --output none
        local retry=0
        while [[ $retry -lt 30 ]]; do
            provider_state=$(az provider show --namespace Microsoft.App --query "registrationState" -o tsv 2>/dev/null)
            if [[ "$provider_state" == "Registered" ]]; then
                break
            fi
            sleep 5
            retry=$((retry + 1))
        done
        if [[ "$provider_state" != "Registered" ]]; then
            error "Microsoft.App 프로바이더 등록 타임아웃. 수동 실행: az provider register -n Microsoft.App --wait"
            exit 1
        fi
        log "Microsoft.App 리소스 프로바이더 등록 완료"
    fi
}

app_name() {
    # 고객명을 Container App 이름으로 변환 (소문자, 하이픈만 허용)
    echo "demo-${1}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g'
}

generate_secret() {
    openssl rand -hex 32
}

full_image() {
    echo "${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}"
}

# 값이 비어있지 않은 환경변수만 배열에 추가
add_env() {
    local var_name="$1"
    local var_value="$2"
    if [[ -n "$var_value" ]]; then
        ENV_VARS+=("${var_name}=${var_value}")
    fi
}

###############################################################################
# init — 인프라 초기 구성 (최초 1회)
###############################################################################

cmd_init() {
    check_az
    log "데모 인프라 초기 구성 시작..."

    # 리소스 그룹
    if az group show --name "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        log "리소스 그룹 '${RESOURCE_GROUP}' 이미 존재"
    else
        log "리소스 그룹 생성: ${RESOURCE_GROUP}"
        az group create \
            --name "$RESOURCE_GROUP" \
            --location "$LOCATION" \
            --output none
    fi

    # 스토리지 계정
    if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        log "스토리지 계정 '${STORAGE_ACCOUNT}' 이미 존재"
    else
        log "스토리지 계정 생성: ${STORAGE_ACCOUNT}"
        az storage account create \
            --name "$STORAGE_ACCOUNT" \
            --resource-group "$RESOURCE_GROUP" \
            --location "$LOCATION" \
            --sku Standard_LRS \
            --output none
    fi

    # 파일 공유
    STORAGE_KEY=$(az storage account keys list \
        --account-name "$STORAGE_ACCOUNT" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[0].value" -o tsv)

    if az storage share show --name "$FILE_SHARE_NAME" --account-name "$STORAGE_ACCOUNT" --account-key "$STORAGE_KEY" &>/dev/null 2>&1; then
        log "파일 공유 '${FILE_SHARE_NAME}' 이미 존재"
    else
        log "파일 공유 생성: ${FILE_SHARE_NAME}"
        az storage share create \
            --name "$FILE_SHARE_NAME" \
            --account-name "$STORAGE_ACCOUNT" \
            --account-key "$STORAGE_KEY" \
            --output none
    fi

    # Container Apps Environment
    if az containerapp env show --name "$ENVIRONMENT_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        log "Container Apps Environment '${ENVIRONMENT_NAME}' 이미 존재"
    else
        log "Container Apps Environment 생성: ${ENVIRONMENT_NAME}"
        az containerapp env create \
            --name "$ENVIRONMENT_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --location "$LOCATION" \
            --output none
    fi

    # ACR 인증
    if [[ -n "$ACR_USERNAME" && -n "$ACR_PASSWORD" ]]; then
        log "ACR 인증: admin 계정 사용 (${ACR_NAME})"
    else
        log "ACR 로그인: az acr login (${ACR_NAME})"
        if ! az acr login --name "$ACR_NAME" 2>/dev/null; then
            warn "ACR 로그인 실패. DEMO_ACR_USERNAME/DEMO_ACR_PASSWORD 설정을 확인하세요."
            warn "또는 수동 실행: az acr login --name ${ACR_NAME}"
        fi
    fi

    # Environment에 스토리지 연결
    log "스토리지를 Environment에 연결..."
    az containerapp env storage set \
        --name "$ENVIRONMENT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --storage-name "$STORAGE_LINK_NAME" \
        --azure-file-account-name "$STORAGE_ACCOUNT" \
        --azure-file-account-key "$STORAGE_KEY" \
        --azure-file-share-name "$FILE_SHARE_NAME" \
        --access-mode ReadWrite \
        --output none 2>/dev/null || true

    echo ""
    log "초기 구성 완료!"
    echo ""
    echo "  구독:          $(az account show --query name -o tsv)"
    echo "  리소스 그룹:    ${RESOURCE_GROUP}"
    echo "  위치:          ${LOCATION}"
    echo "  스토리지:       ${STORAGE_ACCOUNT}/${FILE_SHARE_NAME}"
    echo "  Environment:   ${ENVIRONMENT_NAME}"
    echo "  ACR:           ${ACR_NAME}.azurecr.io"
    echo ""
    echo "  다음 단계: ./scripts/demo-env.sh create <customer-name>"
}

###############################################################################
# create — 고객 데모 환경 생성
###############################################################################

cmd_create() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    # 고객별 설정 오버라이드 로드
    load_customer_env "$customer"

    check_az

    # 중복 체크
    if az containerapp show --name "$name" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        error "데모 환경 '${customer}'가 이미 존재합니다."
        echo "  삭제 후 재생성: ./scripts/demo-env.sh delete ${customer}"
        exit 1
    fi

    local secret_key
    secret_key=$(generate_secret)

    log "데모 환경 생성: ${customer} (${name})"

    # 고객별 데이터 디렉토리 생성
    STORAGE_KEY=$(az storage account keys list \
        --account-name "$STORAGE_ACCOUNT" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[0].value" -o tsv)

    az storage directory create \
        --name "$name" \
        --share-name "$FILE_SHARE_NAME" \
        --account-name "$STORAGE_ACCOUNT" \
        --account-key "$STORAGE_KEY" \
        --output none 2>/dev/null || true

    # 환경 변수 구성 — DEMO_* 접두사를 떼고 앱 환경변수로 전달
    ENV_VARS=()

    # 고정값 (고객별 자동 설정)
    add_env "DATABASE_URL"     "sqlite:////app/backend/data/webui.db"
    add_env "WEBUI_SECRET_KEY" "$secret_key"
    add_env "PORT"             "$CONTAINER_PORT"
    add_env "ENV"              "prod"
    add_env "SCARF_NO_ANALYTICS"      "true"
    add_env "DO_NOT_TRACK"            "true"
    add_env "ANONYMIZED_TELEMETRY"    "false"

    # DEMO_* 환경변수를 앱 환경변수로 매핑
    # .env.demo에 DEMO_WEBUI_NAME="Cloosphere" 가 있으면 WEBUI_NAME="Cloosphere" 로 전달
    local demo_vars=(
        # 기본 설정
        WEBUI_NAME
        DEFAULT_LOCALE
        ENABLE_SIGNUP
        ENABLE_LOGIN_FORM

        # LLM 연결
        OPENAI_API_BASE_URL
        OPENAI_API_KEY

        # Azure OpenAI
        AZURE_OPENAI_ENDPOINT
        AZURE_OPENAI_DEPLOYMENT
        AZURE_OPENAI_API_KEY
        AZURE_OPENAI_API_VERSION
        AZURE_OPENAI_EMBEDDING_MODEL

        # Vector DB
        VECTOR_DB
        AZURE_SEARCH_ENDPOINT
        AZURE_SEARCH_API_KEY
        AZURE_SEARCH_INDEX
        AZURE_SEARCH_API_VERSION
        AZURE_SEARCH_DBSPHERE_INDEX_NAME

        # 기능 토글
        ENABLE_WEB_SEARCH
        ENABLE_IMAGE_GENERATION
        ENABLE_CODE_INTERPRETER
        ENABLE_CHANNELS
        ENABLE_COMMUNITY_SHARING

        # RAG / 임베딩
        RAG_EMBEDDING_ENGINE
        RAG_EMBEDDING_MODEL

        # 파일 업로드 (Azure Blob)
        AZURE_STORAGE_MEDIA_BASE_URL
        AZURE_STORAGE_MEDIA_CONTAINER
        AZURE_STORAGE_MEDIA_SAS_KEY

        # Microsoft OAuth
        ENABLE_OAUTH_SIGNUP
        MICROSOFT_CLIENT_ID
        MICROSOFT_CLIENT_SECRET
        MICROSOFT_CLIENT_TENANT_ID
        MICROSOFT_OAUTH_SCOPE

        # OneDrive / SharePoint
        ENABLE_ONEDRIVE_INTEGRATION
        ONEDRIVE_CLIENT_ID
        ENABLE_SHAREPOINT_INTEGRATION
        ONEDRIVE_SHAREPOINT_TENANT_ID
        ONEDRIVE_SHAREPOINT_URL

        # DbSphere
        DBSPHERE_TYPES

        # 인덱스 접두사 (Azure Search 인덱스 격리)
        SEARCH_INDEX_PREFIX

        # 기타
        BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
        ENABLE_LICENSE_ENFORCEMENT
    )

    for var in "${demo_vars[@]}"; do
        local demo_key="DEMO_${var}"
        add_env "$var" "${!demo_key:-}"
    done

    # 자동 기본값 (고객별 설정 없으면 고객명 기반으로 생성)
    if [[ -z "${DEMO_WEBUI_NAME:-}" ]]; then
        add_env "WEBUI_NAME" "Cloosphere Demo (${customer})"
    fi
    if [[ -z "${DEMO_SEARCH_INDEX_PREFIX:-}" ]]; then
        add_env "SEARCH_INDEX_PREFIX" "demo_${customer}"
    fi
    if [[ -z "${DEMO_ENABLE_LICENSE_ENFORCEMENT:-}" ]]; then
        add_env "ENABLE_LICENSE_ENFORCEMENT" "false"
    fi

    # ACR 인증 옵션
    local registry_args=(
        --registry-server "${ACR_NAME}.azurecr.io"
    )
    if [[ -n "$ACR_USERNAME" && -n "$ACR_PASSWORD" ]]; then
        registry_args+=(--registry-username "$ACR_USERNAME" --registry-password "$ACR_PASSWORD")
    fi

    # Container App 생성 (볼륨 포함 YAML 방식)
    log "Container App 배포 중 (볼륨 포함)..."

    # Environment에 스토리지가 연결되어 있는지 확인, 없으면 연결
    local storage_exists
    storage_exists=$(az containerapp env storage show \
        --name "$ENVIRONMENT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --storage-name "$STORAGE_LINK_NAME" \
        --query "name" -o tsv 2>/dev/null || echo "")

    if [[ -z "$storage_exists" ]]; then
        log "Environment에 스토리지 연결..."
        local storage_key_mount
        storage_key_mount=$(az storage account keys list \
            --account-name "$STORAGE_ACCOUNT" \
            --resource-group "$RESOURCE_GROUP" \
            --query "[0].value" -o tsv)

        az containerapp env storage set \
            --name "$ENVIRONMENT_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --storage-name "$STORAGE_LINK_NAME" \
            --azure-file-account-name "$STORAGE_ACCOUNT" \
            --azure-file-account-key "$storage_key_mount" \
            --azure-file-share-name "$FILE_SHARE_NAME" \
            --access-mode ReadWrite \
            --output none
    fi

    # YAML 파일 생성 (볼륨 마운트 포함) — Python으로 생성하여 타입 안전성 보장
    local create_yaml
    create_yaml=$(mktemp /tmp/demo-env-create-XXXXXX.yaml)

    # 환경변수를 파일로 전달
    local env_file
    env_file=$(mktemp /tmp/demo-env-vars-XXXXXX.txt)
    printf '%s\n' "${ENV_VARS[@]}" > "$env_file"

    python3 - "$create_yaml" "$env_file" "$name" "$(full_image)" \
        "$CONTAINER_PORT" "$CPU" "$MEMORY" "$MIN_REPLICAS" "$MAX_REPLICAS" \
        "$ACR_NAME" "$ACR_USERNAME" "$ACR_PASSWORD" "$STORAGE_LINK_NAME" <<'PYEOF'
import sys, yaml

out_path, env_file, name, image = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
port, cpu, memory = int(sys.argv[5]), float(sys.argv[6]), sys.argv[7]
min_rep, max_rep = int(sys.argv[8]), int(sys.argv[9])
acr_name, acr_user, acr_pass, storage_link = sys.argv[10], sys.argv[11], sys.argv[12], sys.argv[13]

# Parse env vars (all as strings)
env_list = []
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if '=' in line:
            k, v = line.split('=', 1)
            env_list.append({"name": k, "value": str(v)})

config = {
    "properties": {
        "configuration": {
            "ingress": {
                "external": True,
                "targetPort": port,
                "transport": "Auto",
            },
            "registries": [{
                "server": f"{acr_name}.azurecr.io",
                "username": acr_user,
                "passwordSecretRef": "acr-password",
            }],
            "secrets": [{
                "name": "acr-password",
                "value": acr_pass,
            }],
        },
        "template": {
            "containers": [{
                "name": name,
                "image": image,
                "resources": {
                    "cpu": cpu,
                    "memory": memory,
                },
                "env": env_list,
                "volumeMounts": [{
                    "volumeName": "data-volume",
                    "mountPath": "/app/backend/data",
                    "subPath": name,
                }],
            }],
            "scale": {
                "minReplicas": min_rep,
                "maxReplicas": max_rep,
            },
            "volumes": [{
                "name": "data-volume",
                "storageName": storage_link,
                "storageType": "AzureFile",
                "mountOptions": "dir_mode=0777,file_mode=0666",
            }],
        },
    },
}

with open(out_path, "w") as f:
    yaml.dump(config, f, default_flow_style=False)

print(f"YAML generated: {len(env_list)} env vars, volume mount included")
PYEOF

    rm -f "$env_file"

    az containerapp create \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT_NAME" \
        --yaml "$create_yaml" \
        --output none

    rm -f "$create_yaml"

    # URL 조회
    local fqdn
    fqdn=$(az containerapp show \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")

    echo ""
    log "데모 환경 생성 완료!"
    echo ""
    echo "  고객:       ${customer}"
    echo "  앱 이름:    ${name}"
    if [[ -n "$fqdn" ]]; then
        echo "  URL:        https://${fqdn}"
    fi
    echo "  Secret Key: ${secret_key}"
    echo ""
    echo "  첫 접속 시 관리자 계정을 생성하세요."
}

###############################################################################
# mount_volume — 볼륨 마운트 (공통 함수)
###############################################################################

mount_volume() {
    local name="$1"

    log "데이터 볼륨 마운트..."

    # Environment에 스토리지가 연결되어 있는지 확인, 없으면 연결
    local storage_exists
    storage_exists=$(az containerapp env storage show \
        --name "$ENVIRONMENT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --storage-name "$STORAGE_LINK_NAME" \
        --query "name" -o tsv 2>/dev/null || echo "")

    if [[ -z "$storage_exists" ]]; then
        log "Environment에 스토리지 연결..."
        local storage_key
        storage_key=$(az storage account keys list \
            --account-name "$STORAGE_ACCOUNT" \
            --resource-group "$RESOURCE_GROUP" \
            --query "[0].value" -o tsv)

        az containerapp env storage set \
            --name "$ENVIRONMENT_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --storage-name "$STORAGE_LINK_NAME" \
            --azure-file-account-name "$STORAGE_ACCOUNT" \
            --azure-file-account-key "$storage_key" \
            --azure-file-share-name "$FILE_SHARE_NAME" \
            --access-mode ReadWrite \
            --output none
    fi

    local tmpfile
    tmpfile=$(mktemp /tmp/demo-env-XXXXXX.yaml)

    az containerapp show \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --output yaml > "$tmpfile"

    # YAML에 볼륨 설정 추가
    python3 - "$tmpfile" "$name" "$STORAGE_LINK_NAME" <<'PYEOF'
import sys, yaml

filepath, customer_dir, storage_link = sys.argv[1], sys.argv[2], sys.argv[3]

with open(filepath) as f:
    config = yaml.safe_load(f)

template = config.setdefault("properties", {}).setdefault("template", {})

template["volumes"] = [{
    "name": "data-volume",
    "storageName": storage_link,
    "storageType": "AzureFile",
    "mountOptions": "dir_mode=0777,file_mode=0666",
}]

for container in template.get("containers", []):
    container["volumeMounts"] = [{
        "volumeName": "data-volume",
        "mountPath": "/app/backend/data",
        "subPath": customer_dir,
    }]

with open(filepath, "w") as f:
    yaml.dump(config, f, default_flow_style=False)
PYEOF

    az containerapp update \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --yaml "$tmpfile" \
        --output none

    rm -f "$tmpfile"
    log "볼륨 마운트 완료"
}

###############################################################################
# mount — 볼륨 마운트 (수동 실행용)
###############################################################################

cmd_mount() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    check_az

    if ! az containerapp show --name "$name" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        error "데모 환경 '${customer}'를 찾을 수 없습니다."
        exit 1
    fi

    mount_volume "$name"
}

###############################################################################
# delete — 고객 데모 환경 삭제
###############################################################################

cmd_delete() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    check_az

    if ! az containerapp show --name "$name" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        error "데모 환경 '${customer}'를 찾을 수 없습니다."
        exit 1
    fi

    warn "데모 환경 '${customer}'를 삭제합니다."
    read -rp "계속하시겠습니까? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "취소됨."
        exit 0
    fi

    log "Container App 삭제: ${name}"
    az containerapp delete \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --yes \
        --output none

    # 데이터 삭제 여부 확인
    read -rp "데이터도 삭제하시겠습니까? (y/N): " confirm_data
    if [[ "$confirm_data" == "y" || "$confirm_data" == "Y" ]]; then
        STORAGE_KEY=$(az storage account keys list \
            --account-name "$STORAGE_ACCOUNT" \
            --resource-group "$RESOURCE_GROUP" \
            --query "[0].value" -o tsv)

        log "데이터 디렉토리 삭제: ${name}"
        az storage file delete-batch \
            --source "$FILE_SHARE_NAME" \
            --account-name "$STORAGE_ACCOUNT" \
            --account-key "$STORAGE_KEY" \
            --pattern "${name}/*" \
            --output none 2>/dev/null || true

        az storage directory delete \
            --name "$name" \
            --share-name "$FILE_SHARE_NAME" \
            --account-name "$STORAGE_ACCOUNT" \
            --account-key "$STORAGE_KEY" \
            --output none 2>/dev/null || true
    fi

    log "삭제 완료: ${customer}"
}

###############################################################################
# list — 전체 데모 환경 목록
###############################################################################

cmd_list() {
    check_az

    log "데모 환경 목록 (구독: $(az account show --query name -o tsv))"
    echo ""

    local count
    count=$(az containerapp list \
        --resource-group "$RESOURCE_GROUP" \
        --query "[?starts_with(name, 'demo-')] | length(@)" \
        --output tsv 2>/dev/null || echo "0")

    if [[ "$count" == "0" ]]; then
        echo "  등록된 데모 환경이 없습니다."
        echo "  생성: ./scripts/demo-env.sh create <customer-name>"
    else
        az containerapp list \
            --resource-group "$RESOURCE_GROUP" \
            --query "[?starts_with(name, 'demo-')].{Name:name, FQDN:properties.configuration.ingress.fqdn, Status:properties.provisioningState}" \
            --output table 2>/dev/null

        echo ""
        log "총 ${count}개 데모 환경"
    fi
}

###############################################################################
# info — 환경 상세 정보
###############################################################################

cmd_info() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    check_az

    if ! az containerapp show --name "$name" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        error "데모 환경 '${customer}'를 찾을 수 없습니다."
        exit 1
    fi

    local fqdn provisioning_state
    fqdn=$(az containerapp show \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.configuration.ingress.fqdn" -o tsv)

    provisioning_state=$(az containerapp show \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.provisioningState" -o tsv)

    local replicas
    replicas=$(az containerapp replica list \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --query "length(@)" -o tsv 2>/dev/null || echo "0")

    echo ""
    echo "  구독:        $(az account show --query name -o tsv)"
    echo "  고객:        ${customer}"
    echo "  앱 이름:     ${name}"
    echo "  URL:         https://${fqdn}"
    echo "  상태:        ${provisioning_state}"
    echo "  활성 복제본:  ${replicas}"
    echo "  데이터 경로:  ${FILE_SHARE_NAME}/${name}/"
    echo ""
}

###############################################################################
# logs — 로그 확인
###############################################################################

cmd_logs() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    check_az

    log "로그 조회: ${customer} (최근 100줄)"
    az containerapp logs show \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --tail 100 \
        --follow false 2>/dev/null || error "로그를 조회할 수 없습니다."
}

###############################################################################
# update — 이미지 업데이트
###############################################################################

cmd_update() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    check_az

    if ! az containerapp show --name "$name" --resource-group "$RESOURCE_GROUP" &>/dev/null 2>&1; then
        error "데모 환경 '${customer}'를 찾을 수 없습니다."
        exit 1
    fi

    log "이미지 업데이트: ${customer} → $(full_image)"
    az containerapp update \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$(full_image)" \
        --output none

    log "업데이트 완료"
}

###############################################################################
# restart — 재시작
###############################################################################

cmd_restart() {
    local customer="$1"
    local name
    name=$(app_name "$customer")

    check_az

    log "재시작: ${customer}"

    local revision
    revision=$(az containerapp revision list \
        --name "$name" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[0].name" -o tsv 2>/dev/null)

    if [[ -n "$revision" ]]; then
        az containerapp revision restart \
            --name "$name" \
            --resource-group "$RESOURCE_GROUP" \
            --revision "$revision" \
            --output none
        log "재시작 완료"
    else
        warn "활성 revision이 없습니다. (scale-to-zero 상태일 수 있음)"
    fi
}

###############################################################################
# main
###############################################################################

usage() {
    cat <<USAGE
Cloosphere Demo Environment Manager

사용법: $0 <command> [options]

Commands:
  init                      인프라 초기 구성 (최초 1회)
  create <customer-name>    데모 환경 생성
  mount  <customer-name>    볼륨 마운트 (생성 후 수동 실행용)
  delete <customer-name>    데모 환경 삭제
  list                      전체 데모 환경 목록
  info   <customer-name>    환경 상세 정보
  update  <customer-name>   이미지 업데이트 (새 빌드 적용)
  logs   <customer-name>    로그 확인
  restart <customer-name>   재시작

설정 파일 (우선순위: 고객별 > 공통):
  scripts/.env.demo              공통 설정 (LLM 키, 인프라 등)
  scripts/.env.demo.<customer>   고객별 오버라이드

  샘플: cp scripts/.env.demo.example scripts/.env.demo

  DEMO_* 접두사가 떼어지고 앱 환경변수로 전달됩니다.
  예) DEMO_OPENAI_API_KEY="sk-xxx" → OPENAI_API_KEY="sk-xxx"

  전체 변수 목록: scripts/.env.demo.example 참조

자동 기본값 (고객별 설정 없을 때):
  WEBUI_NAME          → "Cloosphere Demo (<customer>)"
  SEARCH_INDEX_PREFIX → "demo_<customer>"

예시:
  $0 init                          # 최초 인프라 구성
  $0 create samsung                # .env.demo + .env.demo.samsung 로드
  $0 create hyundai                # .env.demo + .env.demo.hyundai 로드
  $0 list                          # 전체 목록 확인
  $0 delete samsung                # 삼성 데모 환경 삭제
USAGE
}

main() {
    local command="${1:-}"
    shift || true

    case "$command" in
        init)
            cmd_init
            ;;
        create)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 create <customer-name>"
                exit 1
            fi
            cmd_create "$1"
            ;;
        mount)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 mount <customer-name>"
                exit 1
            fi
            cmd_mount "$1"
            ;;
        delete)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 delete <customer-name>"
                exit 1
            fi
            cmd_delete "$1"
            ;;
        list)
            cmd_list
            ;;
        info)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 info <customer-name>"
                exit 1
            fi
            cmd_info "$1"
            ;;
        update)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 update <customer-name>"
                exit 1
            fi
            cmd_update "$1"
            ;;
        logs)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 logs <customer-name>"
                exit 1
            fi
            cmd_logs "$1"
            ;;
        restart)
            if [[ -z "${1:-}" ]]; then
                error "고객명을 입력하세요: $0 restart <customer-name>"
                exit 1
            fi
            cmd_restart "$1"
            ;;
        help|--help|-h|"")
            usage
            ;;
        *)
            error "알 수 없는 명령: ${command}"
            echo ""
            usage
            exit 1
            ;;
    esac
}

main "$@"
