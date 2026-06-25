// ============================================================================
// Common Naming Parameters
// ============================================================================
// Naming Convention: {region}-{project}-{environment}-{resource}-{instance}
// Example: krc-ai-dev-rds-01
// ============================================================================

@description('Region code (e.g., krc = Korea Central, eus2 = East US 2)')
param regionCode string = 'krc'

@description('Project name')
param projectName string = 'ai'

@description('Environment (e.g., dev, stg, prd)')
param environment string = 'dev'

@description('Company/Tenant prefix for VNet resources')
param companyPrefix string = 'acme'

@description('Azure subscription ID')
param subscriptionId string = '88b17567-9dae-4a5f-9d02-9adec345618b'

@description('Location for resources')
param location string = 'koreacentral'

@description('Location display name')
param locationDisplayName string = 'Korea Central'

// Tags
var commonTags = {
  Environment: environment
  'Project Name': '${toUpper(projectName)} PoC'
}

// ============================================================================
// Network Configuration
// ============================================================================

// Allowed Office IPs for firewall rules
var allowedOfficeIps = [
  '211.215.58.26'
  '222.234.227.131'
  '222.234.227.132'
  '222.234.227.133'
  '222.234.227.134'
  '222.234.227.135'
  '222.234.227.136'
]

// VM Private IPs (Static allocation)
var vmPrivateIps = {
  vm01: '10.100.0.4'
  vm02: '10.100.0.5'
}

// Subnet CIDR ranges
var subnetCidrs = {
  vm: '10.100.0.0/27'
  ap: '10.100.1.0/26'
  func: '10.100.2.0/27'
  pe: '10.100.3.0/27'
  pgsql: '10.100.4.0/27'
  etc: '10.100.5.0/27'
}

// IP Rules for ACR networkRuleSet (requires action and value properties)
var allowedOfficeIpRulesAcr = [for ip in allowedOfficeIps: {
  action: 'Allow'
  value: ip
}]

// IP Rules for Search networkRuleSet (requires only value property)
var allowedOfficeIpRulesSearch = [for ip in allowedOfficeIps: {
  value: ip
}]

// ============================================================================
// Naming Variables (derived from common parameters)
// ============================================================================

// Base naming patterns
var baseNameDash = '${regionCode}-${projectName}-${environment}'        // krc-ai-dev
var baseNameNoDash = '${regionCode}${projectName}${environment}'        // krcaidev
var vnetBaseName = '${companyPrefix}-${projectName}-${environment}'     // acme-ai-dev

// Resource Group
var resourceGroupName = '${companyPrefix}-${projectName}-${environment}-${regionCode}-01-rg' // acme-ai-dev-krc-01-rg

// Managed Identity Resource ID
var acrManagedIdentityId = '/subscriptions/${subscriptionId}/resourcegroups/${resourceGroupName}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${acrManagedIdentityName}'

// ============================================================================
// Resource Names
// ============================================================================

// Redis
var redisName = '${baseNameDash}-rds-01'                                // krc-ai-dev-rds-01

// App Services
var owuiAppServiceName = '${baseNameDash}-owui-as-01'                   // krc-ai-dev-owui-as-01
var msdsFunctionName = '${baseNameDash}-msds-func-01'                   // krc-ai-dev-msds-func-01

// App Service Plans
var msdsAppServicePlanName = '${baseNameDash}-msds-p1v3-asp-01'         // krc-ai-dev-msds-p1v3-asp-01
var owuiAppServicePlanName = '${baseNameDash}-owui-p0v3-asp-01'         // krc-ai-dev-owui-p0v3-asp-01

// Storage Accounts (no dashes allowed)
var storageAccountName = '${baseNameNoDash}sa01'                        // krcaidevsa01
var msdsStorageAccountName = '${baseNameNoDash}msdssa01'                // krcaidevmsdssa01

// Container Registry (no dashes allowed)
var acrName = '${baseNameNoDash}acr01'                                  // krcaidevacr01

// Search Service
var searchServiceName = '${baseNameDash}-search-01'                     // krc-ai-dev-search-01

// Cognitive Services
var docIntelligenceName = '${baseNameDash}-docitg-01'                   // krc-ai-dev-docitg-01
var openAIName = '${baseNameDash}-openai-01'                            // krc-ai-dev-openai-01

// PostgreSQL
var postgresName = '${baseNameDash}-pgsqlfx-01'                         // krc-ai-dev-pgsqlfx-01

// Virtual Machines
var vm01Name = '${baseNameDash}-dev-linux-vm01'                         // krc-ai-dev-dev-linux-vm01
var vm02Name = '${baseNameDash}-dev-linux-vm02'                         // krc-ai-dev-dev-linux-vm02

// Network Interfaces (with random suffix from Azure)
var nic01Name = '${baseNameDash}-dev-linux-vm01239_z1'                  // krc-ai-dev-dev-linux-vm01239_z1
var nic02Name = '${baseNameDash}-dev-linux-vm02716_z1'                  // krc-ai-dev-dev-linux-vm02716_z1

// Public IPs
var pip01Name = '${baseNameDash}-dev-pip-01'                            // krc-ai-dev-dev-pip-01
var pip02Name = '${baseNameDash}-dev-pip-02'                            // krc-ai-dev-dev-pip-02

// Virtual Network
var vnetName = '${vnetBaseName}-${regionCode}-01-vnet'                  // acme-ai-dev-krc-01-vnet

// Network Security Groups
var apSubnetNsgName = '${vnetName}-ap-subnet-nsg'                       // acme-ai-dev-krc-01-vnet-ap-subnet-nsg
var vmSubnetNsgName = '${vnetName}-vm-subnet-nsg'                       // acme-ai-dev-krc-01-vnet-vm-subnet-nsg
var etcSubnetNsgName = '${vnetName}-etc-subnet-nsg'                     // acme-ai-dev-krc-01-vnet-etc-subnet-nsg
var funcSubnetNsgName = '${vnetName}-func-subnet-nsg'                   // acme-ai-dev-krc-01-vnet-func-subnet-nsg

// Managed Identity
var acrManagedIdentityName = '${baseNameDash}-acr-mi-01'                // krc-ai-dev-acr-mi-01

// Private Endpoints
var acrPrivateEndpointName = '${acrName}-pri-ed'                        // krcaidevacr01-pri-ed
var redisPrivateEndpointName = '${redisName}-pri-ed'                    // krc-ai-dev-rds-01-pri-ed
var searchPrivateEndpointName = '${searchServiceName}-pri-ed'           // krc-ai-dev-search-01-pri-ed
var docIntelligencePrivateEndpointName = '${docIntelligenceName}-pri-ed'// krc-ai-dev-docitg-01-pri-ed
var openAIPrivateEndpointName = '${openAIName}-pri-ed'                  // krc-ai-dev-openai-01-pri-ed
var owuiPrivateEndpointName = '${owuiAppServiceName}-pri-ed'            // krc-ai-dev-owui-as-01-pri-ed
var msdsFuncPrivateEndpointName = '${msdsFunctionName}-pri-ed'          // krc-ai-dev-msds-func-01-pri-ed
var msdsStoragePrivateEndpointName = '${msdsStorageAccountName}-pri-ed' // krcaidevmsdssa01-pri-ed
var storagePrivateEndpointBlobName = '${storageAccountName}-pri-ed-${storageAccountName}-blob-private-endpoint'
var storagePrivateEndpointFileName = '${storageAccountName}-pri-ed-${storageAccountName}-file-private-endpoint'
var storagePrivateEndpointQueueName = '${storageAccountName}-pri-ed-${storageAccountName}-queue-private-endpoint'
var storagePrivateEndpointTableName = '${storageAccountName}-pri-ed-${storageAccountName}-table-private-endpoint'

// Private DNS Zones (Azure standard names)
var privateDnsZoneAcr = 'privatelink.azurecr.io'
var privateDnsZoneOpenAI = 'privatelink.openai.azure.com'
var privateDnsZoneWebsites = 'privatelink.azurewebsites.net'
var privateDnsZoneSearch = 'privatelink.search.windows.net'
var privateDnsZoneBlob = 'privatelink.blob.core.windows.net'
var privateDnsZoneFile = 'privatelink.file.core.windows.net'
var privateDnsZoneQueue = 'privatelink.queue.core.windows.net'
var privateDnsZoneTable = 'privatelink.table.core.windows.net'
var privateDnsZoneRedis = 'privatelink.redis.cache.windows.net'
var privateDnsZoneCognitiveServices = 'privatelink.cognitiveservices.azure.com'

// External Resources
var postgresPrivateDnsZoneId = '/subscriptions/${subscriptionId}/resourceGroups/hub-rg/providers/Microsoft.Network/privateDnsZones/privatelink.postgres.database.azure.com'
var eus2VnetId = '/subscriptions/${subscriptionId}/resourceGroups/${vnetBaseName}-eus2-01-rg/providers/Microsoft.Network/virtualNetworks/${vnetBaseName}-eus2-01-vnet'

// ============================================================================
// Standardized Resource Name Parameters
// ============================================================================
// Naming: {resourceType}_{purpose}_name
// ============================================================================

// Cache
param redis_main_name string = redisName

// App Services
param appService_owui_name string = owuiAppServiceName
param function_msds_name string = msdsFunctionName

// App Service Plans
param appServicePlan_owui_name string = owuiAppServicePlanName
param appServicePlan_msds_name string = msdsAppServicePlanName

// Storage Accounts
param storageAccount_main_name string = storageAccountName
param storageAccount_msds_name string = msdsStorageAccountName

// Container Registry
param acr_main_name string = acrName

// Search
param search_main_name string = searchServiceName

// Cognitive Services
param cognitiveServices_docIntelligence_name string = docIntelligenceName
param cognitiveServices_openai_name string = openAIName

// Database
param postgres_main_name string = postgresName

// Virtual Machines
param vm_linux01_name string = vm01Name
param vm_linux02_name string = vm02Name

// Network Interfaces
param nic_linux01_name string = nic01Name
param nic_linux02_name string = nic02Name

// Public IPs
param pip_01_name string = pip01Name
param pip_02_name string = pip02Name

// Virtual Network
param vnet_main_name string = vnetName

// Network Security Groups
param nsg_apSubnet_name string = apSubnetNsgName
param nsg_vmSubnet_name string = vmSubnetNsgName
param nsg_etcSubnet_name string = etcSubnetNsgName
param nsg_funcSubnet_name string = funcSubnetNsgName

// Managed Identity
param managedIdentity_acr_name string = acrManagedIdentityName

// Private Endpoints
param privateEndpoint_acr_name string = acrPrivateEndpointName
param privateEndpoint_redis_name string = redisPrivateEndpointName
param privateEndpoint_search_name string = searchPrivateEndpointName
param privateEndpoint_docIntelligence_name string = docIntelligencePrivateEndpointName
param privateEndpoint_openai_name string = openAIPrivateEndpointName
param privateEndpoint_owui_name string = owuiPrivateEndpointName
param privateEndpoint_msdsFunc_name string = msdsFuncPrivateEndpointName
param privateEndpoint_msdsStorage_name string = msdsStoragePrivateEndpointName
param privateEndpoint_storageBlob_name string = storagePrivateEndpointBlobName
param privateEndpoint_storageFile_name string = storagePrivateEndpointFileName
param privateEndpoint_storageQueue_name string = storagePrivateEndpointQueueName
param privateEndpoint_storageTable_name string = storagePrivateEndpointTableName

// Private DNS Zones
param privateDnsZone_acr_name string = privateDnsZoneAcr
param privateDnsZone_openai_name string = privateDnsZoneOpenAI
param privateDnsZone_websites_name string = privateDnsZoneWebsites
param privateDnsZone_search_name string = privateDnsZoneSearch
param privateDnsZone_blob_name string = privateDnsZoneBlob
param privateDnsZone_file_name string = privateDnsZoneFile
param privateDnsZone_queue_name string = privateDnsZoneQueue
param privateDnsZone_table_name string = privateDnsZoneTable
param privateDnsZone_redis_name string = privateDnsZoneRedis
param privateDnsZone_cognitiveServices_name string = privateDnsZoneCognitiveServices

// External Resource IDs
param external_privateDnsZone_postgres_id string = postgresPrivateDnsZoneId
param external_vnet_eus2_id string = eus2VnetId

// ============================================================================
// Legacy Parameter Mappings (for backward compatibility during migration)
// TODO: Update resource references to use new param names, then remove this section
// ============================================================================
var Redis_krc_ai_dev_rds_01_name = redis_main_name
var sites_krc_ai_dev_owui_as_01_name = appService_owui_name
var sites_krc_ai_dev_msds_func_01_name = function_msds_name
var storageAccounts_krcaidevsa01_name = storageAccount_main_name
var storageAccounts_krcaidevmsdssa01_name = storageAccount_msds_name
var registries_krcaidevacr01_name = acr_main_name
var searchServices_krc_ai_dev_search_01_name = search_main_name
var serverfarms_krc_ai_dev_msds_p1v3_asp_01_name = appServicePlan_msds_name
var serverfarms_krc_ai_dev_owui_p0v3_asp_01_name = appServicePlan_owui_name
var privateEndpoints_krcaidevacr01_pri_ed_name = privateEndpoint_acr_name
var privateDnsZones_privatelink_azurecr_io_name = privateDnsZone_acr_name
var accounts_krc_ai_dev_docitg_01_name = cognitiveServices_docIntelligence_name
var accounts_krc_ai_dev_openai_01_name = cognitiveServices_openai_name
var publicIPAddresses_krc_ai_dev_dev_pip_01_name = pip_01_name
var publicIPAddresses_krc_ai_dev_dev_pip_02_name = pip_02_name
var virtualNetworks_acme_ai_dev_krc_01_vnet_name = vnet_main_name
var privateEndpoints_krcaidevmsdssa01_pri_ed_name = privateEndpoint_msdsStorage_name
var virtualMachines_krc_ai_dev_dev_linux_vm01_name = vm_linux01_name
var virtualMachines_krc_ai_dev_dev_linux_vm02_name = vm_linux02_name
var privateEndpoints_krc_ai_dev_rds_01_pri_ed_name = privateEndpoint_redis_name
var privateDnsZones_privatelink_openai_azure_com_name = privateDnsZone_openai_name
var privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name = privateEndpoint_docIntelligence_name
var privateEndpoints_krc_ai_dev_openai_01_pri_ed_name = privateEndpoint_openai_name
var privateEndpoints_krc_ai_dev_search_01_pri_ed_name = privateEndpoint_search_name
var flexibleServers_krc_ai_dev_pgsqlfx_01_name = postgres_main_name
var privateDnsZones_privatelink_azurewebsites_net_name = privateDnsZone_websites_name
var privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name = privateEndpoint_owui_name
var privateDnsZones_privatelink_search_windows_net_name = privateDnsZone_search_name
var privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name = privateEndpoint_msdsFunc_name
var networkInterfaces_krc_ai_dev_dev_linux_vm01239_z1_name = nic_linux01_name
var networkInterfaces_krc_ai_dev_dev_linux_vm02716_z1_name = nic_linux02_name
var privateDnsZones_privatelink_blob_core_windows_net_name = privateDnsZone_blob_name
var privateDnsZones_privatelink_file_core_windows_net_name = privateDnsZone_file_name
var privateDnsZones_privatelink_queue_core_windows_net_name = privateDnsZone_queue_name
var privateDnsZones_privatelink_table_core_windows_net_name = privateDnsZone_table_name
var userAssignedIdentities_krc_ai_dev_acr_mi_01_name = managedIdentity_acr_name
var privateDnsZones_privatelink_redis_cache_windows_net_name = privateDnsZone_redis_name
var privateDnsZones_privatelink_cognitiveservices_azure_com_name = privateDnsZone_cognitiveServices_name
var networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name = nsg_apSubnet_name
var networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name = nsg_vmSubnet_name
var networkSecurityGroups_acme_ai_dev_krc_01_vnet_etc_subnet_nsg_name = nsg_etcSubnet_name
var networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name = nsg_funcSubnet_name
var privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name = privateEndpoint_storageBlob_name
var privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name = privateEndpoint_storageFile_name
var privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name = privateEndpoint_storageQueue_name
var privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name = privateEndpoint_storageTable_name
var privateDnsZones_privatelink_postgres_database_azure_com_externalid = external_privateDnsZone_postgres_id
var virtualNetworks_acme_ai_dev_eus2_01_vnet_externalid = external_vnet_eus2_id

resource Redis_krc_ai_dev_rds_01_name_resource 'Microsoft.Cache/Redis@2024-11-01' = {
  name: Redis_krc_ai_dev_rds_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    redisVersion: '6.0'
    sku: {
      name: 'Standard'
      family: 'C'
      capacity: 2
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    redisConfiguration: {
      'aad-enabled': 'true'
      maxclients: '2000'
      'maxmemory-reserved': '299'
      'maxfragmentationmemory-reserved': '299'
      'maxmemory-delta': '299'
    }
    updateChannel: 'Stable'
    zonalAllocationPolicy: 'Automatic'
    disableAccessKeyAuthentication: false
  }
}

resource registries_krcaidevacr01_name_resource 'Microsoft.ContainerRegistry/registries@2025-05-01-preview' = {
  name: registries_krcaidevacr01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'Premium'
    tier: 'Premium'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${acrManagedIdentityId}': {}
    }
  }
  properties: {
    adminUserEnabled: false
    networkRuleSet: {
      defaultAction: 'Deny'
      ipRules: allowedOfficeIpRulesAcr
    }
    policies: {
      quarantinePolicy: {
        status: 'disabled'
      }
      trustPolicy: {
        type: 'Notary'
        status: 'disabled'
      }
      retentionPolicy: {
        days: 7
        status: 'disabled'
      }
      exportPolicy: {
        status: 'enabled'
      }
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
      softDeletePolicy: {
        retentionDays: 7
        status: 'disabled'
      }
    }
    encryption: {
      status: 'disabled'
    }
    dataEndpointEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
    networkRuleBypassAllowedForTasks: false
    zoneRedundancy: 'Enabled'
    anonymousPullEnabled: false
    metadataSearch: 'Disabled'
    roleAssignmentMode: 'LegacyRegistryPermissions'
    autoGeneratedDomainNameLabelScope: 'Unsecure'
  }
}

resource userAssignedIdentities_krc_ai_dev_acr_mi_01_name_resource 'Microsoft.ManagedIdentity/userAssignedIdentities@2025-01-31-preview' = {
  name: userAssignedIdentities_krc_ai_dev_acr_mi_01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_resource 'Microsoft.Network/networkSecurityGroups@2024-07-01' = {
  name: networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    securityRules: [
      {
        name: 'AllowApToVM'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_AllowApToVM.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '8000-8999'
          sourceAddressPrefix: 'AppService.KoreaCentral'
          access: 'Allow'
          priority: 100
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
        }
      }
      {
        name: 'AllowApToOpenAI'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_AllowApToOpenAI.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          sourceAddressPrefix: 'AppService.KoreaCentral'
          destinationAddressPrefix: '10.110.0.0/24'
          access: 'Allow'
          priority: 110
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: [
            '80'
            '443'
          ]
          sourceAddressPrefixes: []
          destinationAddressPrefixes: []
        }
      }
    ]
  }
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_etc_subnet_nsg_name_resource 'Microsoft.Network/networkSecurityGroups@2024-07-01' = {
  name: networkSecurityGroups_acme_ai_dev_krc_01_vnet_etc_subnet_nsg_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    securityRules: []
  }
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_resource 'Microsoft.Network/networkSecurityGroups@2024-07-01' = {
  name: networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    securityRules: [
      {
        name: 'AllowFuncToOpenAI'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_AllowFuncToOpenAI.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          sourceAddressPrefix: 'AppService.KoreaCentral'
          destinationAddressPrefix: '10.110.0.0/24'
          access: 'Allow'
          priority: 100
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: [
            '80'
            '443'
          ]
          sourceAddressPrefixes: []
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AllowFuncToStorage'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_AllowFuncToStorage.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          sourceAddressPrefix: 'AppService.KoreaCentral'
          destinationAddressPrefix: 'Storage.KoreaCentral'
          access: 'Allow'
          priority: 110
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: [
            '80'
            '443'
            '445'
          ]
          sourceAddressPrefixes: []
          destinationAddressPrefixes: []
        }
      }
    ]
  }
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource 'Microsoft.Network/networkSecurityGroups@2024-07-01' = {
  name: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    securityRules: [
      {
        name: 'AllowVMSShInBound'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVMSShInBound.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          description: 'Local(intenet) to VM SSH Allow'
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '22'
          access: 'Allow'
          priority: 100
          direction: 'Inbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: [
            '211.215.58.26'
            '222.234.227.131'
          ]
          destinationAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
        }
      }
      {
        name: 'AllowVmtoStorageOutBound'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoStorageOutBound.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Storage.KoreaCentral'
          access: 'Allow'
          priority: 110
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: [
            '80'
            '443'
            '445'
          ]
          sourceAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AllowVmtoACROutBound'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoACROutBound.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '8080'
          destinationAddressPrefix: 'AzureContainerRegistry.KoreaCentral'
          access: 'Allow'
          priority: 120
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AllowVMtoPgsqlOutBound'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVMtoPgsqlOutBound.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '5432'
          destinationAddressPrefix: '10.100.4.0/27'
          access: 'Allow'
          priority: 130
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AllowVmtoAISearchOutBound'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoAISearchOutBound.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '8080'
          destinationAddressPrefix: 'AzureCognitiveSearch'
          access: 'Allow'
          priority: 140
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AllowVmtoCognitiveServiceOutBound'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoCognitiveServiceOutBound.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '8080'
          destinationAddressPrefix: 'CognitiveServicesManagement'
          access: 'Allow'
          priority: 150
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AllowVMtoRedis'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVMtoRedis.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '6379'
          destinationAddressPrefix: '10.100.3.0/27'
          access: 'Allow'
          priority: 160
          direction: 'Outbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
          destinationAddressPrefixes: []
        }
      }
      {
        name: 'AlowApToVM01'
        id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AlowApToVM01.id
        type: 'Microsoft.Network/networkSecurityGroups/securityRules'
        properties: {
          protocol: 'TCP'
          sourcePortRange: '*'
          destinationPortRange: '8000-8999'
          sourceAddressPrefix: 'AppService.KoreaCentral'
          access: 'Allow'
          priority: 110
          direction: 'Inbound'
          sourcePortRanges: []
          destinationPortRanges: []
          sourceAddressPrefixes: []
          destinationAddressPrefixes: [
            '10.100.0.4'
            '10.100.0.5'
          ]
        }
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurecr_io_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_azurecr_io_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_azurewebsites_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_azurewebsites_net_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_blob_core_windows_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_blob_core_windows_net_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_cognitiveservices_azure_com_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_cognitiveservices_azure_com_name
  location: 'global'
  tags: {
    Environment: 'PoC'
  }
  properties: {}
}

resource privateDnsZones_privatelink_file_core_windows_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_file_core_windows_net_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_openai_azure_com_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_openai_azure_com_name
  location: 'global'
  tags: {
    Environment: 'PoC'
  }
  properties: {}
}

resource privateDnsZones_privatelink_queue_core_windows_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_queue_core_windows_net_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_redis_cache_windows_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_redis_cache_windows_net_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_search_windows_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_search_windows_net_name
  location: 'global'
  properties: {}
}

resource privateDnsZones_privatelink_table_core_windows_net_name_resource 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZones_privatelink_table_core_windows_net_name
  location: 'global'
  properties: {}
}

resource publicIPAddresses_krc_ai_dev_dev_pip_01_name_resource 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: publicIPAddresses_krc_ai_dev_dev_pip_01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  zones: [
    '1'
  ]
  properties: {
    ipAddress: '20.39.198.106'
    publicIPAddressVersion: 'IPv4'
    publicIPAllocationMethod: 'Static'
    idleTimeoutInMinutes: 4
    ipTags: []
    ddosSettings: {
      protectionMode: 'VirtualNetworkInherited'
    }
  }
}

resource publicIPAddresses_krc_ai_dev_dev_pip_02_name_resource 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: publicIPAddresses_krc_ai_dev_dev_pip_02_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  zones: [
    '1'
  ]
  properties: {
    ipAddress: '40.82.145.28'
    publicIPAddressVersion: 'IPv4'
    publicIPAllocationMethod: 'Static'
    idleTimeoutInMinutes: 4
    ipTags: []
    ddosSettings: {
      protectionMode: 'VirtualNetworkInherited'
    }
  }
}

resource searchServices_krc_ai_dev_search_01_name_resource 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchServices_krc_ai_dev_search_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    endpoint: 'https://${searchServices_krc_ai_dev_search_01_name}.search.windows.net'
    hostingMode: 'Default'
    computeType: 'Default'
    publicNetworkAccess: 'Enabled'
    networkRuleSet: {
      ipRules: allowedOfficeIpRulesSearch
      bypass: 'AzureServices'
    }
    encryptionWithCmk: {
      enforcement: 'Unspecified'
    }
    disableLocalAuth: false
    authOptions: {
      apiKeyOnly: {}
    }
    dataExfiltrationProtections: []
    semanticSearch: 'standard'
    upgradeAvailable: 'notAvailable'
  }
}

resource serverfarms_krc_ai_dev_msds_p1v3_asp_01_name_resource 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: serverfarms_krc_ai_dev_msds_p1v3_asp_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'P1v3'
    tier: 'PremiumV3'
    size: 'P1v3'
    family: 'Pv3'
    capacity: 1
  }
  kind: 'linux'
  properties: {
    perSiteScaling: false
    elasticScaleEnabled: false
    maximumElasticWorkerCount: 1
    isSpot: false
    reserved: true
    isXenon: false
    hyperV: false
    targetWorkerCount: 0
    targetWorkerSizeId: 0
    zoneRedundant: false
    asyncScalingEnabled: false
  }
}

resource serverfarms_krc_ai_dev_owui_p0v3_asp_01_name_resource 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: serverfarms_krc_ai_dev_owui_p0v3_asp_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'P0v3'
    tier: 'Premium0V3'
    size: 'P0v3'
    family: 'Pv3'
    capacity: 8
  }
  kind: 'linux'
  properties: {
    perSiteScaling: false
    elasticScaleEnabled: false
    maximumElasticWorkerCount: 8
    isSpot: false
    reserved: true
    isXenon: false
    hyperV: false
    targetWorkerCount: 0
    targetWorkerSizeId: 0
    zoneRedundant: false
    asyncScalingEnabled: false
  }
}

resource Redis_krc_ai_dev_rds_01_name_Data_Contributor 'Microsoft.Cache/Redis/accessPolicies@2024-11-01' = {
  parent: Redis_krc_ai_dev_rds_01_name_resource
  name: 'Data Contributor'
  properties: {
    permissions: '+@all -@dangerous +cluster|info +cluster|nodes +cluster|slots allkeys'
  }
}

resource Redis_krc_ai_dev_rds_01_name_Data_Owner 'Microsoft.Cache/Redis/accessPolicies@2024-11-01' = {
  parent: Redis_krc_ai_dev_rds_01_name_resource
  name: 'Data Owner'
  properties: {
    permissions: '+@all allkeys'
  }
}

resource Redis_krc_ai_dev_rds_01_name_Data_Reader 'Microsoft.Cache/Redis/accessPolicies@2024-11-01' = {
  parent: Redis_krc_ai_dev_rds_01_name_resource
  name: 'Data Reader'
  properties: {
    permissions: '+@read +@connection +cluster|info +cluster|nodes +cluster|slots allkeys'
  }
}

resource Redis_krc_ai_dev_rds_01_name_Redis_krc_ai_dev_rds_01_name_pri_ed_a22dd2fe_3692_4245_8bb3_ff6dc61351a7 'Microsoft.Cache/Redis/privateEndpointConnections@2024-11-01' = {
  parent: Redis_krc_ai_dev_rds_01_name_resource
  name: '${Redis_krc_ai_dev_rds_01_name}-pri-ed.a22dd2fe-3692-4245-8bb3-ff6dc61351a7'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
      actionsRequired: 'None'
    }
  }
}

resource accounts_krc_ai_dev_openai_01_name_Default 'Microsoft.CognitiveServices/accounts/defenderForAISettings@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'Default'
  properties: {
    state: 'Disabled'
  }
}

resource accounts_krc_ai_dev_openai_01_name_gpt_4_1 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'gpt-4.1'
  sku: {
    name: 'GlobalStandard'
    capacity: 1000
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    currentCapacity: 1000
    raiPolicyName: 'krc-ai-dev-content-filter'
  }
}

resource accounts_krc_ai_dev_openai_01_name_gpt_4_1_mini 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'gpt-4.1-mini'
  sku: {
    name: 'GlobalStandard'
    capacity: 5000
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    currentCapacity: 5000
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource accounts_krc_ai_dev_openai_01_name_text_embedding_3_large 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'text-embedding-3-large'
  sku: {
    name: 'GlobalStandard'
    capacity: 1000
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
    currentCapacity: 1000
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource accounts_krc_ai_dev_openai_01_name_AISerchtoOpenAI_pri_link_02_7a2dbb7c_96ab_4acc_b2d6_a1282b9350c0 'Microsoft.CognitiveServices/accounts/privateEndpointConnections@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'AISerchtoOpenAI-pri-link-02.7a2dbb7c-96ab-4acc-b2d6-a1282b9350c0'
  location: 'koreacentral'
  properties: {
    privateEndpoint: {}
    groupIds: [
      'account'
    ]
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'request'
      actionsRequired: 'None'
    }
  }
}

resource accounts_krc_ai_dev_docitg_01_name_accounts_krc_ai_dev_docitg_01_name_pri_ed_65467593_3d6b_4efe_8fd2_c53b51048932 'Microsoft.CognitiveServices/accounts/privateEndpointConnections@2025-06-01' = {
  parent: accounts_krc_ai_dev_docitg_01_name_resource
  name: '${accounts_krc_ai_dev_docitg_01_name}-pri-ed.65467593-3d6b-4efe-8fd2-c53b51048932'
  location: 'koreacentral'
  properties: {
    privateEndpoint: {}
    groupIds: [
      'account'
    ]
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Approved'
      actionsRequired: 'None'
    }
  }
}

resource accounts_krc_ai_dev_openai_01_name_accounts_krc_ai_dev_openai_01_name_pri_ed_5f4d8859_06a4_43c1_bc30_cd65f3c21d10 'Microsoft.CognitiveServices/accounts/privateEndpointConnections@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: '${accounts_krc_ai_dev_openai_01_name}-pri-ed.5f4d8859-06a4-43c1-bc30-cd65f3c21d10'
  location: 'koreacentral'
  properties: {
    privateEndpoint: {}
    groupIds: [
      'account'
    ]
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Approved'
      actionsRequired: 'None'
    }
  }
}

resource accounts_krc_ai_dev_openai_01_name_krc_ai_dev_content_filter 'Microsoft.CognitiveServices/accounts/raiPolicies@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'krc-ai-dev-content-filter'
  properties: {
    mode: 'Default'
    basePolicyName: 'Microsoft.DefaultV2'
    contentFilters: [
      {
        name: 'Violence'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Hate'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Sexual'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Selfharm'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Jailbreak'
        blocking: false
        enabled: false
        source: 'Prompt'
      }
      {
        name: 'Indirect Attack'
        blocking: false
        enabled: false
        source: 'Prompt'
      }
      {
        name: 'Indirect Attack Spotlighting'
        blocking: false
        enabled: false
        source: 'Prompt'
      }
      {
        name: 'Violence'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Hate'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Sexual'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Selfharm'
        severityThreshold: 'High'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Protected Material Text'
        blocking: false
        enabled: false
        source: 'Completion'
      }
      {
        name: 'Protected Material Code'
        blocking: false
        enabled: false
        source: 'Completion'
      }
    ]
  }
}

resource accounts_krc_ai_dev_openai_01_name_Microsoft_Default 'Microsoft.CognitiveServices/accounts/raiPolicies@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'Microsoft.Default'
  properties: {
    mode: 'Blocking'
    contentFilters: [
      {
        name: 'Hate'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Hate'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Sexual'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Sexual'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Violence'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Violence'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Selfharm'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Selfharm'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
    ]
  }
}

resource accounts_krc_ai_dev_openai_01_name_Microsoft_DefaultV2 'Microsoft.CognitiveServices/accounts/raiPolicies@2025-06-01' = {
  parent: accounts_krc_ai_dev_openai_01_name_resource
  name: 'Microsoft.DefaultV2'
  properties: {
    mode: 'Blocking'
    contentFilters: [
      {
        name: 'Hate'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Hate'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Sexual'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Sexual'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Violence'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Violence'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Selfharm'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Selfharm'
        severityThreshold: 'Medium'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Jailbreak'
        blocking: true
        enabled: true
        source: 'Prompt'
      }
      {
        name: 'Protected Material Text'
        blocking: true
        enabled: true
        source: 'Completion'
      }
      {
        name: 'Protected Material Code'
        blocking: false
        enabled: true
        source: 'Completion'
      }
    ]
  }
}

resource virtualMachines_krc_ai_dev_dev_linux_vm01_name_resource 'Microsoft.Compute/virtualMachines@2024-11-01' = {
  name: virtualMachines_krc_ai_dev_dev_linux_vm01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  zones: [
    '1'
  ]
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: 'Standard_D2s_v4'
    }
    additionalCapabilities: {
      hibernationEnabled: false
    }
    storageProfile: {
      imageReference: {
        publisher: 'canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        osType: 'Linux'
        name: '${virtualMachines_krc_ai_dev_dev_linux_vm01_name}_OsDisk_1_aeb3d54744a84683ad0becfb1323e8fb'
        createOption: 'FromImage'
        caching: 'ReadWrite'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
          id: resourceId(
            'Microsoft.Compute/disks',
            '${virtualMachines_krc_ai_dev_dev_linux_vm01_name}_OsDisk_1_aeb3d54744a84683ad0becfb1323e8fb'
          )
        }
        deleteOption: 'Delete'
        diskSizeGB: 128
      }
      dataDisks: []
      diskControllerType: 'SCSI'
    }
    osProfile: {
      computerName: virtualMachines_krc_ai_dev_dev_linux_vm01_name
      adminUsername: 'acme_admin'
      linuxConfiguration: {
        disablePasswordAuthentication: false
        provisionVMAgent: true
        patchSettings: {
          patchMode: 'ImageDefault'
          assessmentMode: 'ImageDefault'
        }
      }
      secrets: []
      allowExtensionOperations: true
      requireGuestProvisionSignal: true
    }
    securityProfile: {
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
      securityType: 'TrustedLaunch'
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: networkInterfaces_krc_ai_dev_dev_linux_vm01239_z1_name_resource.id
          properties: {
            deleteOption: 'Detach'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

resource virtualMachines_krc_ai_dev_dev_linux_vm02_name_resource 'Microsoft.Compute/virtualMachines@2024-11-01' = {
  name: virtualMachines_krc_ai_dev_dev_linux_vm02_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  zones: [
    '1'
  ]
  properties: {
    hardwareProfile: {
      vmSize: 'Standard_D2s_v4'
    }
    additionalCapabilities: {
      hibernationEnabled: false
    }
    storageProfile: {
      imageReference: {
        publisher: 'canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        osType: 'Linux'
        name: '${virtualMachines_krc_ai_dev_dev_linux_vm02_name}_OsDisk_1_57f324d741674b508292a01e42995fa2'
        createOption: 'FromImage'
        caching: 'ReadWrite'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
          id: resourceId(
            'Microsoft.Compute/disks',
            '${virtualMachines_krc_ai_dev_dev_linux_vm02_name}_OsDisk_1_57f324d741674b508292a01e42995fa2'
          )
        }
        deleteOption: 'Delete'
        diskSizeGB: 128
      }
      dataDisks: []
      diskControllerType: 'SCSI'
    }
    osProfile: {
      computerName: virtualMachines_krc_ai_dev_dev_linux_vm02_name
      adminUsername: 'acme_admin'
      linuxConfiguration: {
        disablePasswordAuthentication: false
        provisionVMAgent: true
        patchSettings: {
          patchMode: 'ImageDefault'
          assessmentMode: 'ImageDefault'
        }
      }
      secrets: []
      allowExtensionOperations: true
      requireGuestProvisionSignal: true
    }
    securityProfile: {
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
      securityType: 'TrustedLaunch'
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: networkInterfaces_krc_ai_dev_dev_linux_vm02716_z1_name_resource.id
          properties: {
            deleteOption: 'Detach'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

resource registries_krcaidevacr01_name_koreacentral 'Microsoft.ContainerRegistry/registries/replications@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: 'koreacentral'
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    regionEndpointEnabled: true
    zoneRedundancy: 'Enabled'
  }
}

resource registries_krcaidevacr01_name_repositories_admin 'Microsoft.ContainerRegistry/registries/scopeMaps@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: '_repositories_admin'
  properties: {
    description: 'Can perform all read, write and delete operations on the registry'
    actions: [
      'repositories/*/metadata/read'
      'repositories/*/metadata/write'
      'repositories/*/content/read'
      'repositories/*/content/write'
      'repositories/*/content/delete'
    ]
  }
}

resource registries_krcaidevacr01_name_repositories_pull 'Microsoft.ContainerRegistry/registries/scopeMaps@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: '_repositories_pull'
  properties: {
    description: 'Can pull any repository of the registry'
    actions: [
      'repositories/*/content/read'
    ]
  }
}

resource registries_krcaidevacr01_name_repositories_pull_metadata_read 'Microsoft.ContainerRegistry/registries/scopeMaps@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: '_repositories_pull_metadata_read'
  properties: {
    description: 'Can perform all read operations on the registry'
    actions: [
      'repositories/*/content/read'
      'repositories/*/metadata/read'
    ]
  }
}

resource registries_krcaidevacr01_name_repositories_push 'Microsoft.ContainerRegistry/registries/scopeMaps@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: '_repositories_push'
  properties: {
    description: 'Can push to any repository of the registry'
    actions: [
      'repositories/*/content/read'
      'repositories/*/content/write'
    ]
  }
}

resource registries_krcaidevacr01_name_repositories_push_metadata_write 'Microsoft.ContainerRegistry/registries/scopeMaps@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: '_repositories_push_metadata_write'
  properties: {
    description: 'Can perform all read and write operations on the registry'
    actions: [
      'repositories/*/metadata/read'
      'repositories/*/metadata/write'
      'repositories/*/content/read'
      'repositories/*/content/write'
    ]
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource 'Microsoft.DBforPostgreSQL/flexibleServers@2025-01-01-preview' = {
  name: flexibleServers_krc_ai_dev_pgsqlfx_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'Standard_D2ds_v5'
    tier: 'GeneralPurpose'
  }
  properties: {
    replica: {
      role: 'Primary'
    }
    storage: {
      iops: 500
      tier: 'P10'
      storageSizeGB: 128
      autoGrow: 'Enabled'
    }
    network: {
      publicNetworkAccess: 'Disabled'
      delegatedSubnetResourceId: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id
      privateDnsZoneArmResourceId: privateDnsZones_privatelink_postgres_database_azure_com_externalid
    }
    dataEncryption: {
      type: 'SystemManaged'
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    version: '17'
    administratorLogin: 'pgsqldbadmin'
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'ZoneRedundant'
      standbyAvailabilityZone: '2'
    }
    maintenanceWindow: {
      customWindow: 'Disabled'
      dayOfWeek: 0
      startHour: 0
      startMinute: 0
    }
    replicationRole: 'Primary'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_Default 'Microsoft.DBforPostgreSQL/flexibleServers/advancedThreatProtectionSettings@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'Default'
  properties: {
    state: 'Disabled'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639048163881072278 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639048163881072278'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639049028394894850 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639049028394894850'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639049892937676357 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639049892937676357'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639050757447435649 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639050757447435649'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639051620415049894 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639051620415049894'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639052484687073979 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639052484687073979'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backup_639053349050899179 'Microsoft.DBforPostgreSQL/flexibleServers/backups@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backup_639053349050899179'
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_allow_alter_system 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'allow_alter_system'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_allow_in_place_tablespaces 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'allow_in_place_tablespaces'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_allow_system_table_mods 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'allow_system_table_mods'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_algorithm 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.algorithm'
  properties: {
    value: 'sha256'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_k_anonymity_provider 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.k_anonymity_provider'
  properties: {
    value: 'k_anonymity'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_masking_policies 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.masking_policies'
  properties: {
    value: 'anon'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_maskschema 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.maskschema'
  properties: {
    value: 'mask'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_privacy_by_default 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.privacy_by_default'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_restrict_to_trusted_schemas 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.restrict_to_trusted_schemas'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_salt 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.salt'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_sourceschema 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.sourceschema'
  properties: {
    value: 'public'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_strict_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.strict_mode'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_anon_transparent_dynamic_masking 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'anon.transparent_dynamic_masking'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_application_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'application_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_archive_cleanup_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'archive_cleanup_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_archive_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'archive_command'
  properties: {
    value: 'BlobLogUpload.sh %f %p'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_archive_library 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'archive_library'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_archive_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'archive_mode'
  properties: {
    value: 'always'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_archive_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'archive_timeout'
  properties: {
    value: '300'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_array_nulls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'array_nulls'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_authentication_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'authentication_timeout'
  properties: {
    value: '30'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_analyze 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_analyze'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_buffers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_format 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_format'
  properties: {
    value: 'text'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_min_duration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_min_duration'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_nested_statements 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_nested_statements'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_parameter_max_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_parameter_max_length'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_settings 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_settings'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_timing 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_timing'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_triggers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_triggers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_verbose 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_verbose'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_log_wal 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.log_wal'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_auto_explain_sample_rate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'auto_explain.sample_rate'
  properties: {
    value: '1.0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_analyze_scale_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_analyze_scale_factor'
  properties: {
    value: '0.1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_analyze_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_analyze_threshold'
  properties: {
    value: '50'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_freeze_max_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_freeze_max_age'
  properties: {
    value: '200000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_max_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_max_workers'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_multixact_freeze_max_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_multixact_freeze_max_age'
  properties: {
    value: '400000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_naptime 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_naptime'
  properties: {
    value: '60'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_vacuum_cost_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_vacuum_cost_delay'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_vacuum_cost_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_vacuum_cost_limit'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_vacuum_insert_scale_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_vacuum_insert_scale_factor'
  properties: {
    value: '0.2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_vacuum_insert_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_vacuum_insert_threshold'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_vacuum_scale_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_vacuum_scale_factor'
  properties: {
    value: '0.2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_vacuum_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_vacuum_threshold'
  properties: {
    value: '50'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_autovacuum_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'autovacuum_work_mem'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_accepted_password_auth_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.accepted_password_auth_method'
  properties: {
    value: 'md5,scram-sha-256'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_enable_temp_tablespaces_on_local_ssd 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.enable_temp_tablespaces_on_local_ssd'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.extensions'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_migration_copy_with_binary 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.migration_copy_with_binary'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_migration_skip_analyze 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.migration_skip_analyze'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_migration_skip_extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.migration_skip_extensions'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_migration_skip_large_objects 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.migration_skip_large_objects'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_migration_skip_role_user 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.migration_skip_role_user'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_migration_table_split_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.migration_table_split_size'
  properties: {
    value: '20480'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_service_principal_id 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.service_principal_id'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_service_principal_tenant_id 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.service_principal_tenant_id'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_single_to_flex_migration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure.single_to_flex_migration'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_change_batch_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.change_batch_buffer_size'
  properties: {
    value: '16'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_change_batch_export_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.change_batch_export_timeout'
  properties: {
    value: '30'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_max_fabric_mirrors 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.max_fabric_mirrors'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_max_snapshot_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.max_snapshot_workers'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_onelake_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.onelake_buffer_size'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_parquet_compression 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.parquet_compression'
  properties: {
    value: 'zstd'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_snapshot_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.snapshot_buffer_size'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_cdc_snapshot_export_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_cdc.snapshot_export_timeout'
  properties: {
    value: '180'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_storage_allow_network_access 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_storage.allow_network_access'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_storage_blob_block_size_mb 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_storage.blob_block_size_mb'
  properties: {
    value: '256'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_storage_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_storage.log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_storage_public_account_access 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_storage.public_account_access'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backend_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backend_flush_after'
  properties: {
    value: '256'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backslash_quote 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backslash_quote'
  properties: {
    value: 'safe_encoding'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_backtrace_functions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'backtrace_functions'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bgwriter_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bgwriter_delay'
  properties: {
    value: '20'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bgwriter_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bgwriter_flush_after'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bgwriter_lru_maxpages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bgwriter_lru_maxpages'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bgwriter_lru_multiplier 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bgwriter_lru_multiplier'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_block_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'block_size'
  properties: {
    value: '8192'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bonjour 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bonjour'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bonjour_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bonjour_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_bytea_output 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'bytea_output'
  properties: {
    value: 'hex'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_check_function_bodies 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'check_function_bodies'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_checkpoint_completion_target 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'checkpoint_completion_target'
  properties: {
    value: '0.9'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_checkpoint_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'checkpoint_flush_after'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_checkpoint_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'checkpoint_timeout'
  properties: {
    value: '600'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_checkpoint_warning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'checkpoint_warning'
  properties: {
    value: '30'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_client_connection_check_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'client_connection_check_interval'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_client_encoding 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'client_encoding'
  properties: {
    value: 'UTF8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_client_min_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'client_min_messages'
  properties: {
    value: 'notice'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cluster_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cluster_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_commit_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'commit_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_commit_siblings 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'commit_siblings'
  properties: {
    value: '5'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_commit_timestamp_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'commit_timestamp_buffers'
  properties: {
    value: '512'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_compute_query_id 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'compute_query_id'
  properties: {
    value: 'auto'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_config_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'config_file'
  properties: {
    value: '/datadrive/pg/data/postgresql.conf'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_bucket_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.bucket_limit'
  properties: {
    value: '2000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_enable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.enable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_factor_bias 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.factor_bias'
  properties: {
    value: '0.8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_hash_entries_max 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.hash_entries_max'
  properties: {
    value: '500'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_reset_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.reset_time'
  properties: {
    value: '120'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_restore_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.restore_factor'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_connection_throttle_update_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'connection_throttle.update_time'
  properties: {
    value: '20'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_constraint_exclusion 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'constraint_exclusion'
  properties: {
    value: 'partition'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cpu_index_tuple_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cpu_index_tuple_cost'
  properties: {
    value: '0.005'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cpu_operator_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cpu_operator_cost'
  properties: {
    value: '0.0025'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cpu_tuple_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cpu_tuple_cost'
  properties: {
    value: '0.01'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_createrole_self_grant 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'createrole_self_grant'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_auth_delay_ms 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.auth_delay_ms'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_auth_failure_cache_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.auth_failure_cache_size'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_encrypted_password_allowed 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.encrypted_password_allowed'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_history_max_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.history_max_size'
  properties: {
    value: '65535'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_max_auth_failure 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.max_auth_failure'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_no_password_logging 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.no_password_logging'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_contain 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_contain'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_contain_username 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_contain_username'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_ignore_case 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_ignore_case'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_min_digit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_min_digit'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_min_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_min_length'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_min_lower 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_min_lower'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_min_repeat 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_min_repeat'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_min_special 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_min_special'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_min_upper 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_min_upper'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_not_contain 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_not_contain'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_reuse_history 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_reuse_history'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_reuse_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_reuse_interval'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_valid_max 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_valid_max'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_password_valid_until 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.password_valid_until'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_reset_superuser 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.reset_superuser'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_contain 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_contain'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_contain_password 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_contain_password'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_ignore_case 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_ignore_case'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_min_digit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_min_digit'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_min_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_min_length'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_min_lower 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_min_lower'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_min_repeat 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_min_repeat'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_min_special 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_min_special'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_min_upper 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_min_upper'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_username_not_contain 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.username_not_contain'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_whitelist 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.whitelist'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_credcheck_whitelist_auth_failure 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'credcheck.whitelist_auth_failure'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_database_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.database_name'
  properties: {
    value: 'postgres'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_enable_superuser_jobs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.enable_superuser_jobs'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_host 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.host'
  properties: {
    value: '/tmp'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_launch_active_jobs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.launch_active_jobs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_log_min_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.log_min_messages'
  properties: {
    value: 'warning'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_log_run 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.log_run'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_log_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.log_statement'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_max_running_jobs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.max_running_jobs'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_timezone 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.timezone'
  properties: {
    value: 'GMT'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cron_use_background_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cron.use_background_workers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_cursor_tuple_fraction 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'cursor_tuple_fraction'
  properties: {
    value: '0.1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_data_checksums 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'data_checksums'
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_data_directory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'data_directory'
  properties: {
    value: '/datadrive/pg/data'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_data_directory_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'data_directory_mode'
  properties: {
    value: '0700'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_data_sync_retry 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'data_sync_retry'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_DateStyle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'DateStyle'
  properties: {
    value: 'ISO, MDY'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_db_user_namespace 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'db_user_namespace'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_deadlock_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'deadlock_timeout'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_assertions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_assertions'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_discard_caches 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_discard_caches'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_io_direct 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_io_direct'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_logical_replication_streaming 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_logical_replication_streaming'
  properties: {
    value: 'buffered'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_parallel_query 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_parallel_query'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_pretty_print 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_pretty_print'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_print_parse 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_print_parse'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_print_plan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_print_plan'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_debug_print_rewritten 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'debug_print_rewritten'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_statistics_target 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_statistics_target'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_table_access_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_table_access_method'
  properties: {
    value: 'heap'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_tablespace 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_tablespace'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_text_search_config 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_text_search_config'
  properties: {
    value: 'pg_catalog.english'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_toast_compression 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_toast_compression'
  properties: {
    value: 'lz4'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_transaction_deferrable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_transaction_deferrable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_transaction_isolation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_transaction_isolation'
  properties: {
    value: 'read committed'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_default_transaction_read_only 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'default_transaction_read_only'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_duckdb_max_memory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'duckdb.max_memory'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_duckdb_max_workers_per_postgres_scan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'duckdb.max_workers_per_postgres_scan'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_duckdb_memory_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'duckdb.memory_limit'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_duckdb_threads 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'duckdb.threads'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_duckdb_worker_threads 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'duckdb.worker_threads'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_dynamic_library_path 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'dynamic_library_path'
  properties: {
    value: '$libdir'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_dynamic_shared_memory_type 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'dynamic_shared_memory_type'
  properties: {
    value: 'posix'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_effective_cache_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'effective_cache_size'
  properties: {
    value: '786432'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_effective_io_concurrency 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'effective_io_concurrency'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_async_append 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_async_append'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_bitmapscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_bitmapscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_gathermerge 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_gathermerge'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_group_by_reordering 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_group_by_reordering'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_hashagg 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_hashagg'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_hashjoin 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_hashjoin'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_incremental_sort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_incremental_sort'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_indexonlyscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_indexonlyscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_indexscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_indexscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_material 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_material'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_memoize 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_memoize'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_mergejoin 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_mergejoin'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_nestloop 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_nestloop'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_parallel_append 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_parallel_append'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_parallel_hash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_parallel_hash'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_partition_pruning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_partition_pruning'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_partitionwise_aggregate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_partitionwise_aggregate'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_partitionwise_join 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_partitionwise_join'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_presorted_aggregate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_presorted_aggregate'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_seqscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_seqscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_sort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_sort'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_enable_tidscan 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'enable_tidscan'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_escape_string_warning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'escape_string_warning'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_event_source 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'event_source'
  properties: {
    value: 'PostgreSQL'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_event_triggers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'event_triggers'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_exit_on_error 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'exit_on_error'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_external_pid_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'external_pid_file'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_extra_float_digits 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'extra_float_digits'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_from_collapse_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'from_collapse_limit'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_fsync 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'fsync'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_full_page_writes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'full_page_writes'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo_effort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo_effort'
  properties: {
    value: '5'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo_generations 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo_generations'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo_pool_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo_pool_size'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo_seed 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo_seed'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo_selection_bias 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo_selection_bias'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_geqo_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'geqo_threshold'
  properties: {
    value: '12'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_gin_fuzzy_search_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'gin_fuzzy_search_limit'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_gin_pending_list_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'gin_pending_list_limit'
  properties: {
    value: '4096'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_gss_accept_delegation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'gss_accept_delegation'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_hash_mem_multiplier 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'hash_mem_multiplier'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_hba_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'hba_file'
  properties: {
    value: '/datadrive/pg/data/pg_hba.conf'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_hot_standby 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'hot_standby'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_hot_standby_feedback 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'hot_standby_feedback'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_huge_page_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'huge_page_size'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_huge_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'huge_pages'
  properties: {
    value: 'try'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_huge_pages_status 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'huge_pages_status'
  properties: {
    value: 'off'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_icu_validation_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'icu_validation_level'
  properties: {
    value: 'warning'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ident_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ident_file'
  properties: {
    value: '/datadrive/pg/data/pg_ident.conf'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_idle_in_transaction_session_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'idle_in_transaction_session_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_idle_session_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'idle_session_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ignore_checksum_failure 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ignore_checksum_failure'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ignore_invalid_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ignore_invalid_pages'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ignore_system_indexes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ignore_system_indexes'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_in_hot_standby 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'in_hot_standby'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_integer_datetimes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'integer_datetimes'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_intelligent_tuning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'intelligent_tuning'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_intelligent_tuning_metric_targets 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'intelligent_tuning.metric_targets'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_IntervalStyle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'IntervalStyle'
  properties: {
    value: 'postgres'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_io_combine_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'io_combine_limit'
  properties: {
    value: '16'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_above_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_above_cost'
  properties: {
    value: '100000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_debugging_support 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_debugging_support'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_dump_bitcode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_dump_bitcode'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_expressions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_expressions'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_inline_above_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_inline_above_cost'
  properties: {
    value: '500000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_optimize_above_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_optimize_above_cost'
  properties: {
    value: '500000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_profiling_support 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_profiling_support'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_provider 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_provider'
  properties: {
    value: 'llvmjit'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_jit_tuple_deforming 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'jit_tuple_deforming'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_join_collapse_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'join_collapse_limit'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_krb_caseins_users 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'krb_caseins_users'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_krb_server_keyfile 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'krb_server_keyfile'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_lc_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'lc_messages'
  properties: {
    value: 'en_US.utf8'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_lc_monetary 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'lc_monetary'
  properties: {
    value: 'en_US.utf-8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_lc_numeric 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'lc_numeric'
  properties: {
    value: 'en_US.utf-8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_lc_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'lc_time'
  properties: {
    value: 'en_US.utf8'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_listen_addresses 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'listen_addresses'
  properties: {
    value: '*'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_lo_compat_privileges 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'lo_compat_privileges'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_local_preload_libraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'local_preload_libraries'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_lock_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'lock_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_autovacuum_min_duration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_autovacuum_min_duration'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_checkpoints 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_checkpoints'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_connections'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_destination 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_destination'
  properties: {
    value: 'stderr'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_directory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_directory'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_disconnections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_disconnections'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_duration 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_duration'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_error_verbosity 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_error_verbosity'
  properties: {
    value: 'default'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_executor_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_executor_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_file_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_file_mode'
  properties: {
    value: '0600'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_filename 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_filename'
  properties: {
    value: 'postgresql-%Y-%m-%d_%H%M%S.log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_hostname 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_hostname'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_line_prefix 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_line_prefix'
  properties: {
    value: '%t-%c-'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_lock_waits 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_lock_waits'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_min_duration_sample 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_min_duration_sample'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_min_duration_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_min_duration_statement'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_min_error_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_min_error_statement'
  properties: {
    value: 'error'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_min_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_min_messages'
  properties: {
    value: 'warning'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_parameter_max_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_parameter_max_length'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_parameter_max_length_on_error 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_parameter_max_length_on_error'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_parser_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_parser_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_planner_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_planner_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_recovery_conflict_waits 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_recovery_conflict_waits'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_replication_commands 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_replication_commands'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_rotation_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_rotation_age'
  properties: {
    value: '60'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_rotation_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_rotation_size'
  properties: {
    value: '102400'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_startup_progress_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_startup_progress_interval'
  properties: {
    value: '10000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_statement'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_statement_sample_rate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_statement_sample_rate'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_statement_stats 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_statement_stats'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_temp_files 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_temp_files'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_timezone 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_timezone'
  properties: {
    value: 'UTC'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_transaction_sample_rate 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_transaction_sample_rate'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_log_truncate_on_rotation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'log_truncate_on_rotation'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_logfiles_download_enable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'logfiles.download_enable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_logfiles_retention_days 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'logfiles.retention_days'
  properties: {
    value: '3'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_logging_collector 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'logging_collector'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_logical_decoding_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'logical_decoding_work_mem'
  properties: {
    value: '65536'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_maintenance_io_concurrency 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'maintenance_io_concurrency'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_maintenance_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'maintenance_work_mem'
  properties: {
    value: '216064'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_connections'
  properties: {
    value: '859'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_files_per_process 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_files_per_process'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_function_args 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_function_args'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_identifier_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_identifier_length'
  properties: {
    value: '63'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_index_keys 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_index_keys'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_locks_per_transaction 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_locks_per_transaction'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_logical_replication_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_logical_replication_workers'
  properties: {
    value: '4'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_notify_queue_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_notify_queue_pages'
  properties: {
    value: '1048576'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_parallel_apply_workers_per_subscription 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_parallel_apply_workers_per_subscription'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_parallel_maintenance_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_parallel_maintenance_workers'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_parallel_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_parallel_workers'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_parallel_workers_per_gather 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_parallel_workers_per_gather'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_pred_locks_per_page 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_pred_locks_per_page'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_pred_locks_per_relation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_pred_locks_per_relation'
  properties: {
    value: '-2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_pred_locks_per_transaction 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_pred_locks_per_transaction'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_prepared_transactions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_prepared_transactions'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_replication_slots 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_replication_slots'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_slot_wal_keep_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_slot_wal_keep_size'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_stack_depth 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_stack_depth'
  properties: {
    value: '2048'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_standby_archive_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_standby_archive_delay'
  properties: {
    value: '30000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_standby_streaming_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_standby_streaming_delay'
  properties: {
    value: '30000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_sync_workers_per_subscription 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_sync_workers_per_subscription'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_wal_senders 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_wal_senders'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_wal_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_wal_size'
  properties: {
    value: '12288'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_max_worker_processes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'max_worker_processes'
  properties: {
    value: '8'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_metrics_autovacuum_diagnostics 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'metrics.autovacuum_diagnostics'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_metrics_collector_database_activity 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'metrics.collector_database_activity'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_metrics_pgbouncer_diagnostics 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'metrics.pgbouncer_diagnostics'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_min_dynamic_shared_memory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'min_dynamic_shared_memory'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_min_parallel_index_scan_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'min_parallel_index_scan_size'
  properties: {
    value: '64'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_min_parallel_table_scan_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'min_parallel_table_scan_size'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_min_wal_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'min_wal_size'
  properties: {
    value: '80'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_multixact_member_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'multixact_member_buffers'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_multixact_offset_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'multixact_offset_buffers'
  properties: {
    value: '16'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_notify_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'notify_buffers'
  properties: {
    value: '16'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_parallel_leader_participation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'parallel_leader_participation'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_parallel_setup_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'parallel_setup_cost'
  properties: {
    value: '1000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_parallel_tuple_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'parallel_tuple_cost'
  properties: {
    value: '0.1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_password_encryption 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'password_encryption'
  properties: {
    value: 'scram-sha-256'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_hint_plan_debug_print 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_hint_plan.debug_print'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_hint_plan_enable_hint 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_hint_plan.enable_hint'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_hint_plan_enable_hint_table 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_hint_plan.enable_hint_table'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_hint_plan_message_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_hint_plan.message_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_hint_plan_parse_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_hint_plan.parse_messages'
  properties: {
    value: 'info'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_partman_bgw_analyze 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_partman_bgw.analyze'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_partman_bgw_dbname 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_partman_bgw.dbname'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_partman_bgw_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_partman_bgw.interval'
  properties: {
    value: '3600'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_partman_bgw_jobmon 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_partman_bgw.jobmon'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_partman_bgw_maintenance_wait 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_partman_bgw.maintenance_wait'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_partman_bgw_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_partman_bgw.role'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_prewarm_autoprewarm 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_prewarm.autoprewarm'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_prewarm_autoprewarm_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_prewarm.autoprewarm_interval'
  properties: {
    value: '300'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_interval_length_minutes 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.interval_length_minutes'
  properties: {
    value: '15'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_is_enabled_fs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.is_enabled_fs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_max_captured_queries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.max_captured_queries'
  properties: {
    value: '500'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_max_plan_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.max_plan_size'
  properties: {
    value: '7500'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_max_query_text_length 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.max_query_text_length'
  properties: {
    value: '6000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_parameters_capture_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.parameters_capture_mode'
  properties: {
    value: 'capture_parameterless_only'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_query_capture_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.query_capture_mode'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_retention_period_in_days 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.retention_period_in_days'
  properties: {
    value: '7'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_store_query_plans 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.store_query_plans'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_qs_track_utility 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_qs.track_utility'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_stat_statements_max 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_stat_statements.max'
  properties: {
    value: '5000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_stat_statements_save 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_stat_statements.save'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_stat_statements_track 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_stat_statements.track'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_stat_statements_track_planning 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_stat_statements.track_planning'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pg_stat_statements_track_utility 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pg_stat_statements.track_utility'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaadauth_enable_group_sync 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaadauth.enable_group_sync'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_catalog 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_catalog'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_client 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_client'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_parameter 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_parameter'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_parameter_max_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_parameter_max_size'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_relation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_relation'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_rows 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_rows'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_statement 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_statement'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_log_statement_once 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.log_statement_once'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgaudit_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgaudit.role'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgbouncer_enabled 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgbouncer.enabled'
  properties: {
    value: 'false'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_batch_inserts 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.batch_inserts'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_conflict_log_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.conflict_log_level'
  properties: {
    value: 'log'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_conflict_resolution 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.conflict_resolution'
  properties: {
    value: 'apply_remote'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_extra_connection_options 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.extra_connection_options'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_synchronous_commit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.synchronous_commit'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_temp_directory 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.temp_directory'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pglogical_use_spi 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pglogical.use_spi'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgms_stats_is_enabled_fs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgms_stats.is_enabled_fs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgms_wait_sampling_history_period 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgms_wait_sampling.history_period'
  properties: {
    value: '100'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgms_wait_sampling_is_enabled_fs 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgms_wait_sampling.is_enabled_fs'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pgms_wait_sampling_query_capture_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pgms_wait_sampling.query_capture_mode'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_plan_cache_mode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'plan_cache_mode'
  properties: {
    value: 'auto'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_port 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'port'
  properties: {
    value: '5432'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_post_auth_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'post_auth_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_postgis_gdal_enabled_drivers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'postgis.gdal_enabled_drivers'
  properties: {
    value: 'DISABLE_ALL'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_pre_auth_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'pre_auth_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_primary_conninfo 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'primary_conninfo'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_primary_slot_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'primary_slot_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_quote_all_identifiers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'quote_all_identifiers'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_random_page_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'random_page_cost'
  properties: {
    value: '2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_end_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_end_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_init_sync_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_init_sync_method'
  properties: {
    value: 'fsync'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_min_apply_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_min_apply_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_prefetch 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_prefetch'
  properties: {
    value: 'try'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_action 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_action'
  properties: {
    value: 'pause'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_inclusive 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_inclusive'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_lsn 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_lsn'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_name 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_name'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_time'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_timeline 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_timeline'
  properties: {
    value: 'latest'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recovery_target_xid 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recovery_target_xid'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_recursive_worktable_factor 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'recursive_worktable_factor'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_remove_temp_files_after_crash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'remove_temp_files_after_crash'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_require_secure_transport 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'require_secure_transport'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_reserved_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'reserved_connections'
  properties: {
    value: '5'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_restart_after_crash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'restart_after_crash'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_restore_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'restore_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_restrict_nonsystem_relation_kind 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'restrict_nonsystem_relation_kind'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_row_security 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'row_security'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_scram_iterations 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'scram_iterations'
  properties: {
    value: '4096'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_search_path 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'search_path'
  properties: {
    value: '"$user", public'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_segment_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'segment_size'
  properties: {
    value: '131072'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_send_abort_for_crash 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'send_abort_for_crash'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_send_abort_for_kill 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'send_abort_for_kill'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_seq_page_cost 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'seq_page_cost'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_serializable_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'serializable_buffers'
  properties: {
    value: '32'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_server_encoding 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'server_encoding'
  properties: {
    value: 'UTF8'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_server_version 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'server_version'
  properties: {
    value: '17.6'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_server_version_num 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'server_version_num'
  properties: {
    value: '170006'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_session_preload_libraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'session_preload_libraries'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_session_replication_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'session_replication_role'
  properties: {
    value: 'origin'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_shared_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'shared_buffers'
  properties: {
    value: '262144'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_shared_memory_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'shared_memory_size'
  properties: {
    value: '2206'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_shared_memory_size_in_huge_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'shared_memory_size_in_huge_pages'
  properties: {
    value: '1103'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_shared_memory_type 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'shared_memory_type'
  properties: {
    value: 'mmap'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_shared_preload_libraries 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'shared_preload_libraries'
  properties: {
    value: 'pg_cron,pg_stat_statements'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_squeeze_max_xlock_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'squeeze.max_xlock_time'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_squeeze_worker_autostart 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'squeeze.worker_autostart'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_squeeze_worker_role 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'squeeze.worker_role'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_squeeze_workers_per_database 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'squeeze.workers_per_database'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl'
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_ca_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_ca_file'
  properties: {
    value: '/datadrive/certs/ca.pem'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_cert_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_cert_file'
  properties: {
    value: '/datadrive/certs/cert.pem'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_ciphers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_ciphers'
  properties: {
    value: 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_crl_dir 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_crl_dir'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_crl_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_crl_file'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_dh_params_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_dh_params_file'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_ecdh_curve 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_ecdh_curve'
  properties: {
    value: 'prime256v1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_key_file 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_key_file'
  properties: {
    value: '/datadrive/certs/key.pem'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_library 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_library'
  properties: {
    value: 'OpenSSL'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_max_protocol_version 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_max_protocol_version'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_min_protocol_version 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_min_protocol_version'
  properties: {
    value: 'TLSv1.2'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_passphrase_command 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_passphrase_command'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_passphrase_command_supports_reload 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_passphrase_command_supports_reload'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_ssl_prefer_server_ciphers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'ssl_prefer_server_ciphers'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_standard_conforming_strings 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'standard_conforming_strings'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_statement_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'statement_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_stats_fetch_consistency 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'stats_fetch_consistency'
  properties: {
    value: 'cache'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_subtransaction_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'subtransaction_buffers'
  properties: {
    value: '512'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_summarize_wal 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'summarize_wal'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_superuser_reserved_connections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'superuser_reserved_connections'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_sync_replication_slots 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'sync_replication_slots'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_synchronize_seqscans 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'synchronize_seqscans'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_synchronized_standby_slots 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'synchronized_standby_slots'
  properties: {
    value: 'azure_standby_dbe5128f217d'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_synchronous_commit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'synchronous_commit'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_synchronous_standby_names 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'synchronous_standby_names'
  properties: {
    value: 'ANY 1 ( "azure_standby_dbe5128f217d_standby", "krc-ai-dev-pgsqlfx-01-ukih" )'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_syslog_facility 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'syslog_facility'
  properties: {
    value: 'local0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_syslog_ident 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'syslog_ident'
  properties: {
    value: 'postgres'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_syslog_sequence_numbers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'syslog_sequence_numbers'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_syslog_split_messages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'syslog_split_messages'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_tcp_keepalives_count 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'tcp_keepalives_count'
  properties: {
    value: '9'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_tcp_keepalives_idle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'tcp_keepalives_idle'
  properties: {
    value: '120'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_tcp_keepalives_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'tcp_keepalives_interval'
  properties: {
    value: '30'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_tcp_user_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'tcp_user_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_temp_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'temp_buffers'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_temp_file_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'temp_file_limit'
  properties: {
    value: '-1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_temp_tablespaces 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'temp_tablespaces'
  properties: {
    value: 'temptblspace'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_timescaledb_bgw_launcher_poll_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'timescaledb.bgw_launcher_poll_time'
  properties: {
    value: '60000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_timescaledb_disable_load 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'timescaledb.disable_load'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_timescaledb_max_background_workers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'timescaledb.max_background_workers'
  properties: {
    value: '16'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_timescaledb_osm_disable_load 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'timescaledb_osm.disable_load'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_TimeZone 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'TimeZone'
  properties: {
    value: 'UTC'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_timezone_abbreviations 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'timezone_abbreviations'
  properties: {
    value: 'Default'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_trace_connection_negotiation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'trace_connection_negotiation'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_trace_notify 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'trace_notify'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_trace_sort 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'trace_sort'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_activities 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_activities'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_activity_query_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_activity_query_size'
  properties: {
    value: '1024'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_commit_timestamp 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_commit_timestamp'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_counts 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_counts'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_functions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_functions'
  properties: {
    value: 'none'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_io_timing 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_io_timing'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_track_wal_io_timing 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'track_wal_io_timing'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_transaction_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'transaction_buffers'
  properties: {
    value: '512'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_transaction_deferrable 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'transaction_deferrable'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_transaction_isolation 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'transaction_isolation'
  properties: {
    value: 'read committed'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_transaction_read_only 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'transaction_read_only'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_transaction_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'transaction_timeout'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_transform_null_equals 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'transform_null_equals'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_unix_socket_directories 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'unix_socket_directories'
  properties: {
    value: '/tmp,/tmp/tuning_sockets'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_unix_socket_group 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'unix_socket_group'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_unix_socket_permissions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'unix_socket_permissions'
  properties: {
    value: '0777'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_update_process_title 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'update_process_title'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_buffer_usage_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_buffer_usage_limit'
  properties: {
    value: '2048'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_cost_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_cost_delay'
  properties: {
    value: '0'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_cost_limit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_cost_limit'
  properties: {
    value: '200'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_cost_page_dirty 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_cost_page_dirty'
  properties: {
    value: '20'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_cost_page_hit 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_cost_page_hit'
  properties: {
    value: '1'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_cost_page_miss 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_cost_page_miss'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_failsafe_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_failsafe_age'
  properties: {
    value: '1600000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_freeze_min_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_freeze_min_age'
  properties: {
    value: '50000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_freeze_table_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_freeze_table_age'
  properties: {
    value: '150000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_multixact_failsafe_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_multixact_failsafe_age'
  properties: {
    value: '1600000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_multixact_freeze_min_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_multixact_freeze_min_age'
  properties: {
    value: '5000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_vacuum_multixact_freeze_table_age 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'vacuum_multixact_freeze_table_age'
  properties: {
    value: '150000000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_block_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_block_size'
  properties: {
    value: '8192'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_buffers 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_buffers'
  properties: {
    value: '2048'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_compression 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_compression'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_consistency_checking 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_consistency_checking'
  properties: {
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_decode_buffer_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_decode_buffer_size'
  properties: {
    value: '524288'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_init_zero 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_init_zero'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_keep_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_keep_size'
  properties: {
    value: '400'
    source: 'user-override'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_level 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_level'
  properties: {
    value: 'replica'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_log_hints 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_log_hints'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_receiver_create_temp_slot 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_receiver_create_temp_slot'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_receiver_status_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_receiver_status_interval'
  properties: {
    value: '10'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_receiver_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_receiver_timeout'
  properties: {
    value: '60000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_recycle 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_recycle'
  properties: {
    value: 'on'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_retrieve_retry_interval 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_retrieve_retry_interval'
  properties: {
    value: '5000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_segment_size 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_segment_size'
  properties: {
    value: '16777216'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_sender_timeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_sender_timeout'
  properties: {
    value: '60000'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_skip_threshold 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_skip_threshold'
  properties: {
    value: '2048'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_summary_keep_time 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_summary_keep_time'
  properties: {
    value: '14400'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_sync_method 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_sync_method'
  properties: {
    value: 'fdatasync'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_writer_delay 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_writer_delay'
  properties: {
    value: '200'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_wal_writer_flush_after 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'wal_writer_flush_after'
  properties: {
    value: '128'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_work_mem 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'work_mem'
  properties: {
    value: '4096'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_xmlbinary 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'xmlbinary'
  properties: {
    value: 'base64'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_xmloption 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'xmloption'
  properties: {
    value: 'content'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_zero_damaged_pages 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'zero_damaged_pages'
  properties: {
    value: 'off'
    source: 'system-default'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_maintenance 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_maintenance'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_azure_sys 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'azure_sys'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_db_cloosphere 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'db_cloosphere'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_db_cloosphere_dev 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'db_cloosphere_dev'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_db_msds 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'db_msds'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_krc_ai_dev_pgsqlfx_01_name_postgres 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-01-01-preview' = {
  parent: flexibleServers_krc_ai_dev_pgsqlfx_01_name_resource
  name: 'postgres'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_AllowApToOpenAI 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name}/AllowApToOpenAI'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    sourceAddressPrefix: 'AppService.KoreaCentral'
    destinationAddressPrefix: '10.110.0.0/24'
    access: 'Allow'
    priority: 110
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: [
      '80'
      '443'
    ]
    sourceAddressPrefixes: []
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_AllowApToVM 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name}/AllowApToVM'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '8000-8999'
    sourceAddressPrefix: 'AppService.KoreaCentral'
    access: 'Allow'
    priority: 100
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: []
    destinationAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_AllowFuncToOpenAI 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name}/AllowFuncToOpenAI'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    sourceAddressPrefix: 'AppService.KoreaCentral'
    destinationAddressPrefix: '10.110.0.0/24'
    access: 'Allow'
    priority: 100
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: [
      '80'
      '443'
    ]
    sourceAddressPrefixes: []
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_AllowFuncToStorage 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name}/AllowFuncToStorage'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    sourceAddressPrefix: 'AppService.KoreaCentral'
    destinationAddressPrefix: 'Storage.KoreaCentral'
    access: 'Allow'
    priority: 110
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: [
      '80'
      '443'
      '445'
    ]
    sourceAddressPrefixes: []
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVMSShInBound 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVMSShInBound'
  properties: {
    description: 'Local(intenet) to VM SSH Allow'
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '22'
    access: 'Allow'
    priority: 100
    direction: 'Inbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: [
      '211.215.58.26'
      '222.234.227.131'
    ]
    destinationAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoACROutBound 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVmtoACROutBound'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '8080'
    destinationAddressPrefix: 'AzureContainerRegistry.KoreaCentral'
    access: 'Allow'
    priority: 120
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoAISearchOutBound 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVmtoAISearchOutBound'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '8080'
    destinationAddressPrefix: 'AzureCognitiveSearch'
    access: 'Allow'
    priority: 140
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoCognitiveServiceOutBound 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVmtoCognitiveServiceOutBound'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '8080'
    destinationAddressPrefix: 'CognitiveServicesManagement'
    access: 'Allow'
    priority: 150
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVMtoPgsqlOutBound 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVMtoPgsqlOutBound'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '5432'
    destinationAddressPrefix: '10.100.4.0/27'
    access: 'Allow'
    priority: 130
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVMtoRedis 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVMtoRedis'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '6379'
    destinationAddressPrefix: '10.100.3.0/27'
    access: 'Allow'
    priority: 160
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AllowVmtoStorageOutBound 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AllowVmtoStorageOutBound'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationAddressPrefix: 'Storage.KoreaCentral'
    access: 'Allow'
    priority: 110
    direction: 'Outbound'
    sourcePortRanges: []
    destinationPortRanges: [
      '80'
      '443'
      '445'
    ]
    sourceAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
    destinationAddressPrefixes: []
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_AlowApToVM01 'Microsoft.Network/networkSecurityGroups/securityRules@2024-07-01' = {
  name: '${networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name}/AlowApToVM01'
  properties: {
    protocol: 'TCP'
    sourcePortRange: '*'
    destinationPortRange: '8000-8999'
    sourceAddressPrefix: 'AppService.KoreaCentral'
    access: 'Allow'
    priority: 110
    direction: 'Inbound'
    sourcePortRanges: []
    destinationPortRanges: []
    sourceAddressPrefixes: []
    destinationAddressPrefixes: [
      '10.100.0.4'
      '10.100.0.5'
    ]
  }
  dependsOn: [
    networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource
  ]
}

resource privateDnsZones_privatelink_openai_azure_com_name_eus2_ai_dev_openai_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_openai_azure_com_name_resource
  name: 'eus2-ai-dev-openai-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint eus2-ai-dev-openai-01-pri-ed with resource guid 615685ae-3e87-437f-8c83-de7c27f2e1bf'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.110.0.4'
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurecr_io_name_krcaidevacr01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurecr_io_name_resource
  name: 'krcaidevacr01'
  properties: {
    ttl: 3600
    aRecords: [
      {
        ipv4Address: '10.100.3.8'
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurecr_io_name_krcaidevacr01_koreacentral_data 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurecr_io_name_resource
  name: 'krcaidevacr01.koreacentral.data'
  properties: {
    ttl: 3600
    aRecords: [
      {
        ipv4Address: '10.100.3.5'
      }
    ]
  }
}

resource privateDnsZones_privatelink_cognitiveservices_azure_com_name_krc_ai_dev_docitg_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_cognitiveservices_azure_com_name_resource
  name: 'krc-ai-dev-docitg-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-docitg-01-pri-ed with resource guid 65467593-3d6b-4efe-8fd2-c53b51048932'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.15'
      }
    ]
  }
}

resource privateDnsZones_privatelink_blob_core_windows_net_name_krcaidevsa01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_blob_core_windows_net_name_resource
  name: 'krcaidevsa01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krcaidevsa01-pri-ed-krcaidevsa01-blob-private-endpoint with resource guid 1bd38766-70b5-48fb-ab54-fd62be7d4c1a'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.12'
      }
    ]
  }
}

resource privateDnsZones_privatelink_file_core_windows_net_name_krcaidevsa01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_file_core_windows_net_name_resource
  name: 'krcaidevsa01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krcaidevsa01-pri-ed-krcaidevsa01-file-private-endpoint with resource guid 625f358f-70c1-4a6d-9f91-3d21efb276df'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.9'
      }
    ]
  }
}

resource privateDnsZones_privatelink_queue_core_windows_net_name_krcaidevsa01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_queue_core_windows_net_name_resource
  name: 'krcaidevsa01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krcaidevsa01-pri-ed-krcaidevsa01-queue-private-endpoint with resource guid 0230fb96-bb20-4a8a-8f92-2238d0a44dcb'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.11'
      }
    ]
  }
}

resource privateDnsZones_privatelink_table_core_windows_net_name_krcaidevsa01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_table_core_windows_net_name_resource
  name: 'krcaidevsa01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krcaidevsa01-pri-ed-krcaidevsa01-table-private-endpoint with resource guid 544f6e84-9579-4d92-9076-3b859da881ce'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.13'
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurewebsites_net_name_krc_ai_dev_msds_func_01_aha0fzgjdrgjhzfh_koreacentral_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurewebsites_net_name_resource
  name: 'krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-msds-func-01-pri-ed with resource guid 531aec20-28ff-4c0a-b350-bb70f6c6ef78'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.10'
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurewebsites_net_name_krc_ai_dev_msds_func_01_aha0fzgjdrgjhzfh_scm_koreacentral_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurewebsites_net_name_resource
  name: 'krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.scm.koreacentral-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-msds-func-01-pri-ed with resource guid 531aec20-28ff-4c0a-b350-bb70f6c6ef78'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.10'
      }
    ]
  }
}

resource privateDnsZones_privatelink_blob_core_windows_net_name_krcaidevmsdssa01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_blob_core_windows_net_name_resource
  name: 'krcaidevmsdssa01'
  properties: {
    ttl: 3600
    aRecords: [
      {
        ipv4Address: '10.100.3.4'
      }
    ]
  }
}

resource privateDnsZones_privatelink_openai_azure_com_name_krc_ai_dev_openai_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_openai_azure_com_name_resource
  name: 'krc-ai-dev-openai-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-openai-01-pri-ed with resource guid 5f4d8859-06a4-43c1-bc30-cd65f3c21d10'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.16'
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurewebsites_net_name_krc_ai_dev_owui_as_01_gqf5guftecdrd7cm_koreacentral_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurewebsites_net_name_resource
  name: 'krc-ai-dev-owui-as-01-gqf5guftecdrd7cm.koreacentral-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-owui-as-01-pri-ed with resource guid 7fe40b92-2fa8-47ed-aaf1-d17b140248e9'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.14'
      }
    ]
  }
}

resource privateDnsZones_privatelink_azurewebsites_net_name_krc_ai_dev_owui_as_01_gqf5guftecdrd7cm_scm_koreacentral_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurewebsites_net_name_resource
  name: 'krc-ai-dev-owui-as-01-gqf5guftecdrd7cm.scm.koreacentral-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-owui-as-01-pri-ed with resource guid 7fe40b92-2fa8-47ed-aaf1-d17b140248e9'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.14'
      }
    ]
  }
}

resource privateDnsZones_privatelink_redis_cache_windows_net_name_krc_ai_dev_rds_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_redis_cache_windows_net_name_resource
  name: 'krc-ai-dev-rds-01'
  properties: {
    metadata: {
      creator: 'created by private endpoint krc-ai-dev-rds-01-pri-ed with resource guid 9ead819d-fe0d-4958-b69a-b3dbb30cc077'
    }
    ttl: 10
    aRecords: [
      {
        ipv4Address: '10.100.3.6'
      }
    ]
  }
}

resource privateDnsZones_privatelink_search_windows_net_name_krc_ai_dev_search_01 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: privateDnsZones_privatelink_search_windows_net_name_resource
  name: 'krc-ai-dev-search-01'
  properties: {
    ttl: 3600
    aRecords: [
      {
        ipv4Address: '10.100.3.7'
      }
    ]
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_azurecr_io_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurecr_io_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_azurewebsites_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurewebsites_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_blob_core_windows_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_blob_core_windows_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_cognitiveservices_azure_com_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_cognitiveservices_azure_com_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_file_core_windows_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_file_core_windows_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_openai_azure_com_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_openai_azure_com_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_queue_core_windows_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_queue_core_windows_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_redis_cache_windows_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_redis_cache_windows_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_search_windows_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_search_windows_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource Microsoft_Network_privateDnsZones_SOA_privateDnsZones_privatelink_table_core_windows_net_name 'Microsoft.Network/privateDnsZones/SOA@2024-06-01' = {
  parent: privateDnsZones_privatelink_table_core_windows_net_name_resource
  name: '@'
  properties: {
    ttl: 3600
    soaRecord: {
      email: 'azureprivatedns-host.microsoft.com'
      expireTime: 2419200
      host: 'azureprivatedns.net'
      minimumTtl: 10
      refreshTime: 3600
      retryTime: 300
      serialNumber: 1
    }
  }
}

resource privateDnsZones_privatelink_openai_azure_com_name_acme_ai_dev_eus2_01_vnet 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_openai_azure_com_name_resource
  name: 'acme-ai-dev-eus2-01-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_eus2_01_vnet_externalid
    }
  }
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-pe-subnet'
  properties: {
    addressPrefixes: [
      '10.100.3.0/27'
    ]
    serviceEndpoints: [
      {
        service: 'Microsoft.Storage'
        locations: [
          'koreacentral'
          'koreasouth'
        ]
      }
      {
        service: 'Microsoft.CognitiveServices'
        locations: [
          '*'
        ]
      }
    ]
    delegations: []
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-pgsqlfx-subnet'
  properties: {
    addressPrefixes: [
      '10.100.4.0/27'
    ]
    serviceEndpoints: [
      {
        service: 'Microsoft.Storage'
        locations: [
          'koreacentral'
          'koreasouth'
        ]
      }
      {
        service: 'Microsoft.CognitiveServices'
        locations: [
          '*'
        ]
      }
    ]
    delegations: [
      {
        name: 'dlg-Microsoft.DBforPostgreSQL-flexibleServers'
        id: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id}/delegations/dlg-Microsoft.DBforPostgreSQL-flexibleServers'
        properties: {
          serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets/delegations'
      }
    ]
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_ai_dev_krc_01_to_ai_dev_eus2_01_peer 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/ai-dev-krc-01-to-ai-dev-eus2-01-peer'
  properties: {
    peeringState: 'Connected'
    peeringSyncLevel: 'FullyInSync'
    remoteVirtualNetwork: {
      id: virtualNetworks_acme_ai_dev_eus2_01_vnet_externalid
    }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: false
    useRemoteGateways: false
    doNotVerifyRemoteGateways: false
    peerCompleteVnets: true
    remoteAddressSpace: {
      addressPrefixes: [
        '10.110.0.0/16'
      ]
    }
    remoteVirtualNetworkAddressSpace: {
      addressPrefixes: [
        '10.110.0.0/16'
      ]
    }
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource storageAccounts_krcaidevsa01_name_default 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: 'default'
  sku: {
    name: 'Standard_LRS'
    tier: 'Standard'
  }
  properties: {
    cors: {
      corsRules: []
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: false
    }
  }
}

resource storageAccounts_krcaidevmsdssa01_name_default 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_resource
  name: 'default'
  sku: {
    name: 'Standard_LRS'
    tier: 'Standard'
  }
  properties: {
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    cors: {
      corsRules: []
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: true
      days: 7
    }
  }
}

resource Microsoft_Storage_storageAccounts_fileServices_storageAccounts_krcaidevsa01_name_default 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: 'default'
  sku: {
    name: 'Standard_LRS'
    tier: 'Standard'
  }
  properties: {
    protocolSettings: {
      smb: {}
    }
    cors: {
      corsRules: []
    }
    shareDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource Microsoft_Storage_storageAccounts_fileServices_storageAccounts_krcaidevmsdssa01_name_default 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_resource
  name: 'default'
  sku: {
    name: 'Standard_LRS'
    tier: 'Standard'
  }
  properties: {
    protocolSettings: {
      smb: {}
    }
    cors: {
      corsRules: []
    }
    shareDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource storageAccounts_krcaidevsa01_name_storageAccounts_krcaidevsa01_name_2c4d113e_8bfb_4637_9423_fe3543ba6009 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: '${storageAccounts_krcaidevsa01_name}.2c4d113e-8bfb-4637-9423-fe3543ba6009'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
      actionRequired: 'None'
    }
  }
}

resource storageAccounts_krcaidevsa01_name_storageAccounts_krcaidevsa01_name_cc06542b_181c_41aa_bd68_8d73859ebc61 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: '${storageAccounts_krcaidevsa01_name}.cc06542b-181c-41aa-bd68-8d73859ebc61'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
      actionRequired: 'None'
    }
  }
}

resource storageAccounts_krcaidevsa01_name_storageAccounts_krcaidevsa01_name_dd7a99d0_513e_4aec_9445_378c21d43a0a 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: '${storageAccounts_krcaidevsa01_name}.dd7a99d0-513e-4aec-9445-378c21d43a0a'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
      actionRequired: 'None'
    }
  }
}

resource storageAccounts_krcaidevsa01_name_storageAccounts_krcaidevsa01_name_dee4e784_90e6_48a9_b09c_d4a6b2b8d80c 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: '${storageAccounts_krcaidevsa01_name}.dee4e784-90e6-48a9-b09c-d4a6b2b8d80c'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
      actionRequired: 'None'
    }
  }
}

resource storageAccounts_krcaidevmsdssa01_name_storageAccounts_krcaidevmsdssa01_name_4987d4c5_8bef_4574_be38_c83072cb7586 'Microsoft.Storage/storageAccounts/privateEndpointConnections@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_resource
  name: '${storageAccounts_krcaidevmsdssa01_name}.4987d4c5-8bef-4574-be38-c83072cb7586'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
      actionRequired: 'None'
    }
  }
}

resource Microsoft_Storage_storageAccounts_queueServices_storageAccounts_krcaidevsa01_name_default 'Microsoft.Storage/storageAccounts/queueServices@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource Microsoft_Storage_storageAccounts_queueServices_storageAccounts_krcaidevmsdssa01_name_default 'Microsoft.Storage/storageAccounts/queueServices@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_resource
  name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource Microsoft_Storage_storageAccounts_tableServices_storageAccounts_krcaidevsa01_name_default 'Microsoft.Storage/storageAccounts/tableServices@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_resource
  name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource Microsoft_Storage_storageAccounts_tableServices_storageAccounts_krcaidevmsdssa01_name_default 'Microsoft.Storage/storageAccounts/tableServices@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_resource
  name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource sites_krc_ai_dev_msds_func_01_name_ftp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'ftp'
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    allow: false
  }
}

resource sites_krc_ai_dev_owui_as_01_name_ftp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: 'ftp'
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    allow: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_scm 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'scm'
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    allow: false
  }
}

resource sites_krc_ai_dev_owui_as_01_name_scm 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: 'scm'
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    allow: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_web 'Microsoft.Web/sites/config@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'web'
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    numberOfWorkers: 1
    defaultDocuments: [
      'Default.htm'
      'Default.html'
      'Default.asp'
      'index.htm'
      'index.html'
      'iisstart.htm'
      'default.aspx'
      'index.php'
    ]
    netFrameworkVersion: 'v4.0'
    linuxFxVersion: 'Python|3.13'
    requestTracingEnabled: false
    remoteDebuggingEnabled: false
    httpLoggingEnabled: false
    acrUseManagedIdentityCreds: false
    logsDirectorySizeLimit: 35
    detailedErrorLoggingEnabled: false
    publishingUsername: 'REDACTED'
    scmType: 'None'
    use32BitWorkerProcess: false
    webSocketsEnabled: false
    alwaysOn: true
    managedPipelineMode: 'Integrated'
    virtualApplications: [
      {
        virtualPath: '/'
        physicalPath: 'site\\wwwroot'
        preloadEnabled: true
      }
    ]
    loadBalancing: 'LeastRequests'
    experiments: {
      rampUpRules: []
    }
    autoHealEnabled: false
    vnetName: 'c381a08e-d376-4a49-8f39-bff0044f2bca_acme-ai-dev-krc-01-vnet-func-subnet'
    vnetRouteAllEnabled: true
    vnetPrivatePortsCount: 0
    publicNetworkAccess: 'Enabled'
    cors: {
      allowedOrigins: [
        'https://portal.azure.com'
      ]
      supportCredentials: false
    }
    localMySqlEnabled: false
    ipSecurityRestrictions: [
      {
        ipAddress: '10.100.0.3/32,10.100.0.4/32'
        action: 'Allow'
        tag: 'Default'
        priority: 100
        name: 'AllowVm'
      }
      {
        ipAddress: '211.215.58.26/32'
        action: 'Allow'
        tag: 'Default'
        priority: 110
        name: 'AllowLocal'
      }
      {
        ipAddress: '10.100.3.0/27'
        action: 'Allow'
        tag: 'Default'
        priority: 120
        name: 'AllowPrivateendpoint'
      }
      {
        ipAddress: 'Any'
        action: 'Deny'
        priority: 2147483647
        name: 'Deny all'
        description: 'Deny all access'
      }
    ]
    ipSecurityRestrictionsDefaultAction: 'Deny'
    scmIpSecurityRestrictions: [
      {
        ipAddress: 'Any'
        action: 'Allow'
        priority: 2147483647
        name: 'Allow all'
        description: 'Allow all access'
      }
    ]
    scmIpSecurityRestrictionsDefaultAction: 'Allow'
    scmIpSecurityRestrictionsUseMain: false
    http20Enabled: false
    minTlsVersion: '1.2'
    scmMinTlsVersion: '1.2'
    ftpsState: 'FtpsOnly'
    preWarmedInstanceCount: 0
    functionAppScaleLimit: 0
    functionsRuntimeScaleMonitoringEnabled: false
    minimumElasticInstanceCount: 0
    azureStorageAccounts: {}
    http20ProxyFlag: 0
  }
}

resource sites_krc_ai_dev_owui_as_01_name_web 'Microsoft.Web/sites/config@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: 'web'
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    numberOfWorkers: 1
    defaultDocuments: [
      'Default.htm'
      'Default.html'
      'Default.asp'
      'index.htm'
      'index.html'
      'iisstart.htm'
      'default.aspx'
      'index.php'
      'hostingstart.html'
    ]
    netFrameworkVersion: 'v4.0'
    linuxFxVersion: 'sitecontainers'
    requestTracingEnabled: false
    remoteDebuggingEnabled: false
    remoteDebuggingVersion: 'VS2022'
    httpLoggingEnabled: false
    acrUseManagedIdentityCreds: true
    acrUserManagedIdentityID: 'f74f43bb-0703-4e6f-94c7-a1040ebf48c7'
    logsDirectorySizeLimit: 35
    detailedErrorLoggingEnabled: false
    publishingUsername: 'REDACTED'
    scmType: 'None'
    use32BitWorkerProcess: true
    webSocketsEnabled: false
    alwaysOn: true
    managedPipelineMode: 'Integrated'
    virtualApplications: [
      {
        virtualPath: '/'
        physicalPath: 'site\\wwwroot'
        preloadEnabled: true
      }
    ]
    loadBalancing: 'LeastRequests'
    experiments: {
      rampUpRules: []
    }
    autoHealEnabled: false
    vnetName: 'c381a08e-d376-4a49-8f39-bff0044f2bca_acme-ai-dev-krc-01-vnet-ap-subnet'
    vnetRouteAllEnabled: true
    vnetPrivatePortsCount: 0
    publicNetworkAccess: 'Enabled'
    localMySqlEnabled: false
    managedServiceIdentityId: 4699
    xManagedServiceIdentityId: 4698
    ipSecurityRestrictions: [
      {
        ipAddress: '10.100.0.3/32,10.100.0.4/32'
        action: 'Allow'
        tag: 'Default'
        priority: 100
        name: 'AllowVm'
      }
      {
        ipAddress: '211.215.58.26/32'
        action: 'Allow'
        tag: 'Default'
        priority: 110
        name: 'AllowCloocusLocal'
        description: 'Cloocus에서 웹앱 접근을 위한 Nat IP 허가'
      }
      {
        ipAddress: '222.234.227.131/32,222.234.227.132/32,222.234.227.133/32,222.234.227.134/32,222.234.227.135/32,222.234.227.136/32'
        action: 'Allow'
        tag: 'Default'
        priority: 110
        name: 'AllowACMELocal'
        description: 'ACME에서 접근을 위한 NAT IP 허용'
      }
      {
        ipAddress: '49.254.29.61/32,118.69.108.33/32,221.243.245.51/32,175.143.125.93/32,86.98.41.40/32'
        action: 'Allow'
        tag: 'Default'
        priority: 110
        name: 'AllowACMELocal2'
      }
      {
        ipAddress: '10.100.3.0/27'
        action: 'Allow'
        tag: 'Default'
        priority: 120
        name: 'AllowPrivateendpoint'
      }
      {
        ipAddress: '218.25.176.140/32'
        action: 'Allow'
        tag: 'Default'
        priority: 120
        name: 'AllowACMEChina'
      }
      {
        ipAddress: 'Any'
        action: 'Deny'
        priority: 2147483647
        name: 'Deny all'
        description: 'Deny all access'
      }
    ]
    ipSecurityRestrictionsDefaultAction: 'Deny'
    scmIpSecurityRestrictions: [
      {
        ipAddress: 'Any'
        action: 'Allow'
        priority: 2147483647
        name: 'Allow all'
        description: 'Allow all access'
      }
    ]
    scmIpSecurityRestrictionsDefaultAction: 'Allow'
    scmIpSecurityRestrictionsUseMain: false
    http20Enabled: false
    minTlsVersion: '1.2'
    scmMinTlsVersion: '1.2'
    ftpsState: 'FtpsOnly'
    preWarmedInstanceCount: 0
    elasticWebAppScaleLimit: 0
    functionsRuntimeScaleMonitoringEnabled: false
    minimumElasticInstanceCount: 1
    azureStorageAccounts: {
      azfile: {
        type: 'AzureFiles'
        accountName: 'krcaidevmsdssa01'
        shareName: 'fsowui'
        mountPath: '/app/backend/data'
        protocol: 'Smb'
      }
    }
    http20ProxyFlag: 0
  }
}

resource sites_krc_ai_dev_msds_func_01_name_b00588cf_59b6_48f2_8fc6_e3acfce8f847 'Microsoft.Web/sites/deployments@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'b00588cf-59b6-48f2-8fc6-e3acfce8f847'
  location: 'Korea Central'
  properties: {
    status: 4
    author_email: 'N/A'
    author: 'krc-ai-dev-dev-linux-vm02'
    deployer: 'Push-Deployer'
    message: 'Created via a push deployment'
    start_time: '2025-12-30T06:20:20.9725049Z'
    end_time: '2025-12-30T06:21:46.0792982Z'
    active: true
  }
}

resource sites_krc_ai_dev_msds_func_01_name_ecf0172a_c4a9_4541_aa56_c8786c2a03ec 'Microsoft.Web/sites/deployments@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'ecf0172a-c4a9-4541-aa56-c8786c2a03ec'
  location: 'Korea Central'
  properties: {
    status: 4
    author_email: 'N/A'
    author: 'krc-ai-dev-dev-linux-vm02'
    deployer: 'Push-Deployer'
    message: 'Created via a push deployment'
    start_time: '2025-12-26T06:45:33.2853952Z'
    end_time: '2025-12-26T06:46:48.5190759Z'
    active: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_fd3e56fb_dda3_4b0f_ab54_6ccd126f2ed7 'Microsoft.Web/sites/deployments@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'fd3e56fb-dda3-4b0f-ab54-6ccd126f2ed7'
  location: 'Korea Central'
  properties: {
    status: 4
    author_email: 'N/A'
    author: 'krc-ai-dev-dev-linux-vm02'
    deployer: 'Push-Deployer'
    message: 'Created via a push deployment'
    start_time: '2025-12-26T07:05:26.0794669Z'
    end_time: '2025-12-26T07:06:33.7792267Z'
    active: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_get_result 'Microsoft.Web/sites/functions@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'get_result'
  location: 'Korea Central'
  properties: {
    script_href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/vfs/home/site/wwwroot/function_app.py'
    href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/functions/get_result'
    config: {
      name: 'get_result'
      entryPoint: 'get_result'
      scriptFile: 'function_app.py'
      language: 'python'
      functionDirectory: '/home/site/wwwroot'
      bindings: [
        {
          direction: 'IN'
          type: 'httpTrigger'
          name: 'req'
          methods: [
            'GET'
          ]
          authLevel: 'FUNCTION'
          route: 'results/{blob_name}'
        }
        {
          direction: 'OUT'
          type: 'http'
          name: '$return'
        }
      ]
    }
    invoke_url_template: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/api/results/{blob_name}'
    language: 'python'
    isDisabled: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_health_check 'Microsoft.Web/sites/functions@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'health_check'
  location: 'Korea Central'
  properties: {
    script_href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/vfs/home/site/wwwroot/function_app.py'
    href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/functions/health_check'
    config: {
      name: 'health_check'
      entryPoint: 'health_check'
      scriptFile: 'function_app.py'
      language: 'python'
      functionDirectory: '/home/site/wwwroot'
      bindings: [
        {
          direction: 'IN'
          type: 'httpTrigger'
          name: 'req'
          methods: [
            'GET'
          ]
          authLevel: 'FUNCTION'
          route: 'health'
        }
        {
          direction: 'OUT'
          type: 'http'
          name: '$return'
        }
      ]
    }
    invoke_url_template: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/api/health'
    language: 'python'
    isDisabled: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_list_results 'Microsoft.Web/sites/functions@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'list_results'
  location: 'Korea Central'
  properties: {
    script_href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/vfs/home/site/wwwroot/function_app.py'
    href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/functions/list_results'
    config: {
      name: 'list_results'
      entryPoint: 'list_results'
      scriptFile: 'function_app.py'
      language: 'python'
      functionDirectory: '/home/site/wwwroot'
      bindings: [
        {
          direction: 'IN'
          type: 'httpTrigger'
          name: 'req'
          methods: [
            'GET'
          ]
          authLevel: 'FUNCTION'
          route: 'results'
        }
        {
          direction: 'OUT'
          type: 'http'
          name: '$return'
        }
      ]
    }
    invoke_url_template: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/api/results'
    language: 'python'
    isDisabled: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_msds_blob_trigger_en 'Microsoft.Web/sites/functions@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'msds_blob_trigger_en'
  location: 'Korea Central'
  properties: {
    script_href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/vfs/home/site/wwwroot/function_app.py'
    href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/functions/msds_blob_trigger_en'
    config: {
      name: 'msds_blob_trigger_en'
      entryPoint: 'msds_blob_trigger_en'
      scriptFile: 'function_app.py'
      language: 'python'
      functionDirectory: '/home/site/wwwroot'
      bindings: [
        {
          direction: 'IN'
          type: 'blobTrigger'
          name: 'myblob'
          path: 'msds/EN/{name}.pdf'
          connection: 'BlobStorageConnectionString'
        }
      ]
    }
    language: 'python'
    isDisabled: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_msds_blob_trigger_zh 'Microsoft.Web/sites/functions@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'msds_blob_trigger_zh'
  location: 'Korea Central'
  properties: {
    script_href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/vfs/home/site/wwwroot/function_app.py'
    href: 'https://krc-ai-dev-msds-func-01-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net/admin/functions/msds_blob_trigger_zh'
    config: {
      name: 'msds_blob_trigger_zh'
      entryPoint: 'msds_blob_trigger_zh'
      scriptFile: 'function_app.py'
      language: 'python'
      functionDirectory: '/home/site/wwwroot'
      bindings: [
        {
          direction: 'IN'
          type: 'blobTrigger'
          name: 'myblob'
          path: 'msds/ZH/{name}.pdf'
          connection: 'BlobStorageConnectionString'
        }
      ]
    }
    language: 'python'
    isDisabled: false
  }
}

resource sites_krc_ai_dev_msds_func_01_name_sites_krc_ai_dev_msds_func_01_name_aha0fzgjdrgjhzfh_koreacentral_01_azurewebsites_net 'Microsoft.Web/sites/hostNameBindings@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: '${sites_krc_ai_dev_msds_func_01_name}-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net'
  location: 'Korea Central'
  properties: {
    siteName: 'krc-ai-dev-msds-func-01'
    hostNameType: 'Verified'
  }
}

resource sites_krc_ai_dev_owui_as_01_name_sites_krc_ai_dev_owui_as_01_name_gqf5guftecdrd7cm_koreacentral_01_azurewebsites_net 'Microsoft.Web/sites/hostNameBindings@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: '${sites_krc_ai_dev_owui_as_01_name}-gqf5guftecdrd7cm.koreacentral-01.azurewebsites.net'
  location: 'Korea Central'
  properties: {
    siteName: 'krc-ai-dev-owui-as-01'
    hostNameType: 'Verified'
  }
}

resource sites_krc_ai_dev_msds_func_01_name_sites_krc_ai_dev_msds_func_01_name_pri_ed_f1e9f897_0638_4636_b253_54d4900dfa52 'Microsoft.Web/sites/privateEndpointConnections@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: '${sites_krc_ai_dev_msds_func_01_name}-pri-ed-f1e9f897-0638-4636-b253-54d4900dfa52'
  location: 'Korea Central'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      actionsRequired: 'None'
    }
    ipAddresses: [
      '10.100.3.10'
    ]
  }
}

resource sites_krc_ai_dev_owui_as_01_name_sites_krc_ai_dev_owui_as_01_name_pri_ed_ae61de91_0bd4_4a3c_b962_f93d7834ccfc 'Microsoft.Web/sites/privateEndpointConnections@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: '${sites_krc_ai_dev_owui_as_01_name}-pri-ed-ae61de91-0bd4-4a3c-b962-f93d7834ccfc'
  location: 'Korea Central'
  properties: {
    privateEndpoint: {}
    privateLinkServiceConnectionState: {
      status: 'Approved'
      actionsRequired: 'None'
    }
    ipAddresses: [
      '10.100.3.14'
    ]
  }
}

resource sites_krc_ai_dev_owui_as_01_name_main 'Microsoft.Web/sites/sitecontainers@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: 'main'
  location: 'Korea Central'
  properties: {
    image: 'krcaidevacr01.azurecr.io/eacmerag:latest'
    isMain: true
    authType: 'UserAssigned'
    userManagedIdentityClientId: 'f74f43bb-0703-4e6f-94c7-a1040ebf48c7'
    volumeMounts: []
    environmentVariables: []
    inheritAppSettingsAndConnectionStrings: true
  }
}

resource registries_krcaidevacr01_name_registries_krcaidevacr01_name_5e289f8040f8458b8e098bc697747763 'Microsoft.ContainerRegistry/registries/privateEndpointConnections@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: '${registries_krcaidevacr01_name}.5e289f8040f8458b8e098bc697747763'
  properties: {
    privateEndpoint: {
      id: privateEndpoints_krcaidevacr01_pri_ed_name_resource.id
    }
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-Approved'
    }
  }
}

resource registries_krcaidevacr01_name_push_Tocken 'Microsoft.ContainerRegistry/registries/tokens@2025-05-01-preview' = {
  parent: registries_krcaidevacr01_name_resource
  name: 'push-Tocken'
  properties: {
    scopeMapId: registries_krcaidevacr01_name_repositories_push.id
    credentials: {
      passwords: [
        {
          creationTime: '2025-12-02T04:16:04.6371143+00:00'
          name: 'password1'
        }
      ]
    }
    status: 'enabled'
  }
}

resource networkInterfaces_krc_ai_dev_dev_linux_vm01239_z1_name_resource 'Microsoft.Network/networkInterfaces@2024-07-01' = {
  name: networkInterfaces_krc_ai_dev_dev_linux_vm01239_z1_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  kind: 'Regular'
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        id: '${networkInterfaces_krc_ai_dev_dev_linux_vm01239_z1_name_resource.id}/ipConfigurations/ipconfig1'
        type: 'Microsoft.Network/networkInterfaces/ipConfigurations'
        properties: {
          privateIPAddress: '10.100.0.4'
          privateIPAllocationMethod: 'Static'
          publicIPAddress: {
            id: publicIPAddresses_krc_ai_dev_dev_pip_01_name_resource.id
            properties: {
              deleteOption: 'Detach'
            }
          }
          subnet: {
            id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
          }
          primary: true
          privateIPAddressVersion: 'IPv4'
        }
      }
    ]
    dnsSettings: {
      dnsServers: []
    }
    enableAcceleratedNetworking: true
    enableIPForwarding: false
    disableTcpStateTracking: false
    nicType: 'Standard'
    auxiliaryMode: 'None'
    auxiliarySku: 'None'
  }
}

resource networkInterfaces_krc_ai_dev_dev_linux_vm02716_z1_name_resource 'Microsoft.Network/networkInterfaces@2024-07-01' = {
  name: networkInterfaces_krc_ai_dev_dev_linux_vm02716_z1_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  kind: 'Regular'
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        id: '${networkInterfaces_krc_ai_dev_dev_linux_vm02716_z1_name_resource.id}/ipConfigurations/ipconfig1'
        type: 'Microsoft.Network/networkInterfaces/ipConfigurations'
        properties: {
          privateIPAddress: '10.100.0.5'
          privateIPAllocationMethod: 'Static'
          publicIPAddress: {
            id: publicIPAddresses_krc_ai_dev_dev_pip_02_name_resource.id
            properties: {
              deleteOption: 'Detach'
            }
          }
          subnet: {
            id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
          }
          primary: true
          privateIPAddressVersion: 'IPv4'
        }
      }
    ]
    dnsSettings: {
      dnsServers: []
    }
    enableAcceleratedNetworking: true
    enableIPForwarding: false
    disableTcpStateTracking: false
    nicType: 'Standard'
    auxiliaryMode: 'None'
    auxiliarySku: 'None'
  }
}

resource privateDnsZones_privatelink_queue_core_windows_net_name_krcaidevsa01_link_9f0e 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_queue_core_windows_net_name_resource
  name: 'krcaidevsa01-link-9f0e'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_file_core_windows_net_name_krcaidevsa01_link_ad95 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_file_core_windows_net_name_resource
  name: 'krcaidevsa01-link-ad95'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_table_core_windows_net_name_krcaidevsa01_link_bd86 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_table_core_windows_net_name_resource
  name: 'krcaidevsa01-link-bd86'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_azurewebsites_net_name_krc_ai_dev_msds_func_01_link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurewebsites_net_name_resource
  name: 'krc-ai-dev-msds-func-01-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_azurecr_io_name_ya7sg46e6z5fk 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_azurecr_io_name_resource
  name: 'ya7sg46e6z5fk'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_blob_core_windows_net_name_ya7sg46e6z5fk 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_blob_core_windows_net_name_resource
  name: 'ya7sg46e6z5fk'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_cognitiveservices_azure_com_name_ya7sg46e6z5fk 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_cognitiveservices_azure_com_name_resource
  name: 'ya7sg46e6z5fk'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_openai_azure_com_name_ya7sg46e6z5fk 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_openai_azure_com_name_resource
  name: 'ya7sg46e6z5fk'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_redis_cache_windows_net_name_ya7sg46e6z5fk 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_redis_cache_windows_net_name_resource
  name: 'ya7sg46e6z5fk'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateDnsZones_privatelink_search_windows_net_name_ya7sg46e6z5fk 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZones_privatelink_search_windows_net_name_resource
  name: 'ya7sg46e6z5fk'
  location: 'global'
  properties: {
    registrationEnabled: false
    resolutionPolicy: 'Default'
    virtualNetwork: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource.id
    }
  }
}

resource privateEndpoints_krcaidevacr01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krcaidevacr01_pri_ed_name
  location: 'koreacentral'
  properties: {
    privateLinkServiceConnections: [
      {
        name: '${privateEndpoints_krcaidevacr01_pri_ed_name}_886ff34d-a39b-4e7f-9f08-cb0fad579013'
        id: '${privateEndpoints_krcaidevacr01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krcaidevacr01_pri_ed_name}_886ff34d-a39b-4e7f-9f08-cb0fad579013'
        properties: {
          privateLinkServiceId: registries_krcaidevacr01_name_resource.id
          groupIds: [
            'registry'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: [
      {
        fqdn: 'krcaidevacr01.koreacentral.data.azurecr.io'
        ipAddresses: [
          '10.100.3.5'
        ]
      }
      {
        fqdn: 'krcaidevacr01.azurecr.io'
        ipAddresses: [
          '10.100.3.8'
        ]
      }
    ]
  }
}

resource privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    privateLinkServiceConnections: [
      {
        name: privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name
        id: '${privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name}'
        properties: {
          privateLinkServiceId: accounts_krc_ai_dev_docitg_01_name_resource.id
          groupIds: [
            'account'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    customNetworkInterfaceName: '${privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name}-nic'
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name
  location: 'koreacentral'
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'blobPrivateLinkConnection'
        id: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name_resource.id}/privateLinkServiceConnections/blobPrivateLinkConnection'
        properties: {
          privateLinkServiceId: storageAccounts_krcaidevsa01_name_resource.id
          groupIds: [
            'blob'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name
  location: 'koreacentral'
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'filePrivateLinkConnection'
        id: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name_resource.id}/privateLinkServiceConnections/filePrivateLinkConnection'
        properties: {
          privateLinkServiceId: storageAccounts_krcaidevsa01_name_resource.id
          groupIds: [
            'file'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name
  location: 'koreacentral'
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'queuePrivateLinkConnection'
        id: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name_resource.id}/privateLinkServiceConnections/queuePrivateLinkConnection'
        properties: {
          privateLinkServiceId: storageAccounts_krcaidevsa01_name_resource.id
          groupIds: [
            'queue'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name
  location: 'koreacentral'
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'tablePrivateLinkConnection'
        id: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name_resource.id}/privateLinkServiceConnections/tablePrivateLinkConnection'
        properties: {
          privateLinkServiceId: storageAccounts_krcaidevsa01_name_resource.id
          groupIds: [
            'table'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    privateLinkServiceConnections: [
      {
        name: privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name
        id: '${privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name}'
        properties: {
          privateLinkServiceId: sites_krc_ai_dev_msds_func_01_name_resource.id
          groupIds: [
            'sites'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krcaidevmsdssa01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krcaidevmsdssa01_pri_ed_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    privateLinkServiceConnections: [
      {
        name: '${privateEndpoints_krcaidevmsdssa01_pri_ed_name}_4f9cb560-3ee3-4a7e-ba7f-4b59350c4013'
        id: '${privateEndpoints_krcaidevmsdssa01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krcaidevmsdssa01_pri_ed_name}_4f9cb560-3ee3-4a7e-ba7f-4b59350c4013'
        properties: {
          privateLinkServiceId: storageAccounts_krcaidevmsdssa01_name_resource.id
          groupIds: [
            'blob'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: [
      {
        fqdn: 'krcaidevmsdssa01.blob.core.windows.net'
        ipAddresses: [
          '10.100.3.4'
        ]
      }
    ]
  }
}

resource privateEndpoints_krc_ai_dev_openai_01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krc_ai_dev_openai_01_pri_ed_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    privateLinkServiceConnections: [
      {
        name: privateEndpoints_krc_ai_dev_openai_01_pri_ed_name
        id: '${privateEndpoints_krc_ai_dev_openai_01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krc_ai_dev_openai_01_pri_ed_name}'
        properties: {
          privateLinkServiceId: accounts_krc_ai_dev_openai_01_name_resource.id
          groupIds: [
            'account'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    customNetworkInterfaceName: '${privateEndpoints_krc_ai_dev_openai_01_pri_ed_name}-nic'
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    privateLinkServiceConnections: [
      {
        name: privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name
        id: '${privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name}'
        properties: {
          privateLinkServiceId: sites_krc_ai_dev_owui_as_01_name_resource.id
          groupIds: [
            'sites'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krc_ai_dev_rds_01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krc_ai_dev_rds_01_pri_ed_name
  location: 'koreacentral'
  properties: {
    privateLinkServiceConnections: [
      {
        name: '${privateEndpoints_krc_ai_dev_rds_01_pri_ed_name}_68912788-745c-4ab5-987b-ded9358ad028'
        id: '${privateEndpoints_krc_ai_dev_rds_01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krc_ai_dev_rds_01_pri_ed_name}_68912788-745c-4ab5-987b-ded9358ad028'
        properties: {
          privateLinkServiceId: Redis_krc_ai_dev_rds_01_name_resource.id
          groupIds: [
            'redisCache'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: []
  }
}

resource privateEndpoints_krc_ai_dev_search_01_pri_ed_name_resource 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: privateEndpoints_krc_ai_dev_search_01_pri_ed_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    privateLinkServiceConnections: [
      {
        name: '${privateEndpoints_krc_ai_dev_search_01_pri_ed_name}_68912788-745c-4ab5-987b-ded9358ad03d'
        id: '${privateEndpoints_krc_ai_dev_search_01_pri_ed_name_resource.id}/privateLinkServiceConnections/${privateEndpoints_krc_ai_dev_search_01_pri_ed_name}_68912788-745c-4ab5-987b-ded9358ad03d'
        properties: {
          privateLinkServiceId: searchServices_krc_ai_dev_search_01_name_resource.id
          groupIds: [
            'searchService'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    manualPrivateLinkServiceConnections: []
    subnet: {
      id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
    }
    ipConfigurations: []
    customDnsConfigs: [
      {
        fqdn: 'krc-ai-dev-search-01.search.windows.net'
        ipAddresses: [
          '10.100.3.7'
        ]
      }
    ]
  }
}

resource privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name_default 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name}/default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-cognitiveservices-azure-com'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_cognitiveservices_azure_com_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krc_ai_dev_docitg_01_pri_ed_name_resource
  ]
}

resource privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name_default 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name}/default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.azurewebsites.net-config'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_azurewebsites_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krc_ai_dev_msds_func_01_pri_ed_name_resource
  ]
}

resource privateEndpoints_krc_ai_dev_openai_01_pri_ed_name_default 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krc_ai_dev_openai_01_pri_ed_name}/default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-openai-azure-com'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_openai_azure_com_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krc_ai_dev_openai_01_pri_ed_name_resource
  ]
}

resource privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name_default 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name}/default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.azurewebsites.net-config'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_azurewebsites_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krc_ai_dev_owui_as_01_pri_ed_name_resource
  ]
}

resource privateEndpoints_krc_ai_dev_rds_01_pri_ed_name_default 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krc_ai_dev_rds_01_pri_ed_name}/default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-redis-cache-windows-net'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_redis_cache_windows_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krc_ai_dev_rds_01_pri_ed_name_resource
  ]
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name_krcaidevsa01_blob_private_endpoint 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name}/krcaidevsa01-blob-private-endpoint'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.blob.core.windows.net-config'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_blob_core_windows_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_blob_private_endpoint_name_resource
  ]
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name_krcaidevsa01_file_private_endpoint 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name}/krcaidevsa01-file-private-endpoint'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.file.core.windows.net-config'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_file_core_windows_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_file_private_endpoint_name_resource
  ]
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name_krcaidevsa01_queue_private_endpoint 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name}/krcaidevsa01-queue-private-endpoint'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.queue.core.windows.net-config'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_queue_core_windows_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_queue_private_endpoint_name_resource
  ]
}

resource privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name_krcaidevsa01_table_private_endpoint 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  name: '${privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name}/krcaidevsa01-table-private-endpoint'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink.table.core.windows.net-config'
        properties: {
          privateDnsZoneId: privateDnsZones_privatelink_table_core_windows_net_name_resource.id
        }
      }
    ]
  }
  dependsOn: [
    privateEndpoints_krcaidevsa01_pri_ed_krcaidevsa01_table_private_endpoint_name_resource
  ]
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-ap-subnet'
  properties: {
    addressPrefixes: [
      '10.100.1.0/26'
    ]
    networkSecurityGroup: {
      id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_resource.id
    }
    serviceEndpoints: [
      {
        service: 'Microsoft.Storage'
        locations: [
          'koreacentral'
          'koreasouth'
        ]
      }
      {
        service: 'Microsoft.CognitiveServices'
        locations: [
          '*'
        ]
      }
    ]
    delegations: [
      {
        name: 'delegation'
        id: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id}/delegations/delegation'
        properties: {
          serviceName: 'Microsoft.Web/serverfarms'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets/delegations'
      }
    ]
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_etc_subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-etc-subnet'
  properties: {
    addressPrefixes: [
      '10.100.5.0/27'
    ]
    networkSecurityGroup: {
      id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_etc_subnet_nsg_name_resource.id
    }
    serviceEndpoints: [
      {
        service: 'Microsoft.Storage'
        locations: [
          'koreacentral'
          'koreasouth'
        ]
      }
      {
        service: 'Microsoft.CognitiveServices'
        locations: [
          '*'
        ]
      }
    ]
    delegations: []
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-func-subnet'
  properties: {
    addressPrefixes: [
      '10.100.2.0/27'
    ]
    networkSecurityGroup: {
      id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_resource.id
    }
    serviceEndpoints: [
      {
        service: 'Microsoft.Storage'
        locations: [
          'koreacentral'
          'koreasouth'
        ]
      }
      {
        service: 'Microsoft.CognitiveServices'
        locations: [
          '*'
        ]
      }
    ]
    delegations: [
      {
        name: 'delegation'
        id: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id}/delegations/delegation'
        properties: {
          serviceName: 'Microsoft.Web/serverfarms'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets/delegations'
      }
    ]
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet 'Microsoft.Network/virtualNetworks/subnets@2024-07-01' = {
  name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}/${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-vm-subnet'
  properties: {
    addressPrefixes: [
      '10.100.0.0/27'
    ]
    networkSecurityGroup: {
      id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource.id
    }
    serviceEndpoints: [
      {
        service: 'Microsoft.Storage'
        locations: [
          'koreacentral'
          'koreasouth'
        ]
      }
      {
        service: 'Microsoft.CognitiveServices'
        locations: [
          '*'
        ]
      }
    ]
    delegations: []
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
  dependsOn: [
    virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource
  ]
}

resource searchServices_krc_ai_dev_search_01_name_searchServices_krc_ai_dev_search_01_name_pri_ed_da6a8b25_dcc0_4056_ae4b_34c6c8b09953 'Microsoft.Search/searchServices/privateEndpointConnections@2025-05-01' = {
  parent: searchServices_krc_ai_dev_search_01_name_resource
  name: '${searchServices_krc_ai_dev_search_01_name}-pri-ed.da6a8b25-dcc0-4056-ae4b-34c6c8b09953'
  properties: {
    privateEndpoint: {
      id: privateEndpoints_krc_ai_dev_search_01_pri_ed_name_resource.id
    }
    privateLinkServiceConnectionState: {
      status: 'Approved'
      description: 'Auto-approved'
      actionsRequired: 'None'
    }
    provisioningState: 'Succeeded'
    groupId: 'searchService'
  }
}

resource searchServices_krc_ai_dev_search_01_name_AISerchtoOpenAI_pri_link_02 'Microsoft.Search/searchServices/sharedPrivateLinkResources@2025-05-01' = {
  parent: searchServices_krc_ai_dev_search_01_name_resource
  name: 'AISerchtoOpenAI-pri-link-02'
  properties: {
    privateLinkResourceId: accounts_krc_ai_dev_openai_01_name_resource.id
    groupId: 'openai_account'
    requestMessage: 'request'
    status: 'Approved'
    provisioningState: 'Succeeded'
  }
}

resource storageAccounts_krcaidevsa01_name_default_azure_webjobs_hosts 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_default
  name: 'azure-webjobs-hosts'
  properties: {
    immutableStorageWithVersioning: {
      enabled: false
    }
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
  dependsOn: [
    storageAccounts_krcaidevsa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_azure_webjobs_hosts 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_default
  name: 'azure-webjobs-hosts'
  properties: {
    immutableStorageWithVersioning: {
      enabled: false
    }
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevsa01_name_default_azure_webjobs_secrets 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: storageAccounts_krcaidevsa01_name_default
  name: 'azure-webjobs-secrets'
  properties: {
    immutableStorageWithVersioning: {
      enabled: false
    }
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
  dependsOn: [
    storageAccounts_krcaidevsa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_azure_webjobs_secrets 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_default
  name: 'azure-webjobs-secrets'
  properties: {
    immutableStorageWithVersioning: {
      enabled: false
    }
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_msds 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: storageAccounts_krcaidevmsdssa01_name_default
  name: 'msds'
  properties: {
    immutableStorageWithVersioning: {
      enabled: false
    }
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: false
    publicAccess: 'None'
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_fsowui 'Microsoft.Storage/storageAccounts/fileServices/shares@2025-01-01' = {
  parent: Microsoft_Storage_storageAccounts_fileServices_storageAccounts_krcaidevmsdssa01_name_default
  name: 'fsowui'
  properties: {
    accessTier: 'Hot'
    shareQuota: 102400
    enabledProtocols: 'SMB'
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_azure_webjobs_blobtrigger_krcaidevdevlinuxvm02_904743189 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-01-01' = {
  parent: Microsoft_Storage_storageAccounts_queueServices_storageAccounts_krcaidevmsdssa01_name_default
  name: 'azure-webjobs-blobtrigger-krcaidevdevlinuxvm02-904743189'
  properties: {
    metadata: {}
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevsa01_name_default_azure_webjobs_blobtrigger_krc_ai_dev_msds_func_01 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-01-01' = {
  parent: Microsoft_Storage_storageAccounts_queueServices_storageAccounts_krcaidevsa01_name_default
  name: 'azure-webjobs-blobtrigger-krc-ai-dev-msds-func-01'
  properties: {
    metadata: {}
  }
  dependsOn: [
    storageAccounts_krcaidevsa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_azure_webjobs_blobtrigger_ljhpark_2002630290 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-01-01' = {
  parent: Microsoft_Storage_storageAccounts_queueServices_storageAccounts_krcaidevmsdssa01_name_default
  name: 'azure-webjobs-blobtrigger-ljhpark-2002630290'
  properties: {
    metadata: {}
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevmsdssa01_name_default_webjobs_blobtrigger_poison 'Microsoft.Storage/storageAccounts/queueServices/queues@2025-01-01' = {
  parent: Microsoft_Storage_storageAccounts_queueServices_storageAccounts_krcaidevmsdssa01_name_default
  name: 'webjobs-blobtrigger-poison'
  properties: {
    metadata: {}
  }
  dependsOn: [
    storageAccounts_krcaidevmsdssa01_name_resource
  ]
}

resource storageAccounts_krcaidevsa01_name_default_AzureFunctionsDiagnosticEvents202512 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-01-01' = {
  parent: Microsoft_Storage_storageAccounts_tableServices_storageAccounts_krcaidevsa01_name_default
  name: 'AzureFunctionsDiagnosticEvents202512'
  properties: {}
  dependsOn: [
    storageAccounts_krcaidevsa01_name_resource
  ]
}

resource sites_krc_ai_dev_msds_func_01_name_resource 'Microsoft.Web/sites@2024-11-01' = {
  name: sites_krc_ai_dev_msds_func_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  kind: 'functionapp,linux'
  properties: {
    enabled: true
    hostNameSslStates: [
      {
        name: '${sites_krc_ai_dev_msds_func_01_name}-aha0fzgjdrgjhzfh.koreacentral-01.azurewebsites.net'
        sslState: 'Disabled'
        hostType: 'Standard'
      }
      {
        name: '${sites_krc_ai_dev_msds_func_01_name}-aha0fzgjdrgjhzfh.scm.koreacentral-01.azurewebsites.net'
        sslState: 'Disabled'
        hostType: 'Repository'
      }
    ]
    serverFarmId: serverfarms_krc_ai_dev_msds_p1v3_asp_01_name_resource.id
    reserved: true
    isXenon: false
    hyperV: false
    dnsConfiguration: {}
    outboundVnetRouting: {
      allTraffic: false
      applicationTraffic: true
      contentShareTraffic: false
      imagePullTraffic: false
      backupRestoreTraffic: false
    }
    siteConfig: {
      numberOfWorkers: 1
      linuxFxVersion: 'Python|3.13'
      acrUseManagedIdentityCreds: false
      alwaysOn: true
      http20Enabled: false
      functionAppScaleLimit: 0
      minimumElasticInstanceCount: 0
    }
    scmSiteAlsoStopped: false
    clientAffinityEnabled: false
    clientAffinityProxyEnabled: false
    clientCertEnabled: false
    clientCertMode: 'Required'
    hostNamesDisabled: false
    ipMode: 'IPv4'
    customDomainVerificationId: '583359B150A258CAD9C0F47C800AAAFF8624D9B464B232288C3369BE1E051195'
    containerSize: 1536
    dailyMemoryTimeQuota: 0
    httpsOnly: true
    endToEndEncryptionEnabled: false
    redundancyMode: 'None'
    publicNetworkAccess: 'Enabled'
    storageAccountRequired: false
    virtualNetworkSubnetId: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
    keyVaultReferenceIdentity: 'SystemAssigned'
    autoGeneratedDomainNameLabelScope: 'TenantReuse'
  }
}

resource sites_krc_ai_dev_owui_as_01_name_resource 'Microsoft.Web/sites@2024-11-01' = {
  name: sites_krc_ai_dev_owui_as_01_name
  location: 'Korea Central'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${acrManagedIdentityId}': {}
    }
  }
  properties: {
    enabled: true
    hostNameSslStates: [
      {
        name: '${sites_krc_ai_dev_owui_as_01_name}-gqf5guftecdrd7cm.koreacentral-01.azurewebsites.net'
        sslState: 'Disabled'
        hostType: 'Standard'
      }
      {
        name: '${sites_krc_ai_dev_owui_as_01_name}-gqf5guftecdrd7cm.scm.koreacentral-01.azurewebsites.net'
        sslState: 'Disabled'
        hostType: 'Repository'
      }
    ]
    serverFarmId: serverfarms_krc_ai_dev_owui_p0v3_asp_01_name_resource.id
    reserved: true
    isXenon: false
    hyperV: false
    dnsConfiguration: {}
    outboundVnetRouting: {
      allTraffic: false
      applicationTraffic: true
      contentShareTraffic: false
      imagePullTraffic: true
      backupRestoreTraffic: false
    }
    siteConfig: {
      numberOfWorkers: 1
      linuxFxVersion: 'sitecontainers'
      acrUseManagedIdentityCreds: true
      alwaysOn: true
      http20Enabled: false
      functionAppScaleLimit: 0
      minimumElasticInstanceCount: 1
    }
    scmSiteAlsoStopped: false
    clientAffinityEnabled: true
    clientAffinityProxyEnabled: false
    clientCertEnabled: false
    clientCertMode: 'Required'
    hostNamesDisabled: false
    ipMode: 'IPv4'
    customDomainVerificationId: '583359B150A258CAD9C0F47C800AAAFF8624D9B464B232288C3369BE1E051195'
    containerSize: 0
    dailyMemoryTimeQuota: 0
    httpsOnly: true
    endToEndEncryptionEnabled: false
    redundancyMode: 'None'
    publicNetworkAccess: 'Enabled'
    storageAccountRequired: false
    virtualNetworkSubnetId: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
    keyVaultReferenceIdentity: 'SystemAssigned'
    autoGeneratedDomainNameLabelScope: 'TenantReuse'
    sshEnabled: true
  }
}

resource sites_krc_ai_dev_owui_as_01_name_c381a08e_d376_4a49_8f39_bff0044f2bca_acme_ai_dev_krc_01_vnet_ap_subnet 'Microsoft.Web/sites/virtualNetworkConnections@2024-11-01' = {
  parent: sites_krc_ai_dev_owui_as_01_name_resource
  name: 'c381a08e-d376-4a49-8f39-bff0044f2bca_acme-ai-dev-krc-01-vnet-ap-subnet'
  location: 'Korea Central'
  properties: {
    vnetResourceId: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
    isSwift: true
  }
}

resource sites_krc_ai_dev_msds_func_01_name_c381a08e_d376_4a49_8f39_bff0044f2bca_acme_ai_dev_krc_01_vnet_func_subnet 'Microsoft.Web/sites/virtualNetworkConnections@2024-11-01' = {
  parent: sites_krc_ai_dev_msds_func_01_name_resource
  name: 'c381a08e-d376-4a49-8f39-bff0044f2bca_acme-ai-dev-krc-01-vnet-func-subnet'
  location: 'Korea Central'
  properties: {
    vnetResourceId: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
    isSwift: true
  }
}

resource virtualNetworks_acme_ai_dev_krc_01_vnet_name_resource 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: virtualNetworks_acme_ai_dev_krc_01_vnet_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.100.0.0/21'
      ]
    }
    privateEndpointVNetPolicies: 'Disabled'
    subnets: [
      {
        name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-vm-subnet'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
        properties: {
          addressPrefixes: [
            '10.100.0.0/27'
          ]
          networkSecurityGroup: {
            id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_vm_subnet_nsg_name_resource.id
          }
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                'koreacentral'
                'koreasouth'
              ]
            }
            {
              service: 'Microsoft.CognitiveServices'
              locations: [
                '*'
              ]
            }
          ]
          delegations: []
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets'
      }
      {
        name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-etc-subnet'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_etc_subnet.id
        properties: {
          addressPrefixes: [
            '10.100.5.0/27'
          ]
          networkSecurityGroup: {
            id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_etc_subnet_nsg_name_resource.id
          }
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                'koreacentral'
                'koreasouth'
              ]
            }
            {
              service: 'Microsoft.CognitiveServices'
              locations: [
                '*'
              ]
            }
          ]
          delegations: []
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets'
      }
      {
        name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-pe-subnet'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
        properties: {
          addressPrefixes: [
            '10.100.3.0/27'
          ]
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                'koreacentral'
                'koreasouth'
              ]
            }
            {
              service: 'Microsoft.CognitiveServices'
              locations: [
                '*'
              ]
            }
          ]
          delegations: []
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets'
      }
      {
        name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-pgsqlfx-subnet'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id
        properties: {
          addressPrefixes: [
            '10.100.4.0/27'
          ]
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                'koreacentral'
                'koreasouth'
              ]
            }
            {
              service: 'Microsoft.CognitiveServices'
              locations: [
                '*'
              ]
            }
          ]
          delegations: [
            {
              name: 'dlg-Microsoft.DBforPostgreSQL-flexibleServers'
              id: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id}/delegations/dlg-Microsoft.DBforPostgreSQL-flexibleServers'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
              type: 'Microsoft.Network/virtualNetworks/subnets/delegations'
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets'
      }
      {
        name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-func-subnet'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
        properties: {
          addressPrefixes: [
            '10.100.2.0/27'
          ]
          networkSecurityGroup: {
            id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_func_subnet_nsg_name_resource.id
          }
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                'koreacentral'
                'koreasouth'
              ]
            }
            {
              service: 'Microsoft.CognitiveServices'
              locations: [
                '*'
              ]
            }
          ]
          delegations: [
            {
              name: 'delegation'
              id: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id}/delegations/delegation'
              properties: {
                serviceName: 'Microsoft.Web/serverfarms'
              }
              type: 'Microsoft.Network/virtualNetworks/subnets/delegations'
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets'
      }
      {
        name: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name}-ap-subnet'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
        properties: {
          addressPrefixes: [
            '10.100.1.0/26'
          ]
          networkSecurityGroup: {
            id: networkSecurityGroups_acme_ai_dev_krc_01_vnet_ap_subnet_nsg_name_resource.id
          }
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
              locations: [
                'koreacentral'
                'koreasouth'
              ]
            }
            {
              service: 'Microsoft.CognitiveServices'
              locations: [
                '*'
              ]
            }
          ]
          delegations: [
            {
              name: 'delegation'
              id: '${virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id}/delegations/delegation'
              properties: {
                serviceName: 'Microsoft.Web/serverfarms'
              }
              type: 'Microsoft.Network/virtualNetworks/subnets/delegations'
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
        type: 'Microsoft.Network/virtualNetworks/subnets'
      }
    ]
    virtualNetworkPeerings: [
      {
        name: 'ai-dev-krc-01-to-ai-dev-eus2-01-peer'
        id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_ai_dev_krc_01_to_ai_dev_eus2_01_peer.id
        properties: {
          peeringState: 'Connected'
          peeringSyncLevel: 'FullyInSync'
          remoteVirtualNetwork: {
            id: virtualNetworks_acme_ai_dev_eus2_01_vnet_externalid
          }
          allowVirtualNetworkAccess: true
          allowForwardedTraffic: true
          allowGatewayTransit: false
          useRemoteGateways: false
          doNotVerifyRemoteGateways: false
          peerCompleteVnets: true
          remoteAddressSpace: {
            addressPrefixes: [
              '10.110.0.0/16'
            ]
          }
          remoteVirtualNetworkAddressSpace: {
            addressPrefixes: [
              '10.110.0.0/16'
            ]
          }
        }
        type: 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings'
      }
    ]
    enableDdosProtection: false
  }
}

resource accounts_krc_ai_dev_docitg_01_name_resource 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accounts_krc_ai_dev_docitg_01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'S0'
  }
  kind: 'FormRecognizer'
  identity: {
    type: 'None'
  }
  properties: {
    customSubDomainName: accounts_krc_ai_dev_docitg_01_name
    networkAcls: {
      defaultAction: 'Deny'
      virtualNetworkRules: [
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_etc_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
      ]
      ipRules: [
        {
          value: '211.215.58.26'
        }
      ]
    }
    allowProjectManagement: false
    publicNetworkAccess: 'Enabled'
  }
}

resource accounts_krc_ai_dev_openai_01_name_resource 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accounts_krc_ai_dev_openai_01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'S0'
  }
  kind: 'OpenAI'
  properties: {
    apiProperties: {}
    customSubDomainName: accounts_krc_ai_dev_openai_01_name
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: [
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_etc_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
          ignoreMissingVnetServiceEndpoint: false
        }
      ]
      ipRules: [
        {
          value: '211.215.58.26'
        }
        {
          value: '222.234.227.131'
        }
      ]
    }
    allowProjectManagement: false
    publicNetworkAccess: 'Enabled'
  }
}

resource storageAccounts_krcaidevsa01_name_resource 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccounts_krcaidevsa01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'Standard_LRS'
    tier: 'Standard'
  }
  kind: 'StorageV2'
  properties: {
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    allowCrossTenantReplication: false
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    networkAcls: {
      resourceAccessRules: []
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_etc_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
      ]
      ipRules: [
        {
          value: '211.215.58.26'
          action: 'Allow'
        }
      ]
      defaultAction: 'Deny'
    }
    supportsHttpsTrafficOnly: true
    encryption: {
      services: {
        file: {
          keyType: 'Account'
          enabled: true
        }
        blob: {
          keyType: 'Account'
          enabled: true
        }
      }
      keySource: 'Microsoft.Storage'
    }
    accessTier: 'Hot'
  }
}

resource storageAccounts_krcaidevmsdssa01_name_resource 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccounts_krcaidevmsdssa01_name
  location: 'koreacentral'
  tags: {
    Environment: 'PoC'
    'Project Name': 'AI PoC'
  }
  sku: {
    name: 'Standard_LRS'
    tier: 'Standard'
  }
  kind: 'StorageV2'
  properties: {
    dnsEndpointType: 'Standard'
    defaultToOAuthAuthentication: false
    publicNetworkAccess: 'Enabled'
    allowCrossTenantReplication: false
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    largeFileSharesState: 'Enabled'
    networkAcls: {
      resourceAccessRules: []
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pe_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_pgsqlfx_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_vm_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_ap_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_func_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
        {
          id: virtualNetworks_acme_ai_dev_krc_01_vnet_name_virtualNetworks_acme_ai_dev_krc_01_vnet_name_etc_subnet.id
          action: 'Allow'
          state: 'Succeeded'
        }
      ]
      ipRules: [
        {
          value: '211.215.58.26'
          action: 'Allow'
        }
        {
          value: '222.234.227.131'
          action: 'Allow'
        }
      ]
      defaultAction: 'Deny'
    }
    supportsHttpsTrafficOnly: true
    encryption: {
      requireInfrastructureEncryption: false
      services: {
        file: {
          keyType: 'Account'
          enabled: true
        }
        blob: {
          keyType: 'Account'
          enabled: true
        }
      }
      keySource: 'Microsoft.Storage'
    }
    accessTier: 'Hot'
  }
}
