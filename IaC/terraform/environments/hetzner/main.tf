locals {
  common_labels = {
    testbed = var.testbed_name
    source  = "depin-iac"
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

resource "hcloud_server" "media" {
  count       = var.media_count
  name        = "${var.testbed_name}-media-${count.index + 1}"
  image       = var.hcloud_image
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "media" })
}

resource "hcloud_server" "routes" {
  count       = var.routes_count
  name        = "${var.testbed_name}-routes-${count.index + 1}"
  image       = var.hcloud_image
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "routes" })
}

resource "hcloud_server" "vclient" {
  count       = var.vclient_count
  name        = "${var.testbed_name}-vclient-${count.index + 1}"
  image       = var.hcloud_image
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "vclient" })
}

resource "hcloud_server" "coordinator" {
  count       = var.coordinator_count
  name        = "${var.testbed_name}-coordinator-${count.index + 1}"
  image       = var.hcloud_image
  location    = var.hcloud_location
  server_type = var.hcloud_server_type
  ssh_keys    = [hcloud_ssh_key.testbed.id]
  user_data   = local.cloud_init
  labels      = merge(local.common_labels, { role = "coordinator" })
}
