variable "project_name" {
  description = "Project name used in AWS resource names."
  type        = string
  default     = "ax-sentinel"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "ap-northeast-2"
}

variable "kubernetes_version" {
  description = "Amazon EKS Kubernetes version."
  type        = string
  default     = "1.34"
}

variable "node_instance_types" {
  description = "EC2 types used by the EKS managed node group."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "node_min_size" {
  type    = number
  default = 2
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_max_size" {
  type    = number
  default = 6
}

variable "web_callback_urls" {
  description = "Allowed OIDC authorization-code callback URLs."
  type        = list(string)
  default     = ["http://localhost:3000/auth/callback"]
}

variable "web_logout_urls" {
  description = "Allowed post-logout URLs."
  type        = list(string)
  default     = ["http://localhost:3000/login"]
}
