variable "testbed_name" {
  type        = string
  description = "Name of the dePIN testbed deployment."
}

variable "node_registry_contract_id" {
  type        = string
  description = "Smart-contract identifier for the node registry."
  default     = null
}

variable "media_count" {
  type        = number
  description = "Number of media (LiveKit SFU) nodes."
  default     = 1
}

variable "routes_count" {
  type        = number
  description = "Number of routes (API/frontend) nodes."
  default     = 1
}

variable "vclient_count" {
  type        = number
  description = "Number of vclient (bot) nodes."
  default     = 0
}

variable "coordinator_count" {
  type        = number
  description = "Number of coordinator nodes."
  default     = 1
}

variable "alicloud_region" {
  type        = string
  description = "Alibaba Cloud region used for provisioning."
  default     = "cn-hangzhou"
}

variable "alicloud_instance_type" {
  type        = string
  description = "Alibaba Cloud ECS instance type. If null, the cheapest available 1 vCPU / 1 GB spot type is selected automatically."
  default     = null
}

variable "alicloud_vpc_cidr" {
  type        = string
  description = "CIDR block for the testbed VPC."
  default     = "10.42.0.0/16"
}

variable "alicloud_vswitch_cidr" {
  type        = string
  description = "CIDR block for the testbed vSwitch."
  default     = "10.42.1.0/24"
}

variable "alicloud_source_image" {
  type        = string
  description = "Alibaba Cloud base image ID used for provisioned instances."
  default     = null
}

variable "alicloud_spot_strategy" {
  type        = string
  description = "Spot instance strategy: NoSpot, SpotAsPriceGo, or SpotWithPriceLimit."
  default     = "SpotAsPriceGo"
}

variable "ssh_username" {
  type        = string
  description = "SSH username for the provisioned instances."
  default     = "root"
}

variable "ssh_cidr_blocks" {
  type        = list(string)
  description = "CIDR blocks that can reach SSH on the testbed nodes."
  default     = ["0.0.0.0/0"]
}
