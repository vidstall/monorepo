data "local_file" "image_manifest" {
  filename = abspath("${path.root}/../../../artifacts/image/manifest.json")
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
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

resource "aws_key_pair" "testbed" {
  key_name   = "${var.testbed_name}-ssh"
  public_key = tls_private_key.ssh.public_key_openssh

  tags = local.common_tags
}

resource "aws_security_group" "ssh" {
  name        = "${var.testbed_name}-ssh"
  description = "SSH access for the testbed"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_cidr_blocks
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_instance" "worker" {
  count                       = var.worker_count
  ami                         = local.image_ids.worker
  instance_type               = var.aws_instance_type
  key_name                    = aws_key_pair.testbed.key_name
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.ssh.id]
  associate_public_ip_address = true
  user_data                   = local.cloud_init

  tags = merge(local.common_tags, {
    Name = "${var.testbed_name}-worker-${count.index + 1}"
    role = "worker"
  })
}

resource "aws_instance" "client" {
  count                       = var.client_count
  ami                         = local.image_ids.client
  instance_type               = var.aws_instance_type
  key_name                    = aws_key_pair.testbed.key_name
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.ssh.id]
  associate_public_ip_address = true
  user_data                   = local.cloud_init

  tags = merge(local.common_tags, {
    Name = "${var.testbed_name}-client-${count.index + 1}"
    role = "client"
  })
}

resource "aws_instance" "coordinator" {
  count                       = var.coordinator_count
  ami                         = local.image_ids.coordinator
  instance_type               = var.aws_instance_type
  key_name                    = aws_key_pair.testbed.key_name
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.ssh.id]
  associate_public_ip_address = true
  user_data                   = local.cloud_init

  tags = merge(local.common_tags, {
    Name = "${var.testbed_name}-coordinator-${count.index + 1}"
    role = "coordinator"
  })
}
