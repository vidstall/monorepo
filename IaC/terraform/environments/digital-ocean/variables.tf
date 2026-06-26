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

variable "dist_count" {
  type        = number
  description = "Number of dist (frontend) nodes."
  default     = 1
}

variable "coordinator_count" {
  type        = number
  description = "Number of coordinator nodes."
  default     = 1
}

variable "digitalocean_region" {
  type        = string
  description = "DigitalOcean region used for provisioning."
  default     = "nyc3"
}

variable "digitalocean_size" {
  type        = string
  description = "DigitalOcean droplet size."
  default     = "s-1vcpu-1gb"
}

variable "digitalocean_image" {
  type        = string
  description = "DigitalOcean base image slug."
  default     = "ubuntu-22-04-x64"
}

variable "ssh_username" {
  type        = string
  description = "SSH username for the provisioned instances."
  default     = "root"
}
