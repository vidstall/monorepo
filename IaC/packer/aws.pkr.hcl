data "amazon-ami" "ubuntu_worker" {
  filters = {
    name                = var.aws_source_ami_name_regex
    root-device-type    = "ebs"
    virtualization-type = "hvm"
  }
  owners      = [var.aws_source_ami_owner]
  most_recent = true
  region      = var.aws_region
}

source "amazon-ebs" "worker" {
  ami_name      = "${var.testbed_name}-worker-{{timestamp}}"
  instance_type = var.aws_instance_type
  region        = var.aws_region
  source_ami    = data.amazon-ami.ubuntu_worker.id
  ssh_username  = var.aws_ssh_username
  tags = {
    testbed = var.testbed_name
    role    = "worker"
    source  = "depin-iac"
  }
}

source "amazon-ebs" "client" {
  ami_name      = "${var.testbed_name}-client-{{timestamp}}"
  instance_type = var.aws_instance_type
  region        = var.aws_region
  source_ami    = data.amazon-ami.ubuntu_worker.id
  ssh_username  = var.aws_ssh_username
  tags = {
    testbed = var.testbed_name
    role    = "client"
    source  = "depin-iac"
  }
}

source "amazon-ebs" "stateful" {
  ami_name      = "${var.testbed_name}-stateful-{{timestamp}}"
  instance_type = var.aws_instance_type
  region        = var.aws_region
  source_ami    = data.amazon-ami.ubuntu_worker.id
  ssh_username  = var.aws_ssh_username
  tags = {
    testbed = var.testbed_name
    role    = "stateful"
    source  = "depin-iac"
  }
}

build {
  sources = [
    "source.amazon-ebs.worker",
    "source.amazon-ebs.client",
    "source.amazon-ebs.stateful",
  ]

  provisioner "shell" {
    script = "scripts/bootstrap.sh"
  }

  post-processor "manifest" {
    output = "${var.artifacts_dir}/image/manifest.json"
    strip_path = true
    custom_data = {
      provider = "aws"
      testbed  = var.testbed_name
    }
  }
}
