variable "subscription_id" {
  type        = string
  description = "Azure subscription id. Empty uses the active az/tofu context."
  default     = ""
}

variable "location" {
  type        = string
  description = "Azure region."
  default     = "eastus2"
}

variable "environment" {
  type        = string
  description = "Environment suffix, e.g. dev or prod."
  default     = "dev"
}

variable "project_prefix" {
  type        = string
  description = "Resource prefix, matching the existing estate."
  default     = "fsd"
}

variable "workload_name" {
  type        = string
  description = "Logical workload name. Example: actia, chatllm, domiactas."
  default     = "domiactas"
}

variable "tags" {
  type        = map(string)
  description = "Common tags."
  default = {
    managed_by = "opentofu"
    stack      = "backend"
  }
}

variable "acr_name" {
  type        = string
  description = "Existing ACR name from the shared stack."
  default     = ""
}

variable "acr_resource_group_name" {
  type        = string
  description = "Resource group that holds the shared ACR."
  default     = ""
}

variable "backend_image" {
  type        = string
  description = "Container image for the FastAPI backend."
}

variable "worker_image" {
  type        = string
  description = "Container image for the job worker."
}

variable "backend_container_cpu" {
  type    = number
  default = 1
}

variable "backend_container_memory" {
  type    = string
  default = "2Gi"
}

variable "worker_container_cpu" {
  type    = number
  default = 1
}

variable "worker_container_memory" {
  type    = string
  default = "2Gi"
}

variable "backend_min_replicas" {
  type    = number
  default = 0
}

variable "backend_max_replicas" {
  type    = number
  default = 2
}

variable "worker_min_replicas" {
  type    = number
  default = 0
}

variable "worker_max_replicas" {
  type    = number
  default = 1
}

variable "backend_target_port" {
  type    = number
  default = 8000
}

variable "create_frontend_static_website" {
  type    = bool
  default = true
}

variable "frontend_index_document" {
  type    = string
  default = "index.html"
}

variable "frontend_error_404_document" {
  type    = string
  default = "404.html"
}

variable "backend_entra_enabled" {
  type    = bool
  default = true
}

variable "key_vault_name" {
  type        = string
  description = "Existing Key Vault name used to feed container app secrets."
  default     = ""
}

variable "key_vault_resource_group_name" {
  type        = string
  description = "Resource group holding the existing Key Vault. Empty uses the backend RG."
  default     = ""
}

variable "backend_entra_tenant_id" {
  type    = string
  default = ""
}

variable "backend_entra_client_id" {
  type    = string
  default = ""
}

variable "backend_entra_audience" {
  type    = string
  default = ""
}

variable "backend_admin_bootstrap_object_ids" {
  type    = list(string)
  default = []
}

variable "azure_speech_region" {
  type    = string
  default = ""
}

variable "azure_speech_endpoint" {
  type    = string
  default = ""
}

variable "azure_speech_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "azure_storage_container_name" {
  type    = string
  default = "audio"
}

variable "databricks_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "databricks_base_url" {
  type    = string
  default = ""
}

variable "segmentation_databricks_model" {
  type    = string
  default = "databricks-claude-sonnet-4-6"
}

variable "compras_databricks_model" {
  type    = string
  default = ""
}

variable "approval_memo_databricks_model" {
  type    = string
  default = ""
}

variable "juridica_databricks_model" {
  type    = string
  default = ""
}

variable "frontend_base_url" {
  type    = string
  default = ""
}

variable "frontend_job_url_template" {
  type    = string
  default = "/jobs/{job_id}"
}

variable "notifications_email_enabled" {
  type    = bool
  default = false
}

variable "notifications_email_backend" {
  type    = string
  default = "noop"
}

variable "notifications_email_sender" {
  type    = string
  default = ""
}

variable "notifications_email_reply_to" {
  type    = string
  default = ""
}

variable "notifications_smtp_host" {
  type    = string
  default = ""
}

variable "notifications_smtp_port" {
  type    = number
  default = 587
}

variable "notifications_smtp_username" {
  type    = string
  default = ""
}

variable "notifications_smtp_password" {
  type      = string
  default   = ""
  sensitive = true
}

variable "servicebus_root_connection_string" {
  type      = string
  default   = ""
  sensitive = true
}

variable "notifications_smtp_use_tls" {
  type    = bool
  default = true
}

variable "notifications_smtp_use_ssl" {
  type    = bool
  default = false
}

variable "servicebus_job_retry_delay_seconds" {
  type    = number
  default = 300
}

variable "azure_batch_max_wait_hours" {
  type    = number
  default = 6
}

variable "jobs_max_attempts" {
  type    = number
  default = 3
}

variable "blob_cors_allowed_origins" {
  type        = list(string)
  default     = ["*"]
  description = "Allowed origins for Azure Blob Storage CORS (direct browser uploads). Restrict to your frontend URL in production, e.g. [\"https://app.example.com\"]."
}
