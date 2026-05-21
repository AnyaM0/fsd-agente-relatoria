resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.common_tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = local.log_analytics_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.common_tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = local.container_env_name
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.common_tags
}

data "azurerm_container_registry" "shared" {
  count               = var.acr_name != "" && var.acr_resource_group_name != "" ? 1 : 0
  name                = var.acr_name
  resource_group_name = var.acr_resource_group_name
}

data "azurerm_key_vault" "this" {
  count               = var.key_vault_name != "" ? 1 : 0
  name                = var.key_vault_name
  resource_group_name = var.key_vault_resource_group_name != "" ? var.key_vault_resource_group_name : azurerm_resource_group.this.name
}

resource "azurerm_key_vault_secret" "azure_speech_api_key" {
  count        = length(data.azurerm_key_vault.this) > 0 && var.azure_speech_api_key != "" ? 1 : 0
  name         = "azure-speech-api-key"
  value        = var.azure_speech_api_key
  key_vault_id = data.azurerm_key_vault.this[0].id
}

resource "azurerm_key_vault_secret" "databricks_token" {
  count        = length(data.azurerm_key_vault.this) > 0 && var.databricks_token != "" ? 1 : 0
  name         = "databricks-token"
  value        = var.databricks_token
  key_vault_id = data.azurerm_key_vault.this[0].id
}

resource "azurerm_key_vault_secret" "smtp_password" {
  count        = length(data.azurerm_key_vault.this) > 0 && var.notifications_smtp_password != "" ? 1 : 0
  name         = "smtp-password"
  value        = var.notifications_smtp_password
  key_vault_id = data.azurerm_key_vault.this[0].id
}

resource "azurerm_key_vault_secret" "servicebus_root_connection_string" {
  count        = length(data.azurerm_key_vault.this) > 0 && var.servicebus_root_connection_string != "" ? 1 : 0
  name         = "servicebus-root-connection-string"
  value        = var.servicebus_root_connection_string
  key_vault_id = data.azurerm_key_vault.this[0].id
}

resource "azurerm_storage_account" "this" {
  name                            = local.storage_account_name
  resource_group_name             = azurerm_resource_group.this.name
  location                        = azurerm_resource_group.this.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.common_tags

  blob_properties {
    cors_rule {
      allowed_origins    = var.blob_cors_allowed_origins
      allowed_methods    = ["DELETE", "GET", "HEAD", "MERGE", "OPTIONS", "PUT"]
      allowed_headers    = ["*"]
      exposed_headers    = ["*"]
      max_age_in_seconds = 86400
    }

    delete_retention_policy {
      days                     = 7
      permanent_delete_enabled = false
    }
  }
}

resource "azurerm_storage_account" "frontend" {
  count                           = var.create_frontend_static_website ? 1 : 0
  name                            = local.frontend_storage_account_name
  resource_group_name             = azurerm_resource_group.this.name
  location                        = azurerm_resource_group.this.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.common_tags

  static_website {
    index_document     = var.frontend_index_document
    error_404_document = var.frontend_error_404_document
  }
}

resource "azurerm_storage_blob" "frontend_index" {
  count                  = var.create_frontend_static_website ? 1 : 0
  name                   = var.frontend_index_document
  storage_account_name   = azurerm_storage_account.frontend[0].name
  storage_container_name = "$web"
  type                   = "Block"
  content_type           = "text/html; charset=utf-8"
  source_content         = fileexists("${path.module}/../../../frontend/dist/index.html") ? file("${path.module}/../../../frontend/dist/index.html") : <<-HTML
  <!doctype html>
  <html lang="es">
    <head>
      <meta charset="utf-8" />
      <title>DomiActas</title>
    </head>
    <body>
      <h1>DomiActas</h1>
      <p>Infraestructura lista. Frontend pendiente de despliegue.</p>
    </body>
  </html>
  HTML
}

resource "azurerm_storage_blob" "frontend_404" {
  count                  = var.create_frontend_static_website ? 1 : 0
  name                   = var.frontend_error_404_document
  storage_account_name   = azurerm_storage_account.frontend[0].name
  storage_container_name = "$web"
  type                   = "Block"
  content_type           = "text/html; charset=utf-8"
  source_content         = fileexists("${path.module}/../../../frontend/dist/index.html") ? file("${path.module}/../../../frontend/dist/index.html") : <<-HTML
  <!doctype html>
  <html lang="es">
    <head>
      <meta charset="utf-8" />
      <title>No encontrado</title>
    </head>
    <body>
      <h1>404</h1>
      <p>El recurso solicitado no existe.</p>
    </body>
  </html>
  HTML
}

resource "azurerm_storage_container" "uploads" {
  name                  = "meeting-uploads"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "artifacts" {
  name                  = "meeting-artifacts"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_servicebus_namespace" "this" {
  name                = local.servicebus_namespace_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  tags                = local.common_tags
}

resource "azurerm_servicebus_queue" "jobs" {
  name         = local.servicebus_queue_name
  namespace_id = azurerm_servicebus_namespace.this.id
}

resource "azurerm_cosmosdb_account" "this" {
  name                = local.cosmos_account_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  tags                = local.common_tags

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.this.location
    failover_priority = 0
  }

  capabilities {
    name = "EnableServerless"
  }
}

resource "azurerm_cosmosdb_sql_database" "this" {
  name                = "fsd-domiactas"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
}

resource "azurerm_cosmosdb_sql_container" "jobs" {
  name                  = "meeting-jobs"
  resource_group_name   = azurerm_resource_group.this.name
  account_name          = azurerm_cosmosdb_account.this.name
  database_name         = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths   = ["/owner_object_id"]
  partition_key_version = 2
}

resource "azurerm_cosmosdb_sql_container" "resources" {
  name                  = "resources"
  resource_group_name   = azurerm_resource_group.this.name
  account_name          = azurerm_cosmosdb_account.this.name
  database_name         = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths   = ["/owner_object_id"]
  partition_key_version = 2
}

resource "azurerm_cosmosdb_sql_container" "admin" {
  name                  = "admin-config"
  resource_group_name   = azurerm_resource_group.this.name
  account_name          = azurerm_cosmosdb_account.this.name
  database_name         = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths   = ["/kind"]
  partition_key_version = 2
}

resource "azurerm_container_app" "backend" {
  name                         = local.backend_app_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = local.common_tags

  identity {
    type = "SystemAssigned"
  }

  ingress {
    external_enabled = true
    target_port      = var.backend_target_port
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  dynamic "registry" {
    for_each = length(data.azurerm_container_registry.shared) > 0 ? [1] : []
    content {
      server   = data.azurerm_container_registry.shared[0].login_server
      identity = "System"
    }
  }

  template {
    min_replicas = var.backend_min_replicas
    max_replicas = var.backend_max_replicas

    container {
      name   = "backend"
      image  = var.backend_image
      cpu    = var.backend_container_cpu
      memory = var.backend_container_memory

      env {
        name  = "BACKEND_ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "BACKEND_COSMOS_ACCOUNT_ENDPOINT"
        value = azurerm_cosmosdb_account.this.endpoint
      }
      env {
        name  = "BACKEND_COSMOS_DATABASE_NAME"
        value = azurerm_cosmosdb_sql_database.this.name
      }
      env {
        name  = "BACKEND_COSMOS_JOBS_CONTAINER_NAME"
        value = azurerm_cosmosdb_sql_container.jobs.name
      }
      env {
        name  = "BACKEND_COSMOS_RESOURCES_CONTAINER_NAME"
        value = azurerm_cosmosdb_sql_container.resources.name
      }
      env {
        name  = "BACKEND_COSMOS_ADMIN_CONTAINER_NAME"
        value = azurerm_cosmosdb_sql_container.admin.name
      }
      env {
        name  = "BACKEND_COSMOS_AUTO_CREATE_CONTAINERS"
        value = "false"
      }
      env {
        name  = "BACKEND_BLOB_ACCOUNT_URL"
        value = trimsuffix(azurerm_storage_account.this.primary_blob_endpoint, "/")
      }
      env {
        name  = "BACKEND_BLOB_UPLOADS_CONTAINER_NAME"
        value = azurerm_storage_container.uploads.name
      }
      env {
        name  = "BACKEND_BLOB_ARTIFACTS_CONTAINER_NAME"
        value = azurerm_storage_container.artifacts.name
      }
      env {
        name  = "BACKEND_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE"
        value = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
      }
      env {
        name  = "BACKEND_SERVICEBUS_JOBS_QUEUE_NAME"
        value = azurerm_servicebus_queue.jobs.name
      }
      env {
        name  = "BACKEND_SERVICEBUS_JOB_RETRY_DELAY_SECONDS"
        value = tostring(var.servicebus_job_retry_delay_seconds)
      }
      env {
        name  = "BACKEND_AZURE_BATCH_MAX_WAIT_HOURS"
        value = tostring(var.azure_batch_max_wait_hours)
      }
      env {
        name  = "BACKEND_JOBS_MAX_ATTEMPTS"
        value = tostring(var.jobs_max_attempts)
      }
      env {
        name  = "BACKEND_ENTRA_ENABLED"
        value = var.backend_entra_enabled ? "true" : "false"
      }
      env {
        name  = "BACKEND_ENTRA_TENANT_ID"
        value = var.backend_entra_tenant_id
      }
      env {
        name  = "BACKEND_ENTRA_CLIENT_ID"
        value = var.backend_entra_client_id
      }
      env {
        name  = "BACKEND_ENTRA_AUDIENCE"
        value = var.backend_entra_audience
      }
      env {
        name  = "BACKEND_ADMIN_BOOTSTRAP_OBJECT_IDS"
        value = jsonencode(var.backend_admin_bootstrap_object_ids)
      }
      env {
        name  = "BACKEND_FRONTEND_BASE_URL"
        value = var.frontend_base_url != "" ? var.frontend_base_url : (var.create_frontend_static_website ? trimsuffix(azurerm_storage_account.frontend[0].primary_web_endpoint, "/") : "")
      }
      env {
        name  = "BACKEND_FRONTEND_JOB_URL_TEMPLATE"
        value = var.frontend_job_url_template
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_ENABLED"
        value = var.notifications_email_enabled ? "true" : "false"
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_BACKEND"
        value = var.notifications_email_backend
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_SENDER"
        value = var.notifications_email_sender
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_REPLY_TO"
        value = var.notifications_email_reply_to
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_SMTP_HOST"
        value = var.notifications_smtp_host
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_SMTP_PORT"
        value = tostring(var.notifications_smtp_port)
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_SMTP_USERNAME"
        value = var.notifications_smtp_username
      }
      env {
        name        = "BACKEND_NOTIFICATIONS_SMTP_PASSWORD"
        secret_name = "smtp-password"
      }
    }
  }

  secret {
    name                = "smtp-password"
    key_vault_secret_id = length(azurerm_key_vault_secret.smtp_password) > 0 ? azurerm_key_vault_secret.smtp_password[0].versionless_id : null
    identity            = "System"
  }
}

resource "azurerm_container_app" "worker" {
  name                         = local.worker_app_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = local.common_tags

  identity {
    type = "SystemAssigned"
  }

  dynamic "registry" {
    for_each = length(data.azurerm_container_registry.shared) > 0 ? [1] : []
    content {
      server   = data.azurerm_container_registry.shared[0].login_server
      identity = "System"
    }
  }

  template {
    min_replicas = var.worker_min_replicas
    max_replicas = var.worker_max_replicas

    container {
      name   = "worker"
      image  = var.worker_image
      cpu    = var.worker_container_cpu
      memory = var.worker_container_memory

      command = ["/opt/venv/bin/python"]
      args    = ["-m", "backend.workers.run_job_worker"]

      env {
        name  = "BACKEND_ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "BACKEND_COSMOS_ACCOUNT_ENDPOINT"
        value = azurerm_cosmosdb_account.this.endpoint
      }
      env {
        name  = "BACKEND_COSMOS_DATABASE_NAME"
        value = azurerm_cosmosdb_sql_database.this.name
      }
      env {
        name  = "BACKEND_COSMOS_JOBS_CONTAINER_NAME"
        value = azurerm_cosmosdb_sql_container.jobs.name
      }
      env {
        name  = "BACKEND_COSMOS_RESOURCES_CONTAINER_NAME"
        value = azurerm_cosmosdb_sql_container.resources.name
      }
      env {
        name  = "BACKEND_COSMOS_ADMIN_CONTAINER_NAME"
        value = azurerm_cosmosdb_sql_container.admin.name
      }
      env {
        name  = "BACKEND_COSMOS_AUTO_CREATE_CONTAINERS"
        value = "false"
      }
      env {
        name  = "BACKEND_BLOB_ACCOUNT_URL"
        value = trimsuffix(azurerm_storage_account.this.primary_blob_endpoint, "/")
      }
      env {
        name  = "BACKEND_BLOB_UPLOADS_CONTAINER_NAME"
        value = azurerm_storage_container.uploads.name
      }
      env {
        name  = "BACKEND_BLOB_ARTIFACTS_CONTAINER_NAME"
        value = azurerm_storage_container.artifacts.name
      }
      env {
        name  = "BACKEND_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE"
        value = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
      }
      env {
        name  = "BACKEND_SERVICEBUS_JOBS_QUEUE_NAME"
        value = azurerm_servicebus_queue.jobs.name
      }
      env {
        name  = "BACKEND_SERVICEBUS_JOB_RETRY_DELAY_SECONDS"
        value = tostring(var.servicebus_job_retry_delay_seconds)
      }
      env {
        name  = "BACKEND_AZURE_BATCH_MAX_WAIT_HOURS"
        value = tostring(var.azure_batch_max_wait_hours)
      }
      env {
        name  = "BACKEND_JOBS_MAX_ATTEMPTS"
        value = tostring(var.jobs_max_attempts)
      }
      env {
        name  = "BACKEND_ENTRA_ENABLED"
        value = var.backend_entra_enabled ? "true" : "false"
      }
      env {
        name  = "BACKEND_ENTRA_TENANT_ID"
        value = var.backend_entra_tenant_id
      }
      env {
        name  = "BACKEND_ENTRA_CLIENT_ID"
        value = var.backend_entra_client_id
      }
      env {
        name  = "BACKEND_ENTRA_AUDIENCE"
        value = var.backend_entra_audience
      }
      env {
        name  = "BACKEND_ADMIN_BOOTSTRAP_OBJECT_IDS"
        value = jsonencode(var.backend_admin_bootstrap_object_ids)
      }
      env {
        name  = "BACKEND_FRONTEND_BASE_URL"
        value = var.frontend_base_url != "" ? var.frontend_base_url : (var.create_frontend_static_website ? trimsuffix(azurerm_storage_account.frontend[0].primary_web_endpoint, "/") : "")
      }
      env {
        name  = "BACKEND_FRONTEND_JOB_URL_TEMPLATE"
        value = var.frontend_job_url_template
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_ENABLED"
        value = var.notifications_email_enabled ? "true" : "false"
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_BACKEND"
        value = var.notifications_email_backend
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_SENDER"
        value = var.notifications_email_sender
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_EMAIL_REPLY_TO"
        value = var.notifications_email_reply_to
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_SMTP_HOST"
        value = var.notifications_smtp_host
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_SMTP_PORT"
        value = tostring(var.notifications_smtp_port)
      }
      env {
        name  = "BACKEND_NOTIFICATIONS_SMTP_USERNAME"
        value = var.notifications_smtp_username
      }
      env {
        name        = "BACKEND_NOTIFICATIONS_SMTP_PASSWORD"
        secret_name = "smtp-password"
      }

      env {
        name  = "AZURE_SPEECH_REGION"
        value = var.azure_speech_region
      }
      env {
        name  = "AZURE_SPEECH_ENDPOINT"
        value = var.azure_speech_endpoint
      }
      env {
        name        = "AZURE_SPEECH_API_KEY"
        secret_name = "azure-speech-api-key"
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = trimsuffix(azurerm_storage_account.this.primary_blob_endpoint, "/")
      }
      env {
        name  = "AZURE_STORAGE_CONTAINER_NAME"
        value = var.azure_storage_container_name
      }
      env {
        name        = "DATABRICKS_TOKEN"
        secret_name = "databricks-token"
      }
      env {
        name  = "DATABRICKS_BASE_URL"
        value = var.databricks_base_url
      }
      env {
        name  = "SEGMENTATION_DATABRICKS_MODEL"
        value = var.segmentation_databricks_model
      }
      env {
        name  = "COMPRAS_DATABRICKS_MODEL"
        value = var.compras_databricks_model
      }
      env {
        name  = "APPROVAL_MEMO_DATABRICKS_MODEL"
        value = var.approval_memo_databricks_model
      }
      env {
        name  = "JURIDICA_DATABRICKS_MODEL"
        value = var.juridica_databricks_model
      }
    }

    custom_scale_rule {
      name             = "servicebus-jobs"
      custom_rule_type = "azure-servicebus"
      metadata = {
        queueName    = azurerm_servicebus_queue.jobs.name
        messageCount = "1"
      }

      authentication {
        secret_name       = "servicebus-root-connection-string"
        trigger_parameter = "connection"
      }
    }
  }

  secret {
    name                = "azure-speech-api-key"
    key_vault_secret_id = length(azurerm_key_vault_secret.azure_speech_api_key) > 0 ? azurerm_key_vault_secret.azure_speech_api_key[0].versionless_id : null
    identity            = "System"
  }

  secret {
    name                = "databricks-token"
    key_vault_secret_id = length(azurerm_key_vault_secret.databricks_token) > 0 ? azurerm_key_vault_secret.databricks_token[0].versionless_id : null
    identity            = "System"
  }

  secret {
    name                = "smtp-password"
    key_vault_secret_id = length(azurerm_key_vault_secret.smtp_password) > 0 ? azurerm_key_vault_secret.smtp_password[0].versionless_id : null
    identity            = "System"
  }

  secret {
    name                = "servicebus-root-connection-string"
    key_vault_secret_id = length(azurerm_key_vault_secret.servicebus_root_connection_string) > 0 ? azurerm_key_vault_secret.servicebus_root_connection_string[0].versionless_id : null
    identity            = "System"
  }
}

resource "azurerm_role_assignment" "backend_blob" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_container_app.backend.identity[0].principal_id
}

resource "azurerm_role_assignment" "worker_blob" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_container_app.worker.identity[0].principal_id
}

resource "azurerm_role_assignment" "backend_blob_delegator" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_container_app.backend.identity[0].principal_id
}

resource "azurerm_role_assignment" "worker_blob_delegator" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_container_app.worker.identity[0].principal_id
}

resource "azurerm_role_assignment" "backend_servicebus_sender" {
  scope                = azurerm_servicebus_namespace.this.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_container_app.backend.identity[0].principal_id
}

resource "azurerm_role_assignment" "worker_servicebus_sender" {
  scope                = azurerm_servicebus_namespace.this.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_container_app.worker.identity[0].principal_id
}

resource "azurerm_role_assignment" "worker_servicebus_receiver" {
  scope                = azurerm_servicebus_namespace.this.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_container_app.worker.identity[0].principal_id
}

resource "azurerm_role_assignment" "backend_acr_pull" {
  count                = length(data.azurerm_container_registry.shared) > 0 ? 1 : 0
  scope                = data.azurerm_container_registry.shared[0].id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.backend.identity[0].principal_id
}

resource "azurerm_role_assignment" "worker_acr_pull" {
  count                = length(data.azurerm_container_registry.shared) > 0 ? 1 : 0
  scope                = data.azurerm_container_registry.shared[0].id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.worker.identity[0].principal_id
}

resource "azurerm_role_assignment" "backend_keyvault_secrets_user" {
  count                = length(data.azurerm_key_vault.this) > 0 ? 1 : 0
  scope                = data.azurerm_key_vault.this[0].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_container_app.backend.identity[0].principal_id
}

resource "azurerm_role_assignment" "worker_keyvault_secrets_user" {
  count                = length(data.azurerm_key_vault.this) > 0 ? 1 : 0
  scope                = data.azurerm_key_vault.this[0].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_container_app.worker.identity[0].principal_id
}

resource "azurerm_cosmosdb_sql_role_assignment" "backend_data_contributor" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_container_app.backend.identity[0].principal_id
  scope               = azurerm_cosmosdb_account.this.id
}

resource "azurerm_cosmosdb_sql_role_assignment" "worker_data_contributor" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_container_app.worker.identity[0].principal_id
  scope               = azurerm_cosmosdb_account.this.id
}
