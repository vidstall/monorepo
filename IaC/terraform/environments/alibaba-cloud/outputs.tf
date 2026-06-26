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
      for instance in alicloud_instance.worker : {
        name       = instance.instance_name
        public_ip  = try(instance.public_ip, instance.public_ip_address, "")
        private_ip = try(instance.private_ip, instance.private_ip_address, "")
        ssh_user   = var.ssh_username
        role       = "worker"
      }
    ]
    dist = [
      for instance in alicloud_instance.dist : {
        name       = instance.instance_name
        public_ip  = try(instance.public_ip, instance.public_ip_address, "")
        private_ip = try(instance.private_ip, instance.private_ip_address, "")
        ssh_user   = var.ssh_username
        role       = "dist"
      }
    ]
    coordinator = [
      for instance in alicloud_instance.coordinator : {
        name       = instance.instance_name
        public_ip  = try(instance.public_ip, instance.public_ip_address, "")
        private_ip = try(instance.private_ip, instance.private_ip_address, "")
        ssh_user   = var.ssh_username
        role       = "coordinator"
      }
    ]
  }
  description = "Inventory data grouped by role."
}
