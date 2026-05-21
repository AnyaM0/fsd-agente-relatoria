output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "acr_name" {
  value = azurerm_container_registry.this.name
}

output "acr_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "state_storage_account_name" {
  value = azurerm_storage_account.state.name
}

output "state_container_name" {
  value = azurerm_storage_container.state.name
}
