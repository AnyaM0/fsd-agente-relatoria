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
  description = "Resource prefix."
  default     = "fsd"
}

variable "workload_name" {
  type        = string
  description = "Logical workload name."
  default     = "domiactas"
}

variable "tags" {
  type        = map(string)
  description = "Common tags."
  default = {
    managed_by = "opentofu"
    stack      = "shared"
  }
}

variable "state_container_name" {
  type        = string
  description = "Blob container name for OpenTofu remote state."
  default     = "tofu-state"
}
