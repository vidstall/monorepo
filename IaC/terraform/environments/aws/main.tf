locals {
  common_tags = {
    testbed = var.testbed_name
    source  = "depin-iac"
  }
}

# Provider-specific infrastructure is intentionally left as a placeholder.
# The provider root will later assemble shared modules for worker, client,
# and stateful node groups.
