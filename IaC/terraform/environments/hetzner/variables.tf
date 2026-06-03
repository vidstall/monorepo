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

variable "stateful_count" {
  type        = number
  description = "Number of stateful nodes."
  default     = 1
}
