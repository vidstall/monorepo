# Terraform Layout

Terraform is organized by provider so that the testbed can be deployed on the cheapest viable cloud for a given run.

## Provider roots

- `environments/aws`
- `environments/digital-ocean`
- `environments/hetzner`
- `environments/alibaba-cloud`

Each provider root should expose the same logical interface:

- testbed name
- role counts for `worker`, `client`, and `stateful`
- node registry contract identifier
- labels/tags needed for Ansible and runtime discovery

## Shared modules

Reusable infrastructure building blocks belong in `modules/`.

Recommended module boundaries:

- node pools or instance groups
- networking
- storage
- security and access

The provider roots should assemble these modules and keep provider-specific differences isolated.
