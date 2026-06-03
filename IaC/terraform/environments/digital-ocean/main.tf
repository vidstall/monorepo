data "local_file" "image_manifest" {
  filename = abspath("${path.root}/../../../artifacts/image/manifest.json")
}

locals {
  common_tags = [
    "testbed:${var.testbed_name}",
    "source:depin-iac",
  ]

  manifest = jsondecode(data.local_file.image_manifest.content)
  builds_by_role = {
    for build in local.manifest.builds :
    element(split(".", build.name), length(split(".", build.name)) - 1) => build
  }
  image_ids = {
    for role, build in local.builds_by_role :
    role => element(split(":", build.artifact_id), 1)
  }
  ssh_home   = var.ssh_username == "root" ? "/root" : "/home/${var.ssh_username}"
  cloud_init = <<-EOT
    #cloud-config
    write_files:
      - path: /tmp/testbed-authorized-key
        permissions: "0600"
        content: |
          ${trimspace(tls_private_key.ssh.public_key_openssh)}
    runcmd:
      - mkdir -p ${local.ssh_home}/.ssh
      - cat /tmp/testbed-authorized-key >> ${local.ssh_home}/.ssh/authorized_keys
      - chown -R ${var.ssh_username}:${var.ssh_username} ${local.ssh_home}/.ssh
      - chmod 700 ${local.ssh_home}/.ssh
      - chmod 600 ${local.ssh_home}/.ssh/authorized_keys
  EOT
}

resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "digitalocean_ssh_key" "testbed" {
  name       = "${var.testbed_name}-ssh"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "digitalocean_droplet" "worker" {
  count     = var.worker_count
  name      = "${var.testbed_name}-worker-${count.index + 1}"
  image     = local.image_ids.worker
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:worker"])
}

resource "digitalocean_droplet" "client" {
  count     = var.client_count
  name      = "${var.testbed_name}-client-${count.index + 1}"
  image     = local.image_ids.client
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:client"])
}

resource "digitalocean_droplet" "coordinator" {
  count     = var.coordinator_count
  name      = "${var.testbed_name}-coordinator-${count.index + 1}"
  image     = local.image_ids.coordinator
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:coordinator"])
}
