variable "namespace" {
  type        = string
  description = "ACR namespace name (must be globally unique on Alibaba Cloud)."
  default     = "xaisen"
}

variable "region" {
  type        = string
  description = "Alibaba Cloud region for the container registry."
  default     = "cn-hangzhou"
}
