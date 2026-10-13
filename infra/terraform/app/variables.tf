variable "region" {
  description = "AWS region. Must match bootstrap and foundation."
  type        = string
  default     = "eu-west-1"
}

variable "api_image_tag" {
  description = "Tag of the API image in ECR for the first apply. Later deploys come from GitHub Actions, and Terraform ignores the running revision."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.api_image_tag))
    error_message = "api_image_tag must be a valid image tag, such as a git SHA."
  }
}

variable "awake" {
  description = "False scales the API to 0 tasks, stops RDS, and pauses the schedules (make aws-sleep)."
  type        = bool
  default     = true
}

variable "api_desired_count" {
  description = "API tasks while awake. The Daraja mock keeps its pushes in memory, so keep it at 1."
  type        = number
  default     = 1

  validation {
    condition     = var.api_desired_count >= 1 && var.api_desired_count <= 4
    error_message = "api_desired_count must be 1 to 4."
  }
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task."
  type        = number
  default     = 256
}

variable "api_memory" {
  description = "Fargate memory (MiB) for the API task."
  type        = number
  default     = 512
}

variable "enable_sandbox_rail" {
  description = "Offer Safaricom's Daraja sandbox next to the mock. Needs the foundation's Daraja secret filled in."
  type        = bool
  default     = false
}

variable "sandbox_allowed_phones" {
  description = "E.164 handsets the sandbox rail may prompt. Required when the sandbox rail is on, because the demo is public."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for p in var.sandbox_allowed_phones : can(regex("^\\+254[17][0-9]{8}$", p))])
    error_message = "sandbox_allowed_phones must be E.164 Kenyan mobile numbers, such as +254708374149."
  }
}

variable "topup_max_kes" {
  description = "Largest single top-up on the public demo, in shillings."
  type        = number
  default     = 1000

  validation {
    condition     = var.topup_max_kes >= 1 && var.topup_max_kes <= 250000 && floor(var.topup_max_kes) == var.topup_max_kes
    error_message = "topup_max_kes must be a whole number from 1 to 250000."
  }
}

variable "resolve_topups_schedule" {
  description = "How often to STK Query top-ups that have had no callback."
  type        = string
  default     = "rate(10 minutes)"
}

variable "demo_reset_schedule" {
  description = "When to wipe the demo back to its seed, in Africa/Nairobi time."
  type        = string
  default     = "cron(0 3 * * ? *)"
}

variable "db_instance_class" {
  description = "RDS instance class. db.t4g.micro is free-tier eligible for 12 months."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_password_version" {
  description = "Bump to generate a new database password; then redeploy the API so tasks read it."
  type        = number
  default     = 1
}

variable "restore_snapshot_identifier" {
  description = "Create the database from this RDS snapshot (make aws-up SNAPSHOT=...). Null starts empty."
  type        = string
  default     = null
}

variable "deletion_protection" {
  description = "Block terraform destroy of the database. Off so make aws-down works."
  type        = bool
  default     = false
}

variable "cloudfront_price_class" {
  description = "PriceClass_200 includes edge locations in Africa (Nairobi, Johannesburg)."
  type        = string
  default     = "PriceClass_200"
}
