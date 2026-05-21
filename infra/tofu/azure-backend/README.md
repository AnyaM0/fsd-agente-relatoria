# Azure Backend OpenTofu

Base de OpenTofu para desplegar la infraestructura mínima del backend y su worker en Azure, siguiendo el patrón de nombres que ya existe en la suscripción:

- Resource groups: `fsd-<workload>-<env>-rg`
- Container Apps env: `fsd-<workload>-env-<env>`
- API app: `<workload>-api-<env>`
- Worker app: `<workload>-worker-<env>`
- Frontend static site: `https://<storage>.z13.web.core.windows.net`
- App registration sugerida: `<workload>-api-<env>`
- App registration de tofu sugerida: `<workload>-tofu`

## Qué crea

- Resource Group
- Log Analytics Workspace
- Container Apps Environment
- Storage Account + containers `meeting-uploads` y `meeting-artifacts`
- Service Bus Namespace + queue `meeting-jobs`
- Cosmos DB account + SQL database + containers:
  - `meeting-jobs`
  - `resources`
  - `admin-config`
- Frontend estático opcional en Azure Storage
- Container App público para el backend
- Container App interno para el worker
- RBAC mínimo para:
  - Blob
  - Service Bus
  - Cosmos DB data plane
  - Key Vault secrets

## Estado actual de `domiactas-dev`

Este stack ya quedó aplicado sobre `fsd-domiactas-dev-rg` con estos nombres:

- Container Apps Environment: `fsd-domiactas-env-dev`
- Backend API: `domiactas-api-dev`
- Worker: `domiactas-worker-dev`
- Storage Account: `fsddomiactasstodev`
- Cosmos DB: `fsddomiactascdbdev`
- Service Bus namespace: `fsd-domiactas-sb-dev`
- Key Vault: `fsddomiactaskvdev`
- Frontend static website: `https://fsddomiactaswebdev.z20.web.core.windows.net`

## Escalado

- `domiactas-api-dev` quedó con `minReplicas = 0` y `maxReplicas = 2`
- `domiactas-worker-dev` quedó con `minReplicas = 0` y `maxReplicas = 1`
- el worker escala por evento usando la cola `meeting-jobs` de Service Bus
- en Azure Container Apps, `minReplicas = null` en la API de consulta equivale a `0`

## Key Vault y secretos

Los secretos sensibles que salen de `.env.azure.local` quedaron montados en `fsddomiactaskvdev` y referenciados desde Container Apps por `keyVaultUrl`:

- `azure-speech-api-key`
- `databricks-token`
- `smtp-password`
- `azure-storage-account-key`
- `azure-storage-connection-string`
- `servicebus-root-connection-string`

Los valores no sensibles siguen como variables de entorno normales en los contenedores:

- endpoints
- nombres de containers
- nombres de colas
- tenant/client/audience de Entra
- URLs del frontend

## Uso

```bash
cd infra/tofu/azure-backend
cp dev.tfvars.example dev.tfvars
tofu init
tofu plan -var-file=dev.tfvars
tofu apply -var-file=dev.tfvars
```

## Notas importantes

- Este stack asume que tus imágenes ya existen.
- Este stack consume un ACR ya existente del stack `shared`.
- Si no fijas `frontend_base_url`, el stack usa la URL del sitio estático de Azure Storage cuando `create_frontend_static_website=true`.
- El backend usa Managed Identity para Blob, Cosmos y Service Bus.
- El backend usa referencias de Key Vault para los secretos sensibles que necesita leer en runtime.
- El worker usa:
  - Managed Identity para Blob/Cosmos/Service Bus
  - referencias de Key Vault para `AZURE_SPEECH_API_KEY`, `DATABRICKS_TOKEN`, SMTP y credenciales auxiliares de Storage/Service Bus
- En producción conviene:
  - `BACKEND_COSMOS_AUTO_CREATE_CONTAINERS=false`
  - mantener secretos en Key Vault y no inline en `Container Apps`

## Naming observado en tu tenant

Tomé como referencia lo que ya existe:

- `fsd-actia-dev-rg`
- `fsd-actia-env-dev`
- `actia-api-dev`
- `actia-worker-dev`
- `actia-api-dev` como app registration
- `actia-tofu` como app registration de IaC
