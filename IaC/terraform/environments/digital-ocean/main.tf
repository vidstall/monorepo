locals {
  common_tags = [
    "testbed:${var.testbed_name}",
    "source:depin-iac",
  ]

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

resource "digitalocean_vpc" "main" {
  name   = var.testbed_name
  region = var.digitalocean_region
}

resource "digitalocean_droplet" "media" {
  count     = var.media_count
  name      = "${var.testbed_name}-media-${count.index + 1}"
  image     = var.digitalocean_image
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  vpc_uuid  = digitalocean_vpc.main.id
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:media"])
}

resource "digitalocean_droplet" "routes" {
  count     = var.routes_count
  name      = "${var.testbed_name}-routes-${count.index + 1}"
  image     = var.digitalocean_image
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  vpc_uuid  = digitalocean_vpc.main.id
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:routes"])
}

resource "digitalocean_droplet" "vclient" {
  count     = var.vclient_count
  name      = "${var.testbed_name}-vclient-${count.index + 1}"
  image     = var.digitalocean_image
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  vpc_uuid  = digitalocean_vpc.main.id
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:vclient"])
}

resource "digitalocean_droplet" "coordinator" {
  count     = var.coordinator_count
  name      = "${var.testbed_name}-coordinator-${count.index + 1}"
  image     = var.digitalocean_image
  region    = var.digitalocean_region
  size      = var.digitalocean_size
  vpc_uuid  = digitalocean_vpc.main.id
  ssh_keys  = [digitalocean_ssh_key.testbed.id]
  user_data = local.cloud_init
  tags      = concat(local.common_tags, ["role:coordinator"])
}

resource "digitalocean_firewall" "testbed" {
  name = "${var.testbed_name}-fw"
  droplet_ids = concat(
    digitalocean_droplet.media[*].id,
    digitalocean_droplet.routes[*].id,
    digitalocean_droplet.vclient[*].id,
    digitalocean_droplet.coordinator[*].id,
  )

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "7880-7882"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "udp"
    port_range       = "7882"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "6379"
    source_addresses = [digitalocean_vpc.main.ip_range]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "all"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "all"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
