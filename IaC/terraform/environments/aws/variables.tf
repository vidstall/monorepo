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

variable "aws_region" {
  type        = string
  description = "AWS region used for provisioning."
  default     = "us-east-1"
}

variable "aws_instance_type" {
  type        = string
  description = "AWS instance type for all roles."
  default     = "t3.micro"
}

variable "aws_source_ami_owner" {
  type        = string
  description = "Owner ID used to resolve the Ubuntu source AMI."
  default     = "099720109477"
}

variable "aws_source_ami_name_regex" {
  type        = string
  description = "AMI name regex used to resolve the Ubuntu source AMI."
  default     = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
}

variable "ssh_username" {
  type        = string
  description = "Default SSH username for the provisioned instances."
  default     = "ubuntu"
}

variable "ssh_cidr_blocks" {
  type        = list(string)
  description = "CIDR blocks that can reach SSH on the testbed nodes."
  default     = ["0.0.0.0/0"]
}
