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
    media = [
      for instance in digitalocean_droplet.media : {
        name       = instance.name
        host       = instance.ipv4_address
        private_ip = instance.ipv4_address_private
        user       = var.ssh_username
      }
    ]
    routes = [
      for instance in digitalocean_droplet.routes : {
        name       = instance.name
        host       = instance.ipv4_address
        private_ip = instance.ipv4_address_private
        user       = var.ssh_username
      }
    ]
    vclient = [
      for instance in digitalocean_droplet.vclient : {
        name       = instance.name
        host       = instance.ipv4_address
        private_ip = instance.ipv4_address_private
        user       = var.ssh_username
      }
    ]
    coordinator = [
      for instance in digitalocean_droplet.coordinator : {
        name       = instance.name
        host       = instance.ipv4_address
        private_ip = instance.ipv4_address_private
        user       = var.ssh_username
      }
    ]
  }
  description = "Inventory data grouped by role."
}
