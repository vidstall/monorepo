source "digitalocean" "worker" {
  api_token    = env("DIGITALOCEAN_TOKEN")
  image        = var.digitalocean_image
  region       = var.digitalocean_region
  size         = var.digitalocean_size
  ssh_username = var.digitalocean_ssh_username
  snapshot_name = "${var.testbed_name}-worker-{{timestamp}}"
  tags = [
    "testbed:${var.testbed_name}",
    "role:worker",
    "source:depin-iac",
  ]
}

source "digitalocean" "client" {
  api_token    = env("DIGITALOCEAN_TOKEN")
  image        = var.digitalocean_image
  region       = var.digitalocean_region
  size         = var.digitalocean_size
  ssh_username = var.digitalocean_ssh_username
  snapshot_name = "${var.testbed_name}-client-{{timestamp}}"
  tags = [
    "testbed:${var.testbed_name}",
    "role:client",
    "source:depin-iac",
  ]
}

source "digitalocean" "stateful" {
  api_token    = env("DIGITALOCEAN_TOKEN")
  image        = var.digitalocean_image
  region       = var.digitalocean_region
  size         = var.digitalocean_size
  ssh_username = var.digitalocean_ssh_username
  snapshot_name = "${var.testbed_name}-stateful-{{timestamp}}"
  tags = [
    "testbed:${var.testbed_name}",
    "role:stateful",
    "source:depin-iac",
  ]
}

build {
  sources = [
    "source.digitalocean.worker",
    "source.digitalocean.client",
    "source.digitalocean.stateful",
  ]

  provisioner "shell" {
    script = "scripts/bootstrap.sh"
  }

  post-processor "manifest" {
    output = "${var.artifacts_dir}/image/manifest.json"
    strip_path = true
    custom_data = {
      provider = "digital-ocean"
      testbed  = var.testbed_name
    }
  }
}
