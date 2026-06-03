variable "name" {
  type        = string
  description = "Logical name for the node pool."
}

variable "role" {
  type        = string
  description = "Role assigned to the node pool."
}

variable "count" {
  type        = number
  description = "Number of nodes in the pool."
  default     = 1
}

variable "tags" {
  type        = map(string)
  description = "Tags or labels applied to the pool."
  default     = {}
}
