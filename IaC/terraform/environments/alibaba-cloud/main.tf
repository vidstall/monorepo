provider "alicloud" {
  region = var.alicloud_region
}

data "local_file" "image_manifest" {
  filename = abspath("${path.root}/../../../artifacts/image/manifest.json")
}

data "alicloud_zones" "available" {
  available_instance_type     = var.alicloud_instance_type
  available_resource_creation = "Instance"
}

locals {
  common_tags = {
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

resource "alicloud_vpc" "testbed" {
  vpc_name   = "${var.testbed_name}-vpc"
  cidr_block = var.alicloud_vpc_cidr

  tags = local.common_tags
}

resource "alicloud_vswitch" "testbed" {
  vswitch_name = "${var.testbed_name}-vswitch"
  vpc_id       = alicloud_vpc.testbed.id
  cidr_block   = var.alicloud_vswitch_cidr
  zone_id      = data.alicloud_zones.available.zones[0].id

  tags = local.common_tags
}

resource "alicloud_security_group" "ssh" {
  security_group_name = "${var.testbed_name}-ssh"
  vpc_id              = alicloud_vpc.testbed.id

  tags = local.common_tags
}

resource "alicloud_security_group_rule" "ssh_ingress" {
  for_each = toset(var.ssh_cidr_blocks)

  security_group_id = alicloud_security_group.ssh.id
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "22/22"
  priority          = 1
  cidr_ip           = each.value
  description       = "SSH access"
}

resource "alicloud_key_pair" "testbed" {
  key_name   = "${var.testbed_name}-ssh"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "alicloud_instance" "worker" {
  count                      = var.worker_count
  instance_name              = "${var.testbed_name}-worker-${count.index + 1}"
  host_name                  = "${var.testbed_name}-worker-${count.index + 1}"
  image_id                   = local.image_ids.worker
  instance_type              = var.alicloud_instance_type
  security_groups            = [alicloud_security_group.ssh.id]
  vswitch_id                 = alicloud_vswitch.testbed.id
  key_name                   = alicloud_key_pair.testbed.key_name
  user_data                  = local.cloud_init
  internet_max_bandwidth_out = 10
  system_disk_category       = "cloud_essd"

  tags = local.common_tags
}

resource "alicloud_instance" "client" {
  count                      = var.client_count
  instance_name              = "${var.testbed_name}-client-${count.index + 1}"
  host_name                  = "${var.testbed_name}-client-${count.index + 1}"
  image_id                   = local.image_ids.client
  instance_type              = var.alicloud_instance_type
  security_groups            = [alicloud_security_group.ssh.id]
  vswitch_id                 = alicloud_vswitch.testbed.id
  key_name                   = alicloud_key_pair.testbed.key_name
  user_data                  = local.cloud_init
  internet_max_bandwidth_out = 10
  system_disk_category       = "cloud_essd"

  tags = local.common_tags
}

resource "alicloud_instance" "coordinator" {
  count                      = var.coordinator_count
  instance_name              = "${var.testbed_name}-coordinator-${count.index + 1}"
  host_name                  = "${var.testbed_name}-coordinator-${count.index + 1}"
  image_id                   = local.image_ids.coordinator
  instance_type              = var.alicloud_instance_type
  security_groups            = [alicloud_security_group.ssh.id]
  vswitch_id                 = alicloud_vswitch.testbed.id
  key_name                   = alicloud_key_pair.testbed.key_name
  user_data                  = local.cloud_init
  internet_max_bandwidth_out = 10
  system_disk_category       = "cloud_essd"

  tags = local.common_tags
}
