source "alicloud-ecs" "worker" {
  access_key    = env("ALICLOUD_ACCESS_KEY")
  secret_key    = env("ALICLOUD_SECRET_KEY")
  region        = var.alicloud_region
  source_image  = var.alicloud_source_image
  image_name    = "${var.testbed_name}-worker-{{timestamp}}"
  instance_type = var.alicloud_instance_type
  ssh_username  = var.alicloud_ssh_username
  io_optimized  = true
  internet_charge_type = "PayByTraffic"
  image_force_delete   = true
  run_tags = {
    testbed = var.testbed_name
    role    = "worker"
    source  = "depin-iac"
  }
}

source "alicloud-ecs" "client" {
  access_key    = env("ALICLOUD_ACCESS_KEY")
  secret_key    = env("ALICLOUD_SECRET_KEY")
  region        = var.alicloud_region
  source_image  = var.alicloud_source_image
  image_name    = "${var.testbed_name}-client-{{timestamp}}"
  instance_type = var.alicloud_instance_type
  ssh_username  = var.alicloud_ssh_username
  io_optimized  = true
  internet_charge_type = "PayByTraffic"
  image_force_delete   = true
  run_tags = {
    testbed = var.testbed_name
    role    = "client"
    source  = "depin-iac"
  }
}

source "alicloud-ecs" "coordinator" {
  access_key    = env("ALICLOUD_ACCESS_KEY")
  secret_key    = env("ALICLOUD_SECRET_KEY")
  region        = var.alicloud_region
  source_image  = var.alicloud_source_image
  image_name    = "${var.testbed_name}-coordinator-{{timestamp}}"
  instance_type = var.alicloud_instance_type
  ssh_username  = var.alicloud_ssh_username
  io_optimized  = true
  internet_charge_type = "PayByTraffic"
  image_force_delete   = true
  run_tags = {
    testbed = var.testbed_name
    role    = "coordinator"
    source  = "depin-iac"
  }
}

build {
  sources = [
    "source.alicloud-ecs.worker",
    "source.alicloud-ecs.client",
    "source.alicloud-ecs.coordinator",
  ]

  provisioner "shell" {
    script = "scripts/bootstrap.sh"
  }

  post-processor "manifest" {
    output = "${var.artifacts_dir}/image/manifest.json"
    strip_path = true
    custom_data = {
      provider = "alibaba-cloud"
      testbed  = var.testbed_name
    }
  }
}
