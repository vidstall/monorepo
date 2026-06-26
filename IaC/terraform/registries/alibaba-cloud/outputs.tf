output "registry" {
  description = "ACR registry prefix to use as --registry for build-images."
  value       = "registry.${var.region}.aliyuncs.com/${var.namespace}"
}
