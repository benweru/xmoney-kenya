variable "region" {
  description = "AWS region. Must match bootstrap and app."
  type        = string
  default     = "eu-west-1"
}

variable "alert_email" {
  description = "Where AWS Budgets sends cost alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "budget_alerts_usd" {
  description = "Actual monthly spend, in USD, that triggers an email. The largest is also the forecast threshold."
  type        = list(number)
  default     = [5, 10, 20]

  validation {
    condition     = length(var.budget_alerts_usd) > 0 && alltrue([for v in var.budget_alerts_usd : v > 0])
    error_message = "budget_alerts_usd needs at least one positive amount."
  }
}

variable "github_repository" {
  description = "owner/name of the repository whose Actions may deploy."
  type        = string
  default     = "benweru/xmoney-kenya"
}

variable "github_environment" {
  description = "GitHub Actions environment the deploy job runs in. Only that environment can assume the role."
  type        = string
  default     = "demo"
}

variable "create_github_oidc_provider" {
  description = "False if the account already has the token.actions.githubusercontent.com provider."
  type        = bool
  default     = true
}
