variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "jobintel"
}

variable "s3_bucket" {
  type = string
}

variable "s3_prefix" {
  type    = string
  default = "jobintel"
}

variable "ecs_cluster_arn" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "container_image" {
  type = string
}

variable "openai_api_key_ssm_param" {
  type    = string
  default = ""
}

variable "discord_webhook_url_ssm_param" {
  type    = string
  default = ""
}

variable "ssm_kms_key_arn" {
  type    = string
  default = ""
}

variable "schedule_expression" {
  type    = string
  default = "rate(1 day)"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "jobintel_dashboard_url" {
  type    = string
  default = ""
}

variable "container_secrets" {
  type = list(object({
    name      = string
    valueFrom = string
  }))
  default = []
}
