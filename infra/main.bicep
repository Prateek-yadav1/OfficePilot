@description('Azure region for OfficePilot resources.')
param location string = resourceGroup().location

@secure()
@description('JSON object mapping Basic Auth usernames to password, user_id, and tenant_id.')
param officePilotAuthUsers string

@secure()
@minLength(32)
@description('Shared secret required by the internal A2A route.')
param a2aSharedSecret string

@secure()
@description('Groq API key used by ADK and CrewAI.')
param groqApiKey string

@description('Groq model ID available to the configured account.')
param groqModel string = 'openai/gpt-oss-120b'

@secure()
@description('Optional PostgreSQL connection string for tenant-scoped retrieval.')
param databaseUrl string = ''

@description('Enable external HTTPS ingress only after the OfficePilot image is deployed and verified.')
param externalIngress string = 'false'

@description('Enable hosted Langfuse tracing. Missing keys intentionally fail app startup.')
param langfuseEnabled string = 'false'

@secure()
param langfusePublicKey string = ''

@secure()
param langfuseSecretKey string = ''

@description('Langfuse project base URL.')
param langfuseBaseUrl string = 'https://cloud.langfuse.com'

var suffix = uniqueString(resourceGroup().id)
var registryName = take('officepilot${suffix}', 50)
var appName = 'officepilot-${suffix}'
var environmentName = 'cae-officepilot-${suffix}'
var workspaceName = 'law-officepilot-${suffix}'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var externalIngressEnabled = toLower(externalIngress) == 'true'
var langfuseIsEnabled = toLower(langfuseEnabled) == 'true'
var secrets = concat(
  [
    {
      name: 'officepilot-auth-users'
      value: officePilotAuthUsers
    }
    {
      name: 'officepilot-a2a-shared-secret'
      value: a2aSharedSecret
    }
    {
      name: 'groq-api-key'
      value: groqApiKey
    }
  ],
  empty(databaseUrl)
    ? []
    : [
        {
          name: 'database-url'
          value: databaseUrl
        }
      ],
  langfuseIsEnabled
    ? [
        {
          name: 'langfuse-public-key'
          value: langfusePublicKey
        }
        {
          name: 'langfuse-secret-key'
          value: langfuseSecretKey
        }
      ]
    : []
)
var appEnvironment = concat(
  [
    {
      name: 'OFFICEPILOT_AUTH_USERS'
      secretRef: 'officepilot-auth-users'
    }
    {
      name: 'OFFICEPILOT_A2A_SHARED_SECRET'
      secretRef: 'officepilot-a2a-shared-secret'
    }
    {
      name: 'LLM_PROVIDER'
      value: 'groq'
    }
    {
      name: 'GROQ_API_KEY'
      secretRef: 'groq-api-key'
    }
    {
      name: 'GROQ_MODEL'
      value: groqModel
    }
    {
      name: 'OFFICEPILOT_WORKSPACE_MODE'
      value: 'mock'
    }
    {
      name: 'OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES'
      value: 'false'
    }
    {
      name: 'OFFICEPILOT_EXECUTION_DB'
      value: '/tmp/officepilot/executions.sqlite3'
    }
    {
      name: 'OFFICEPILOT_MAX_CONCURRENT_WORKFLOWS'
      value: '1'
    }
    {
      name: 'LANGFUSE_ENABLED'
      value: langfuseIsEnabled ? 'true' : 'false'
    }
  ],
  empty(databaseUrl)
    ? []
    : [
        {
          name: 'DATABASE_URL'
          secretRef: 'database-url'
        }
      ],
  langfuseIsEnabled
    ? [
        {
          name: 'LANGFUSE_PUBLIC_KEY'
          secretRef: 'langfuse-public-key'
        }
        {
          name: 'LANGFUSE_SECRET_KEY'
          secretRef: 'langfuse-secret-key'
        }
        {
          name: 'LANGFUSE_BASE_URL'
          value: langfuseBaseUrl
        }
      ]
    : []
)

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-officepilot-${suffix}'
  location: location
}

resource registryPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, appIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      acrPullRoleId
    )
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
    }
  }
  tags: {
    'azd-service-name': 'officepilot'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: secrets
      registries: [
        {
          server: registry.properties.loginServer
          identity: appIdentity.id
        }
      ]
      ingress: {
        external: externalIngressEnabled
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'officepilot'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: 2
            memory: '4Gi'
          }
          env: appEnvironment
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    registryPullRole
  ]
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_CONTAINER_APP_NAME string = containerApp.name
output AZURE_CONTAINER_APP_URL string = externalIngressEnabled
  ? 'https://${containerApp.properties.configuration.ingress.fqdn}'
  : ''
