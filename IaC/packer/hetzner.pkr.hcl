source "hcloud" "worker" {
  token        = env("HCLOUD_TOKEN")
  image        = var.hcloud_image
  location     = var.hcloud_location
  server_type  = var.hcloud_server_type
  ssh_username = var.hcloud_ssh_username
  snapshot_name = "${var.testbed_name}-worker-{{timestamp}}"
  snapshot_labels = {
    testbed = var.testbed_name
    role    = "worker"
    source  = "depin-iac"
  }
}

source "hcloud" "client" {
  token        = env("HCLOUD_TOKEN")
  image        = var.hcloud_image
  location     = var.hcloud_location
  server_type  = var.hcloud_server_type
  ssh_username = var.hcloud_ssh_username
  snapshot_name = "${var.testbed_name}-client-{{timestamp}}"
  snapshot_labels = {
    testbed = var.testbed_name
    role    = "client"
    source  = "depin-iac"
  }
}

source "hcloud" "stateful" {
  token        = env("HCLOUD_TOKEN")
  image        = var.hcloud_image
  location     = var.hcloud_location
  server_type  = var.hcloud_server_type
  ssh_username = var.hcloud_ssh_username
  snapshot_name = "${var.testbed_name}-stateful-{{timestamp}}"
  snapshot_labels = {
    testbed = var.testbed_name
    role    = "stateful"
    source  = "depin-iac"
  }
}

build {
  sources = [
    "source.hcloud.worker",
    "source.hcloud.client",
    "source.hcloud.stateful",
  ]

  provisioner "shell" {
    script = "scripts/bootstrap.sh"
  }

  post-processor "manifest" {
    output = "${var.artifacts_dir}/image/manifest.json"
    strip_path = true
    custom_data = {
      provider = "hetzner"
      testbed  = var.testbed_name
    }
  }
}
