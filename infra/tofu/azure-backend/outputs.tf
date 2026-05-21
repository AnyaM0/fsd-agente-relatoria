output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "container_apps_environment_name" {
  value = azurerm_container_app_environment.this.name
}

output "backend_container_app_name" {
  value = azurerm_container_app.backend.name
}

output "frontend_static_website_url" {
  value = try(trimsuffix(azurerm_storage_account.frontend[0].primary_web_endpoint, "/"), null)
}

output "backend_container_app_url" {
  value = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

output "worker_container_app_name" {
  value = azurerm_container_app.worker.name
}

output "servicebus_namespace_name" {
  value = azurerm_servicebus_namespace.this.name
}

output "cosmos_account_name" {
  value = azurerm_cosmosdb_account.this.name
}

output "storage_account_name" {
  value = azurerm_storage_account.this.name
}

output "acr_login_server" {
  value = try(data.azurerm_container_registry.shared[0].login_server, null)
}

output "backend_env_hint" {
  value = {
    BACKEND_COSMOS_ACCOUNT_ENDPOINT              = azurerm_cosmosdb_account.this.endpoint
    BACKEND_COSMOS_DATABASE_NAME                 = azurerm_cosmosdb_sql_database.this.name
    BACKEND_BLOB_ACCOUNT_URL                     = trimsuffix(azurerm_storage_account.this.primary_blob_endpoint, "/")
    BACKEND_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
    BACKEND_SERVICEBUS_JOBS_QUEUE_NAME           = azurerm_servicebus_queue.jobs.name
  }
}
