output "name" {
  value       = var.name
  description = "Logical name for the node pool."
}

output "role" {
  value       = var.role
  description = "Role assigned to the node pool."
}

output "count" {
  value       = var.count
  description = "Number of nodes in the pool."
}

output "tags" {
  value       = var.tags
  description = "Tags or labels applied to the pool."
}
