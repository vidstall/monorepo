output "testbed_name" {
  value       = var.testbed_name
  description = "Name of the dePIN testbed deployment."
}

output "node_registry_contract_id" {
  value       = var.node_registry_contract_id
  description = "Smart-contract identifier for the node registry."
}

output "private_key_pem" {
  value       = tls_private_key.ssh.private_key_pem
  description = "Private key generated for SSH access."
  sensitive   = true
}

output "inventory" {
  value = {
    worker = [
      for instance in hcloud_server.worker : {
        name = instance.name
        host = instance.ipv4_address
        user = var.ssh_username
      }
    ]
    dist = [
      for instance in hcloud_server.dist : {
        name = instance.name
        host = instance.ipv4_address
        user = var.ssh_username
      }
    ]
    coordinator = [
      for instance in hcloud_server.coordinator : {
        name = instance.name
        host = instance.ipv4_address
        user = var.ssh_username
      }
    ]
  }
  description = "Inventory data grouped by role."
}
