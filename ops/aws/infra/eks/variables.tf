variable "region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_name" {
  type    = string
  default = "jobintel-eks"
}

variable "k8s_version" {
  type    = string
  default = "1.29"
}

variable "subnet_ids" {
  type = list(string)
}

variable "node_instance_types" {
  type    = list(string)
  default = ["t3.medium"]
}

variable "node_min" {
  type    = number
  default = 1
}

variable "node_desired" {
  type    = number
  default = 1
}

variable "node_max" {
  type    = number
  default = 2
}

variable "s3_bucket" {
  type = string
}

variable "s3_prefix" {
  type    = string
  default = "jobintel"
}

variable "k8s_namespace" {
  type    = string
  default = "jobintel"
}

variable "serviceaccount_name" {
  type    = string
  default = "jobintel"
}

variable "tag_subnets" {
  type    = bool
  default = true
}

variable "admin_principal_arn" {
  type        = string
  default     = ""
  description = "IAM principal ARN to grant EKS cluster admin access (user or role). Leave empty to skip."
}
