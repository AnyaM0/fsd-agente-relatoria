locals {
  workload_slug         = replace(lower(var.workload_name), "_", "-")
  compact_workload_slug = replace(local.workload_slug, "-", "")
  compact_prefix        = replace(lower(var.project_prefix), "-", "")

  resource_group_name = "${var.project_prefix}-${local.workload_slug}-shared-${var.environment}-rg"
  acr_name            = substr(replace("${local.compact_prefix}${local.compact_workload_slug}acrsh${var.environment}", "-", ""), 0, 50)
  state_storage_name  = substr(replace("${local.compact_prefix}${local.compact_workload_slug}tfsh${var.environment}", "-", ""), 0, 24)

  common_tags = merge(var.tags, {
    environment = var.environment
    workload    = var.workload_name
  })
}
