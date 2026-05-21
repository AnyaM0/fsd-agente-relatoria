locals {
  workload_slug         = replace(lower(var.workload_name), "_", "-")
  resource_prefix       = "${var.project_prefix}-${local.workload_slug}"
  compact_workload_slug = replace(local.workload_slug, "-", "")
  compact_prefix        = replace(lower(var.project_prefix), "-", "")

  resource_group_name       = "${local.resource_prefix}-${var.environment}-rg"
  log_analytics_name        = "${local.resource_prefix}-law-${var.environment}"
  container_env_name        = "${local.resource_prefix}-env-${var.environment}"
  backend_app_name          = "${local.workload_slug}-api-${var.environment}"
  worker_app_name           = "${local.workload_slug}-worker-${var.environment}"
  servicebus_namespace_name = substr("${local.resource_prefix}-sb-${var.environment}", 0, 50)
  servicebus_queue_name     = "meeting-jobs"

  storage_account_name          = substr(replace("${local.compact_prefix}${local.compact_workload_slug}sto${var.environment}", "-", ""), 0, 24)
  frontend_storage_account_name = substr(replace("${local.compact_prefix}${local.compact_workload_slug}web${var.environment}", "-", ""), 0, 24)
  cosmos_account_name           = substr(replace("${local.compact_prefix}${local.compact_workload_slug}cdb${var.environment}", "-", ""), 0, 44)

  common_tags = merge(var.tags, {
    environment = var.environment
    workload    = var.workload_name
  })
}
