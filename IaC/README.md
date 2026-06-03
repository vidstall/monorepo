# dePIN Testbed IaC

This repository contains the infrastructure-as-code scaffold for a dePIN testbed.

The project is organized around two layers:

- `terraform/` provisions testbed infrastructure
- `ansible/` configures nodes after provisioning

The testbed is role-based, not app-environment-based. The three roles are:

- `worker`
- `client`
- `stateful`

The node registry is expected to come from a separate smart-contract folder. The contract identifier is intentionally left as an input boundary until it is supplied later.

## Environment model

Terraform environments are separated by cloud provider for manual cost optimization.

Available provider roots:

- `terraform/environments/aws`
- `terraform/environments/digital-ocean`
- `terraform/environments/hetzner`
- `terraform/environments/alibaba-cloud`

Pick one provider root per testbed run.

## Repository layout

- `terraform/modules/` shared Terraform modules
- `terraform/environments/<provider>/` provider-specific roots
- `ansible/inventory/` inventory definitions and inventory-generation inputs
- `ansible/group_vars/` role-level variables
- `ansible/host_vars/` host-specific variables
- `ansible/playbooks/` entrypoint playbooks
- `ansible/roles/` role implementations
- `utils/` helper scripts and local tooling

## Current status

This is a scaffold, not a finished deployment.

The repository now contains explicit placeholders for:

- provider-specific Terraform entrypoints
- shared Terraform module interfaces
- role-based Ansible configuration
- the future smart-contract registry integration

## Next step

Add the actual provider resources and the smart-contract registry contract identifier, then wire Terraform outputs into Ansible inventory generation.
