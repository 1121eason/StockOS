variable "project_id" {
  type    = string
  default = "stockos-eason-20261022"
  validation {
    condition     = var.project_id == "stockos-eason-20261022"
    error_message = "This deployment is scoped to the dedicated StockOS project."
  }
}

variable "enable_runtime" {
  type        = bool
  default     = false
  description = "Enable only after the private image, bundle, secret and cost review are complete."
}

variable "estimated_monthly_twd" {
  type        = number
  default     = 0
  description = "Reviewed total recurring estimate, including network, storage, backup and tax."
}

variable "bundle_object" {
  type        = string
  default     = ""
  description = "Immutable object name inside the private seed bucket; includes deploy files and seed."
}

variable "bundle_sha256" {
  type    = string
  default = ""
}

variable "environment_secret_version" {
  type        = string
  default     = ""
  description = "Numeric Secret Manager version containing deploy/.env. Never pass secret contents to Terraform."
}
