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
      for instance in aws_instance.worker : {
        name = instance.tags.Name
        host = instance.public_ip
        user = var.ssh_username
      }
    ]
    dist = [
      for instance in aws_instance.dist : {
        name = instance.tags.Name
        host = instance.public_ip
        user = var.ssh_username
      }
    ]
    vclient = [
      for instance in aws_instance.vclient : {
        name = instance.tags.Name
        host = instance.public_ip
        user = var.ssh_username
      }
    ]
    coordinator = [
      for instance in aws_instance.coordinator : {
        name = instance.tags.Name
        host = instance.public_ip
        user = var.ssh_username
      }
    ]
  }
  description = "Inventory data grouped by role."
}
