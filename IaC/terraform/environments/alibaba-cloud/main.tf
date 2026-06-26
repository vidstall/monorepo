provider "alicloud" {
  region = var.alicloud_region
}

data "alicloud_zones" "available" {
  available_resource_creation = "Instance"
}

data "alicloud_images" "ubuntu" {
  owners      = "system"
  name_regex  = "^ubuntu_22_04_x64_20G_alibase"
  most_recent = true
}

locals {
  effective_image = coalesce(var.alicloud_source_image, data.alicloud_images.ubuntu.images[0].id)
  ssh_home        = var.ssh_username == "root" ? "/root" : "/home/${var.ssh_username}"
  user_data = <<-EOT
    #!/bin/sh
    set -eu
    if ! id -u ${var.ssh_username} >/dev/null 2>&1; then
      useradd -m -s /bin/bash ${var.ssh_username}
    fi
    mkdir -p ${local.ssh_home}/.ssh
    chmod 700 ${local.ssh_home}/.ssh
    cat > ${local.ssh_home}/.ssh/authorized_keys <<'KEY'
    ${tls_private_key.ssh.public_key_openssh}
    KEY
    chmod 600 ${local.ssh_home}/.ssh/authorized_keys
    chown -R ${var.ssh_username}:${var.ssh_username} ${local.ssh_home}/.ssh
    if command -v sudo >/dev/null 2>&1; then
      echo '${var.ssh_username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-${var.ssh_username}
      chmod 440 /etc/sudoers.d/90-${var.ssh_username}
    fi
  EOT

  common_tags = {
    Project = "xaisen"
    Testbed = var.testbed_name
  }
}

resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "alicloud_vpc" "main" {
  vpc_name   = var.testbed_name
  cidr_block = var.alicloud_vpc_cidr
}

resource "alicloud_vswitch" "main" {
  vpc_id       = alicloud_vpc.main.id
  cidr_block   = var.alicloud_vswitch_cidr
  zone_id      = data.alicloud_zones.available.zones[0].id
  vswitch_name = var.testbed_name
}

resource "alicloud_security_group" "testbed" {
  security_group_name = "${var.testbed_name}-sg"
  vpc_id              = alicloud_vpc.main.id
}

resource "alicloud_security_group_rule" "ssh_ingress" {
  for_each = toset(var.ssh_cidr_blocks)

  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "22/22"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = each.value
}

resource "alicloud_security_group_rule" "http_ingress" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "80/80"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = "0.0.0.0/0"
}

resource "alicloud_security_group_rule" "livekit_signal_ingress" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "7880/7880"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = "0.0.0.0/0"
}

resource "alicloud_security_group_rule" "livekit_tcp_ingress" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "7881/7881"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = "0.0.0.0/0"
}

resource "alicloud_security_group_rule" "livekit_udp_ingress" {
  type              = "ingress"
  ip_protocol       = "udp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "7882/7882"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = "0.0.0.0/0"
}

resource "alicloud_security_group_rule" "redis_private_ingress" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "6379/6379"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = var.alicloud_vpc_cidr
}

resource "alicloud_security_group_rule" "egress_all" {
  type              = "egress"
  ip_protocol       = "all"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "-1/-1"
  priority          = 1
  security_group_id = alicloud_security_group.testbed.id
  cidr_ip           = "0.0.0.0/0"
}

resource "alicloud_instance" "worker" {
  count = var.worker_count

  availability_zone          = data.alicloud_zones.available.zones[0].id
  security_groups            = [alicloud_security_group.testbed.id]
  instance_type              = var.alicloud_instance_type
  image_id                   = local.effective_image
  system_disk_category       = "cloud_efficiency"
  instance_name              = "${var.testbed_name}-worker-${count.index + 1}"
  vswitch_id                 = alicloud_vswitch.main.id
  internet_max_bandwidth_out = 100
  user_data                  = local.user_data
  spot_strategy              = var.alicloud_spot_strategy

  tags = merge(local.common_tags, {
    Role = "worker"
  })
}

resource "alicloud_instance" "dist" {
  count = var.dist_count

  availability_zone          = data.alicloud_zones.available.zones[0].id
  security_groups            = [alicloud_security_group.testbed.id]
  instance_type              = var.alicloud_instance_type
  image_id                   = local.effective_image
  system_disk_category       = "cloud_efficiency"
  instance_name              = "${var.testbed_name}-dist-${count.index + 1}"
  vswitch_id                 = alicloud_vswitch.main.id
  internet_max_bandwidth_out = 100
  user_data                  = local.user_data
  spot_strategy              = var.alicloud_spot_strategy

  tags = merge(local.common_tags, {
    Role = "dist"
  })
}

resource "alicloud_instance" "coordinator" {
  count = var.coordinator_count

  availability_zone          = data.alicloud_zones.available.zones[0].id
  security_groups            = [alicloud_security_group.testbed.id]
  instance_type              = var.alicloud_instance_type
  image_id                   = local.effective_image
  system_disk_category       = "cloud_efficiency"
  instance_name              = "${var.testbed_name}-coordinator-${count.index + 1}"
  vswitch_id                 = alicloud_vswitch.main.id
  internet_max_bandwidth_out = 100
  user_data                  = local.user_data
  spot_strategy              = var.alicloud_spot_strategy

  tags = merge(local.common_tags, {
    Role = "coordinator"
  })
}
