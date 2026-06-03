data "local_file" "image_manifest" {
  filename = abspath("${path.root}/../../../artifacts/image/manifest.json")
}

locals {
  common_labels = {
    testbed = var.testbed_name
    source  = "depin-iac"
  }

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

resource "hcloud_ssh_key" "testbed" {
  name       = "${var.testbed_name}-ssh"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "hcloud_server" "worker" {
  count       = var.worker_count
  name        = "${var.testbed_name}-worker-${count.index + 1}"
  image       = local.image_ids.worker
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "worker" })
}

resource "hcloud_server" "client" {
  count       = var.client_count
  name        = "${var.testbed_name}-client-${count.index + 1}"
  image       = local.image_ids.client
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "client" })
}

resource "hcloud_server" "stateful" {
  count       = var.stateful_count
  name        = "${var.testbed_name}-stateful-${count.index + 1}"
  image       = local.image_ids.stateful
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "stateful" })
}
