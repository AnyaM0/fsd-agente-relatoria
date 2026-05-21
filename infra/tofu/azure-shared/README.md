# Azure Shared OpenTofu

Stack compartido para `domiactas` con:

- Resource Group shared
- Azure Container Registry
- Storage account + container para guardar el estado remoto de OpenTofu

## Uso

```bash
cd infra/tofu/azure-shared
cp dev.tfvars.example dev.tfvars
tofu init
tofu plan -var-file=dev.tfvars
tofu apply -var-file=dev.tfvars
```

Outputs importantes:

- `resource_group_name`
- `acr_name`
- `acr_login_server`
- `state_storage_account_name`
- `state_container_name`

Luego el stack `azure-backend` usa:

- `acr_name`
- `acr_resource_group_name`

y su backend remoto puede apuntar al storage account/container de este stack.
