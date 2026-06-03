variable "testbed_name" {
  type        = string
  default     = "depin-testbed"
  description = "Logical name used to tag built images."
}

variable "artifacts_dir" {
  type        = string
  default     = "../../artifacts"
  description = "Repository-relative or absolute path to the artifacts directory."
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region used for building AMIs."
}

variable "aws_instance_type" {
  type        = string
  default     = "t3.micro"
  description = "AWS instance type used during the build."
}

variable "aws_source_ami_owner" {
  type        = string
  default     = "099720109477"
  description = "Owner account used for the Ubuntu source AMI lookup."
}

variable "aws_source_ami_name_regex" {
  type        = string
  default     = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
  description = "Name filter used to resolve the Ubuntu source AMI."
}

variable "aws_ssh_username" {
  type        = string
  default     = "ubuntu"
  description = "SSH username for the AWS build instance."
}

variable "digitalocean_region" {
  type        = string
  default     = "nyc3"
  description = "DigitalOcean region used for the build."
}

variable "digitalocean_size" {
  type        = string
  default     = "s-1vcpu-1gb"
  description = "DigitalOcean droplet size used during the build."
}

variable "digitalocean_image" {
  type        = string
  default     = "ubuntu-22-04-x64"
  description = "DigitalOcean base image slug."
}

variable "digitalocean_ssh_username" {
  type        = string
  default     = "root"
  description = "SSH username for the DigitalOcean build instance."
}

variable "alicloud_region" {
  type        = string
  default     = "cn-hangzhou"
  description = "Alibaba Cloud region used for the build."
}

variable "alicloud_instance_type" {
  type        = string
  default     = "ecs.t6-c1m1.small"
  description = "Alibaba Cloud ECS instance type used during the build."
}

variable "alicloud_source_image" {
  type        = string
  description = "Alibaba Cloud base image ID or image name used for the build."
}

variable "alicloud_ssh_username" {
  type        = string
  default     = "root"
  description = "SSH username for the Alibaba Cloud build instance."
}

variable "hcloud_location" {
  type        = string
  default     = "fsn1"
  description = "Hetzner Cloud location used for the build."
}

variable "hcloud_server_type" {
  type        = string
  default     = "cx22"
  description = "Hetzner Cloud server type used during the build."
}

variable "hcloud_image" {
  type        = string
  default     = "ubuntu-24.04"
  description = "Hetzner Cloud base image slug."
}

variable "hcloud_ssh_username" {
  type        = string
  default     = "root"
  description = "SSH username for the Hetzner build instance."
}
