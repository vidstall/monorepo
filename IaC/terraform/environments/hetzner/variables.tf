variable "testbed_name" {
  type        = string
  description = "Name of the dePIN testbed deployment."
}

variable "node_registry_contract_id" {
  type        = string
  description = "Smart-contract identifier for the node registry."
  default     = null
}

variable "worker_count" {
  type        = number
  description = "Number of worker nodes."
  default     = 1
}

variable "client_count" {
  type        = number
  description = "Number of client nodes."
  default     = 1
}

variable "coordinator_count" {
  type        = number
  description = "Number of coordinator nodes."
  default     = 1
}

variable "hcloud_location" {
  type        = string
  description = "Hetzner Cloud location used for provisioning."
  default     = "fsn1"
}

variable "hcloud_server_type" {
  type        = string
  description = "Hetzner Cloud server type."
  default     = "cx22"
}

variable "hcloud_image" {
  type        = string
  description = "Hetzner Cloud image slug."
  default     = "ubuntu-24.04"
}

variable "ssh_username" {
  type        = string
  description = "SSH username for the provisioned instances."
  default     = "root"
}
