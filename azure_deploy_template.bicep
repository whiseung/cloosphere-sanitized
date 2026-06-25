// ============================================================================
// Azure Infrastructure Deployment Template
// ============================================================================
// 이 템플릿은 새로운 환경에 배포할 때 "REQUIRED PARAMETERS" 섹션만 수정하면 됩니다.
//
// 사용법:
//   1. "REQUIRED PARAMETERS" 섹션의 값들을 새 환경에 맞게 수정
//   2. 필요시 "OPTIONAL PARAMETERS" 섹션 조정
//   3. az deployment group create --template-file azure_deploy_template.bicep
//
// 명명 규칙: {regionCode}-{projectName}-{environment}-{resourceType}-{instance}
// 예시: krc-ai-dev-rds-01
// ============================================================================

// ============================================================================
// REQUIRED PARAMETERS - 새 환경 배포 시 반드시 수정
// ============================================================================

@description('Azure 구독 ID')
param subscriptionId string = '00000000-0000-0000-0000-000000000000'  // TODO: 새 구독 ID 입력

@description('리전 코드 (krc=Korea Central, krs=Korea South, eus=East US, eus2=East US 2, weu=West Europe)')
@allowed(['krc', 'krs', 'eus', 'eus2', 'weu', 'jpe', 'jpw', 'sea'])
param regionCode string = 'krc'

@description('Azure 리전 이름')
@allowed(['koreacentral', 'koreasouth', 'eastus', 'eastus2', 'westeurope', 'japaneast', 'japanwest', 'southeastasia'])
param location string = 'koreacentral'

@description('프로젝트 이름 (소문자, 리소스 이름에 사용)')
@minLength(2)
@maxLength(10)
param projectName string = 'ai'

@description('환경 (dev, stg, prd)')
@allowed(['dev', 'stg', 'prd'])
param environment string = 'dev'

@description('회사/테넌트 접두사 (VNet 등에 사용)')
@minLength(2)
@maxLength(10)
param companyPrefix string = 'mycompany'

@description('PostgreSQL 관리자 비밀번호')
@secure()
@minLength(8)
param postgresAdminPassword string

// ============================================================================
// NETWORK CONFIGURATION - 환경별 네트워크 설정
// ============================================================================

@description('VNet 주소 공간 (CIDR)')
param vnetAddressSpace string = '10.100.0.0/16'

@description('서브넷 CIDR 설정')
param subnetCidrs object = {
  vm: '10.100.0.0/27'       // VM 서브넷 (32 IPs)
  ap: '10.100.1.0/26'       // App Service 서브넷 (64 IPs)
  pe: '10.100.3.0/27'       // Private Endpoint 서브넷 (32 IPs)
  pgsql: '10.100.4.0/27'    // PostgreSQL 서브넷 (32 IPs)
  etc: '10.100.5.0/27'      // 기타 서브넷 (32 IPs)
}

@description('VM 고정 Private IP 주소')
param vmPrivateIps object = {
  vm01: '10.100.0.4'
  vm02: '10.100.0.5'
}

@description('방화벽 허용 IP 목록 (사무실, VPN 등)')
param allowedIps array = [
  // '203.0.113.1'    // 예시: 본사 NAT IP
  // '198.51.100.10'  // 예시: VPN Gateway
]

// ============================================================================
// SECURITY PARAMETERS - 보안 설정
// ============================================================================

@description('PostgreSQL 관리자 계정명')
param postgresAdminLogin string = 'pgsqldbadmin'

@description('VM SSH 공개키 (비워두면 비밀번호 인증 사용)')
param vmSshPublicKey string = ''

@description('VM 관리자 계정명')
param vmAdminUsername string = 'azureuser'

@description('VM 관리자 비밀번호 (SSH 키 미사용 시 필수)')
@secure()
param vmAdminPassword string = ''

// ============================================================================
// OPTIONAL PARAMETERS - 필요시 조정
// ============================================================================

@description('리소스 인스턴스 번호')
param instanceNumber string = '01'

@description('환경 표시명 (태그용)')
param environmentDisplayName string = environment == 'prd' ? 'Production' : environment == 'stg' ? 'Staging' : 'Development'

@description('프로젝트 표시명 (태그용)')
param projectDisplayName string = '${toUpper(projectName)} Platform'

// ============================================================================
// FEATURE FLAGS - 배포할 리소스 선택
// ============================================================================

@description('VM 배포 여부')
param deployVMs bool = true

@description('Redis 배포 여부')
param deployRedis bool = true

@description('Azure AI Search 배포 여부')
param deploySearch bool = true

@description('Document Intelligence 배포 여부')
param deployDocIntelligence bool = true

@description('Azure OpenAI 배포 여부')
param deployOpenAI bool = true

@description('VNet Peering 배포 여부 (다른 리전 VNet과 연결)')
param deployVnetPeering bool = false

@description('Peering 대상 VNet ID (deployVnetPeering=true 시 필수)')
param peeringTargetVnetId string = ''

// ============================================================================
// OPENAI MODEL CONFIGURATION - Azure OpenAI 모델 설정
// ============================================================================

@description('배포할 OpenAI 모델 목록')
param openAIModels array = [
  {
    name: 'gpt-4o'
    modelName: 'gpt-4o'
    version: '2024-11-20'
    skuName: 'GlobalStandard'
    capacity: 150
  }
  {
    name: 'gpt-4o-mini'
    modelName: 'gpt-4o-mini'
    version: '2024-07-18'
    skuName: 'GlobalStandard'
    capacity: 300
  }
  {
    name: 'text-embedding-3-large'
    modelName: 'text-embedding-3-large'
    version: '1'
    skuName: 'Standard'
    capacity: 350
  }
]

// ============================================================================
// SKU CONFIGURATION - 리소스 크기/티어 설정
// ============================================================================

@description('App Service Plan SKU (owui)')
param owuiAppServicePlanSku object = {
  name: 'P0v3'
  tier: 'Premium0V3'
  capacity: 1  // 초기 인스턴스 수
}

@description('Redis SKU')
param redisSku object = {
  name: 'Standard'
  family: 'C'
  capacity: 2
}

@description('PostgreSQL SKU')
param postgresSku object = {
  name: 'Standard_D2ds_v5'
  tier: 'GeneralPurpose'
  storageSizeGB: 128
}

@description('AI Search SKU')
param searchSku string = 'standard'

@description('Container Registry SKU')
param acrSku string = 'Premium'

// ============================================================================
// EXTERNAL RESOURCES - 외부 리소스 참조 (Hub 등)
// ============================================================================

@description('외부 Private DNS Zone 사용 여부 (Hub 구성 시)')
param useExternalDnsZones bool = false

@description('외부 PostgreSQL Private DNS Zone ID (Hub RG)')
param externalPostgresDnsZoneId string = ''

// ============================================================================
// COMPUTED VARIABLES - 자동 생성 (수정 불필요)
// ============================================================================

// 기본 네이밍 패턴
var baseNameDash = '${regionCode}-${projectName}-${environment}'           // krc-ai-dev
var baseNameNoDash = '${regionCode}${projectName}${environment}'           // krcaidev
var vnetBaseName = '${companyPrefix}-${projectName}-${environment}'        // mycompany-ai-dev

// 리소스 그룹 (배포 대상)
var resourceGroupName = '${companyPrefix}-${projectName}-${environment}-${regionCode}-${instanceNumber}-rg'

// ============================================================================
// RESOURCE NAMES - 자동 생성되는 리소스 이름
// ============================================================================

// Virtual Network
var vnetName = '${vnetBaseName}-${regionCode}-${instanceNumber}-vnet'      // mycompany-ai-dev-krc-01-vnet

// Network Security Groups
var nsgNames = {
  vm: '${vnetName}-vm-subnet-nsg'
  ap: '${vnetName}-ap-subnet-nsg'
  etc: '${vnetName}-etc-subnet-nsg'
}

// Redis Cache
var redisName = '${baseNameDash}-rds-${instanceNumber}'                    // krc-ai-dev-rds-01

// App Services
var owuiAppServiceName = '${baseNameDash}-owui-as-${instanceNumber}'       // krc-ai-dev-owui-as-01

// App Service Plans
var owuiAppServicePlanName = '${baseNameDash}-owui-${owuiAppServicePlanSku.name}-asp-${instanceNumber}'

// Storage Accounts (no dashes, max 24 chars)
var storageAccountName = take('${baseNameNoDash}sa${instanceNumber}', 24)           // krcaidevsa01

// Container Registry (no dashes, max 50 chars)
var acrName = take('${baseNameNoDash}acr${instanceNumber}', 50)            // krcaidevacr01

// Cognitive Services
var searchServiceName = '${baseNameDash}-search-${instanceNumber}'         // krc-ai-dev-search-01
var docIntelligenceName = '${baseNameDash}-docitg-${instanceNumber}'       // krc-ai-dev-docitg-01
var openAIName = '${baseNameDash}-openai-${instanceNumber}'                // krc-ai-dev-openai-01

// PostgreSQL
var postgresName = '${baseNameDash}-pgsqlfx-${instanceNumber}'             // krc-ai-dev-pgsqlfx-01

// Virtual Machines
var vmNames = {
  vm01: '${baseNameDash}-linux-vm01'                                       // krc-ai-dev-linux-vm01
  vm02: '${baseNameDash}-linux-vm02'                                       // krc-ai-dev-linux-vm02
}

// Public IPs
var pipNames = {
  pip01: '${baseNameDash}-pip-01'                                          // krc-ai-dev-pip-01
  pip02: '${baseNameDash}-pip-02'                                          // krc-ai-dev-pip-02
}

// Managed Identity
var acrManagedIdentityName = '${baseNameDash}-acr-mi-${instanceNumber}'    // krc-ai-dev-acr-mi-01

// Private Endpoints
var privateEndpointNames = {
  acr: '${acrName}-pe'
  redis: '${redisName}-pe'
  search: '${searchServiceName}-pe'
  docIntelligence: '${docIntelligenceName}-pe'
  openai: '${openAIName}-pe'
  owui: '${owuiAppServiceName}-pe'
  storageBlob: '${storageAccountName}-blob-pe'
  storageFile: '${storageAccountName}-file-pe'
  storageQueue: '${storageAccountName}-queue-pe'
  storageTable: '${storageAccountName}-table-pe'
}

// Private DNS Zones (Azure 표준 이름 - 수정 불필요)
var privateDnsZoneNames = {
  acr: 'privatelink.azurecr.io'
  openai: 'privatelink.openai.azure.com'
  websites: 'privatelink.azurewebsites.net'
  search: 'privatelink.search.windows.net'
  blob: 'privatelink.blob.core.windows.net'
  file: 'privatelink.file.core.windows.net'
  queue: 'privatelink.queue.core.windows.net'
  table: 'privatelink.table.core.windows.net'
  redis: 'privatelink.redis.cache.windows.net'
  cognitiveServices: 'privatelink.cognitiveservices.azure.com'
  postgres: 'privatelink.postgres.database.azure.com'
}

// ============================================================================
// COMPUTED REFERENCES - 리소스 참조용 ID
// ============================================================================

var acrManagedIdentityId = '/subscriptions/${subscriptionId}/resourcegroups/${resourceGroupName}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${acrManagedIdentityName}'

// 외부 DNS Zone (Hub) 또는 로컬 DNS Zone
var postgresDnsZoneId = useExternalDnsZones && !empty(externalPostgresDnsZoneId)
  ? externalPostgresDnsZoneId
  : '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/privateDnsZones/${privateDnsZoneNames.postgres}'

// ============================================================================
// IP RULES - 네트워크 규칙용 IP 목록 변환
// ============================================================================

// ACR용 IP 규칙 (action 필요)
var allowedIpRulesAcr = [for ip in allowedIps: {
  action: 'Allow'
  value: ip
}]

// Search용 IP 규칙 (value만)
var allowedIpRulesSearch = [for ip in allowedIps: {
  value: ip
}]

// ============================================================================
// COMMON TAGS - 모든 리소스에 적용
// ============================================================================

var commonTags = {
  Environment: environmentDisplayName
  'Project Name': projectDisplayName
  ManagedBy: 'Bicep'
  DeployedAt: utcNow('yyyy-MM-dd')
}

// ============================================================================
// RESOURCES START
// ============================================================================

// ----------------------------------------------------------------------------
// Managed Identity (ACR Pull용)
// ----------------------------------------------------------------------------
resource managedIdentity_acr 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: acrManagedIdentityName
  location: location
  tags: commonTags
}

// ----------------------------------------------------------------------------
// Virtual Network
// ----------------------------------------------------------------------------
resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: vnetName
  location: location
  tags: commonTags
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressSpace]
    }
    subnets: [
      {
        name: 'vm-subnet'
        properties: {
          addressPrefix: subnetCidrs.vm
          networkSecurityGroup: { id: nsg_vm.id }
        }
      }
      {
        name: 'ap-subnet'
        properties: {
          addressPrefix: subnetCidrs.ap
          networkSecurityGroup: { id: nsg_ap.id }
          delegations: [
            {
              name: 'Microsoft.Web.serverFarms'
              properties: { serviceName: 'Microsoft.Web/serverFarms' }
            }
          ]
        }
      }
      {
        name: 'pe-subnet'
        properties: {
          addressPrefix: subnetCidrs.pe
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'pgsql-subnet'
        properties: {
          addressPrefix: subnetCidrs.pgsql
          delegations: [
            {
              name: 'Microsoft.DBforPostgreSQL.flexibleServers'
              properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
            }
          ]
        }
      }
      {
        name: 'etc-subnet'
        properties: {
          addressPrefix: subnetCidrs.etc
          networkSecurityGroup: { id: nsg_etc.id }
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Network Security Groups
// ----------------------------------------------------------------------------
resource nsg_vm 'Microsoft.Network/networkSecurityGroups@2024-01-01' = {
  name: nsgNames.vm
  location: location
  tags: commonTags
  properties: {
    securityRules: [
      {
        name: 'AllowSSHFromAllowedIPs'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '22'
          sourceAddressPrefixes: allowedIps
          destinationAddressPrefixes: [vmPrivateIps.vm01, vmPrivateIps.vm02]
          access: 'Allow'
          priority: 100
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowAppServiceInbound'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '8000-8999'
          sourceAddressPrefix: 'AppService.${location == 'koreacentral' ? 'KoreaCentral' : location}'
          destinationAddressPrefixes: [vmPrivateIps.vm01, vmPrivateIps.vm02]
          access: 'Allow'
          priority: 110
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowVMtoPostgreSQL'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '5432'
          sourceAddressPrefixes: [vmPrivateIps.vm01, vmPrivateIps.vm02]
          destinationAddressPrefix: subnetCidrs.pgsql
          access: 'Allow'
          priority: 100
          direction: 'Outbound'
        }
      }
      {
        name: 'AllowVMtoRedis'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '6379'
          sourceAddressPrefixes: [vmPrivateIps.vm01, vmPrivateIps.vm02]
          destinationAddressPrefix: subnetCidrs.pe
          access: 'Allow'
          priority: 110
          direction: 'Outbound'
        }
      }
    ]
  }
}

resource nsg_ap 'Microsoft.Network/networkSecurityGroups@2024-01-01' = {
  name: nsgNames.ap
  location: location
  tags: commonTags
  properties: {
    securityRules: [
      {
        name: 'AllowApToVM'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '8000-8999'
          sourceAddressPrefix: 'AppService.${location == 'koreacentral' ? 'KoreaCentral' : location}'
          destinationAddressPrefixes: [vmPrivateIps.vm01, vmPrivateIps.vm02]
          access: 'Allow'
          priority: 100
          direction: 'Outbound'
        }
      }
    ]
  }
}

resource nsg_etc 'Microsoft.Network/networkSecurityGroups@2024-01-01' = {
  name: nsgNames.etc
  location: location
  tags: commonTags
  properties: {
    securityRules: []
  }
}

// ----------------------------------------------------------------------------
// Private DNS Zones
// ----------------------------------------------------------------------------
resource privateDnsZone_postgres 'Microsoft.Network/privateDnsZones@2024-06-01' = if (!useExternalDnsZones) {
  name: privateDnsZoneNames.postgres
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_acr 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneNames.acr
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_openai 'Microsoft.Network/privateDnsZones@2024-06-01' = if (deployOpenAI) {
  name: privateDnsZoneNames.openai
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_websites 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneNames.websites
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_search 'Microsoft.Network/privateDnsZones@2024-06-01' = if (deploySearch) {
  name: privateDnsZoneNames.search
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_blob 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneNames.blob
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_file 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneNames.file
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_queue 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneNames.queue
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_table 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneNames.table
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_redis 'Microsoft.Network/privateDnsZones@2024-06-01' = if (deployRedis) {
  name: privateDnsZoneNames.redis
  location: 'global'
  tags: commonTags
}

resource privateDnsZone_cognitiveServices 'Microsoft.Network/privateDnsZones@2024-06-01' = if (deployDocIntelligence) {
  name: privateDnsZoneNames.cognitiveServices
  location: 'global'
  tags: commonTags
}

// Private DNS Zone - VNet Links
resource dnsLink_postgres 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!useExternalDnsZones) {
  parent: privateDnsZone_postgres
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_acr 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone_acr
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_websites 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone_websites
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_blob 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone_blob
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_file 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone_file
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_queue 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone_queue
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_table 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone_table
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_search 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (deploySearch) {
  parent: privateDnsZone_search
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_openai 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (deployOpenAI) {
  parent: privateDnsZone_openai
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_redis 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (deployRedis) {
  parent: privateDnsZone_redis
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource dnsLink_cognitiveServices 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (deployDocIntelligence) {
  parent: privateDnsZone_cognitiveServices
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

// ----------------------------------------------------------------------------
// Redis Cache
// ----------------------------------------------------------------------------
resource redis 'Microsoft.Cache/Redis@2024-03-01' = if (deployRedis) {
  name: redisName
  location: location
  tags: commonTags
  properties: {
    redisVersion: '6.0'
    sku: redisSku
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    redisConfiguration: {
      'aad-enabled': 'true'
      'maxmemory-reserved': '299'
      'maxfragmentationmemory-reserved': '299'
      'maxmemory-delta': '299'
    }
  }
}

// Redis Private Endpoint
resource redis_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = if (deployRedis) {
  name: privateEndpointNames.redis
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.redis
        properties: {
          privateLinkServiceId: redis.id
          groupIds: ['redisCache']
        }
      }
    ]
  }
}

resource redis_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = if (deployRedis) {
  parent: redis_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis'
        properties: {
          privateDnsZoneId: privateDnsZone_redis.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Container Registry
// ----------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: commonTags
  sku: { name: acrSku }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity_acr.id}': {}
    }
  }
  properties: {
    adminUserEnabled: false
    networkRuleSet: {
      defaultAction: 'Deny'
      ipRules: allowedIpRulesAcr
    }
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
    zoneRedundancy: acrSku == 'Premium' ? 'Enabled' : 'Disabled'
  }
}

// ACR Private Endpoint
resource acr_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointNames.acr
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.acr
        properties: {
          privateLinkServiceId: acr.id
          groupIds: ['registry']
        }
      }
    ]
  }
}

resource acr_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: acr_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'acr'
        properties: {
          privateDnsZoneId: privateDnsZone_acr.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Storage Account
// ----------------------------------------------------------------------------
resource storageAccount_main 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  tags: commonTags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: allowedIpRulesSearch
    }
  }
}

// Storage Private Endpoints
resource storage_blob_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointNames.storageBlob
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.storageBlob
        properties: {
          privateLinkServiceId: storageAccount_main.id
          groupIds: ['blob']
        }
      }
    ]
  }
}

resource storage_blob_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: storage_blob_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: privateDnsZone_blob.id
        }
      }
    ]
  }
}

resource storage_file_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointNames.storageFile
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.storageFile
        properties: {
          privateLinkServiceId: storageAccount_main.id
          groupIds: ['file']
        }
      }
    ]
  }
}

resource storage_file_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: storage_file_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'file'
        properties: {
          privateDnsZoneId: privateDnsZone_file.id
        }
      }
    ]
  }
}

resource storage_queue_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointNames.storageQueue
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.storageQueue
        properties: {
          privateLinkServiceId: storageAccount_main.id
          groupIds: ['queue']
        }
      }
    ]
  }
}

resource storage_queue_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: storage_queue_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'queue'
        properties: {
          privateDnsZoneId: privateDnsZone_queue.id
        }
      }
    ]
  }
}

resource storage_table_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointNames.storageTable
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.storageTable
        properties: {
          privateLinkServiceId: storageAccount_main.id
          groupIds: ['table']
        }
      }
    ]
  }
}

resource storage_table_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: storage_table_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'table'
        properties: {
          privateDnsZoneId: privateDnsZone_table.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Azure AI Search
// ----------------------------------------------------------------------------
resource search 'Microsoft.Search/searchServices@2024-03-01-preview' = if (deploySearch) {
  name: searchServiceName
  location: location
  tags: commonTags
  sku: { name: searchSku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    publicNetworkAccess: 'Enabled'
    networkRuleSet: {
      ipRules: allowedIpRulesSearch
      bypass: 'AzureServices'
    }
    disableLocalAuth: false
    authOptions: {
      apiKeyOnly: {}
    }
    semanticSearch: 'standard'
  }
}

// Search Private Endpoint
resource search_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = if (deploySearch) {
  name: privateEndpointNames.search
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.search
        properties: {
          privateLinkServiceId: search.id
          groupIds: ['searchService']
        }
      }
    ]
  }
}

resource search_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = if (deploySearch) {
  parent: search_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'search'
        properties: {
          privateDnsZoneId: privateDnsZone_search.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Azure OpenAI
// ----------------------------------------------------------------------------
resource openai 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = if (deployOpenAI) {
  name: openAIName
  location: location
  tags: commonTags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openAIName
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
    }
  }
}

// OpenAI Model Deployments
resource openai_deployments 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = [for model in openAIModels: if (deployOpenAI) {
  parent: openai
  name: model.name
  sku: {
    name: model.skuName
    capacity: model.capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: model.modelName
      version: model.version
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}]

// OpenAI Private Endpoint
resource openai_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = if (deployOpenAI) {
  name: privateEndpointNames.openai
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.openai
        properties: {
          privateLinkServiceId: openai.id
          groupIds: ['account']
        }
      }
    ]
  }
}

resource openai_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = if (deployOpenAI) {
  parent: openai_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'openai'
        properties: {
          privateDnsZoneId: privateDnsZone_openai.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Document Intelligence
// ----------------------------------------------------------------------------
resource docIntelligence 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = if (deployDocIntelligence) {
  name: docIntelligenceName
  location: location
  tags: commonTags
  kind: 'FormRecognizer'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: docIntelligenceName
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
    }
  }
}

// Document Intelligence Private Endpoint
resource docIntelligence_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = if (deployDocIntelligence) {
  name: privateEndpointNames.docIntelligence
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.docIntelligence
        properties: {
          privateLinkServiceId: docIntelligence.id
          groupIds: ['account']
        }
      }
    ]
  }
}

resource docIntelligence_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = if (deployDocIntelligence) {
  parent: docIntelligence_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cognitiveservices'
        properties: {
          privateDnsZoneId: privateDnsZone_cognitiveServices.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// PostgreSQL Flexible Server
// ----------------------------------------------------------------------------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: postgresName
  location: location
  tags: commonTags
  sku: {
    name: postgresSku.name
    tier: postgresSku.tier
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: postgresSku.storageSizeGB
      autoGrow: 'Enabled'
    }
    network: {
      publicNetworkAccess: 'Disabled'
      delegatedSubnetResourceId: '${vnet.id}/subnets/pgsql-subnet'
      privateDnsZoneArmResourceId: useExternalDnsZones ? externalPostgresDnsZoneId : privateDnsZone_postgres.id
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: environment == 'prd' ? 'ZoneRedundant' : 'Disabled'
    }
    dataEncryption: {
      type: 'SystemManaged'
    }
  }
  dependsOn: [
    dnsLink_postgres
  ]
}

// ----------------------------------------------------------------------------
// App Service Plan
// ----------------------------------------------------------------------------
resource appServicePlan_owui 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: owuiAppServicePlanName
  location: location
  tags: commonTags
  kind: 'linux'
  sku: {
    name: owuiAppServicePlanSku.name
    tier: owuiAppServicePlanSku.tier
    capacity: owuiAppServicePlanSku.capacity
  }
  properties: {
    reserved: true
  }
}

// ----------------------------------------------------------------------------
// App Service (OWUI)
// ----------------------------------------------------------------------------
resource appService_owui 'Microsoft.Web/sites@2023-01-01' = {
  name: owuiAppServiceName
  location: location
  tags: commonTags
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity_acr.id}': {}
    }
  }
  properties: {
    serverFarmId: appServicePlan_owui.id
    httpsOnly: true
    virtualNetworkSubnetId: '${vnet.id}/subnets/ap-subnet'
    vnetRouteAllEnabled: true
    siteConfig: {
      linuxFxVersion: 'sitecontainers'
      alwaysOn: true
      acrUseManagedIdentityCreds: true
      acrUserManagedIdentityID: managedIdentity_acr.properties.clientId
      ipSecurityRestrictions: concat(
        [for (ip, i) in allowedIps: {
          ipAddress: '${ip}/32'
          action: 'Allow'
          priority: 100 + i
          name: 'AllowedIP-${i}'
        }],
        [
          {
            ipAddress: '${vmPrivateIps.vm01}/32,${vmPrivateIps.vm02}/32'
            action: 'Allow'
            priority: 200
            name: 'AllowVMs'
          }
          {
            ipAddress: subnetCidrs.pe
            action: 'Allow'
            priority: 210
            name: 'AllowPrivateEndpoint'
          }
          {
            ipAddress: 'Any'
            action: 'Deny'
            priority: 2147483647
            name: 'DenyAll'
          }
        ]
      )
      ipSecurityRestrictionsDefaultAction: 'Deny'
    }
  }
}

// OWUI Private Endpoint
resource owui_pe 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: privateEndpointNames.owui
  location: location
  tags: commonTags
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: privateEndpointNames.owui
        properties: {
          privateLinkServiceId: appService_owui.id
          groupIds: ['sites']
        }
      }
    ]
  }
}

resource owui_pe_dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: owui_pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'websites'
        properties: {
          privateDnsZoneId: privateDnsZone_websites.id
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Public IPs (for VMs)
// ----------------------------------------------------------------------------
resource pip01 'Microsoft.Network/publicIPAddresses@2024-01-01' = if (deployVMs) {
  name: pipNames.pip01
  location: location
  tags: commonTags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  zones: ['1']
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource pip02 'Microsoft.Network/publicIPAddresses@2024-01-01' = if (deployVMs) {
  name: pipNames.pip02
  location: location
  tags: commonTags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  zones: ['1']
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

// ----------------------------------------------------------------------------
// Network Interfaces (for VMs)
// ----------------------------------------------------------------------------
resource nic01 'Microsoft.Network/networkInterfaces@2024-01-01' = if (deployVMs) {
  name: '${vmNames.vm01}-nic'
  location: location
  tags: commonTags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAddress: vmPrivateIps.vm01
          privateIPAllocationMethod: 'Static'
          subnet: { id: '${vnet.id}/subnets/vm-subnet' }
          publicIPAddress: { id: pip01.id }
        }
      }
    ]
  }
}

resource nic02 'Microsoft.Network/networkInterfaces@2024-01-01' = if (deployVMs) {
  name: '${vmNames.vm02}-nic'
  location: location
  tags: commonTags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAddress: vmPrivateIps.vm02
          privateIPAllocationMethod: 'Static'
          subnet: { id: '${vnet.id}/subnets/vm-subnet' }
          publicIPAddress: { id: pip02.id }
        }
      }
    ]
  }
}

// ----------------------------------------------------------------------------
// Virtual Machines
// ----------------------------------------------------------------------------
resource vm01 'Microsoft.Compute/virtualMachines@2024-03-01' = if (deployVMs) {
  name: vmNames.vm01
  location: location
  tags: commonTags
  zones: ['1']
  properties: {
    hardwareProfile: {
      vmSize: 'Standard_D4s_v3'
    }
    osProfile: {
      computerName: vmNames.vm01
      adminUsername: vmAdminUsername
      adminPassword: empty(vmSshPublicKey) ? vmAdminPassword : null
      linuxConfiguration: {
        disablePasswordAuthentication: !empty(vmSshPublicKey)
        ssh: !empty(vmSshPublicKey) ? {
          publicKeys: [
            {
              path: '/home/${vmAdminUsername}/.ssh/authorized_keys'
              keyData: vmSshPublicKey
            }
          ]
        } : null
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        { id: nic01.id }
      ]
    }
  }
}

resource vm02 'Microsoft.Compute/virtualMachines@2024-03-01' = if (deployVMs) {
  name: vmNames.vm02
  location: location
  tags: commonTags
  zones: ['1']
  properties: {
    hardwareProfile: {
      vmSize: 'Standard_D4s_v3'
    }
    osProfile: {
      computerName: vmNames.vm02
      adminUsername: vmAdminUsername
      adminPassword: empty(vmSshPublicKey) ? vmAdminPassword : null
      linuxConfiguration: {
        disablePasswordAuthentication: !empty(vmSshPublicKey)
        ssh: !empty(vmSshPublicKey) ? {
          publicKeys: [
            {
              path: '/home/${vmAdminUsername}/.ssh/authorized_keys'
              keyData: vmSshPublicKey
            }
          ]
        } : null
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        { id: nic02.id }
      ]
    }
  }
}

// ----------------------------------------------------------------------------
// VNet Peering (Optional)
// ----------------------------------------------------------------------------
resource vnetPeering 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-01-01' = if (deployVnetPeering && !empty(peeringTargetVnetId)) {
  parent: vnet
  name: 'peering-to-remote'
  properties: {
    remoteVirtualNetwork: { id: peeringTargetVnetId }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: false
    useRemoteGateways: false
  }
}

// ============================================================================
// OUTPUTS
// ============================================================================

output resourceGroupName string = resourceGroupName
output vnetName string = vnet.name
output vnetId string = vnet.id

output postgresServerName string = postgres.name
output postgresFQDN string = postgres.properties.fullyQualifiedDomainName

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer

output owuiAppServiceName string = appService_owui.name
output owuiDefaultHostName string = appService_owui.properties.defaultHostName

output storageAccountName string = storageAccount_main.name

output redisName string = deployRedis ? redis.name : ''
output redisHostName string = deployRedis ? redis.properties.hostName : ''

output searchServiceName string = deploySearch ? search.name : ''

output openAIName string = deployOpenAI ? openai.name : ''
output openAIEndpoint string = deployOpenAI ? openai.properties.endpoint : ''

output docIntelligenceName string = deployDocIntelligence ? docIntelligence.name : ''

output managedIdentityClientId string = managedIdentity_acr.properties.clientId
output managedIdentityPrincipalId string = managedIdentity_acr.properties.principalId

output vm01PublicIP string = deployVMs ? pip01.properties.ipAddress : ''
output vm02PublicIP string = deployVMs ? pip02.properties.ipAddress : ''
