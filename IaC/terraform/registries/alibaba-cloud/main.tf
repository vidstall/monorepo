provider "alicloud" {
  region = var.region
}

resource "alicloud_cr_namespace" "main" {
  name               = var.namespace
  auto_create        = false
  default_visibility = "PUBLIC"
}

resource "alicloud_cr_repo" "images" {
  for_each = toset(["xaisen-worker", "xaisen-routes", "xaisen-client", "xaisen-vclient"])

  namespace = alicloud_cr_namespace.main.name
  name      = each.value
  summary   = "Xaisen ${each.value}"
  repo_type = "PUBLIC"
}
