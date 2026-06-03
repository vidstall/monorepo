# Ansible Layout

Ansible is used to configure the nodes after Terraform has provisioned them.

## Role model

The testbed uses three distinct roles:

- `worker`
- `client`
- `stateful`

Each role gets its own group variables and role implementation so the configuration can diverge where needed.

## Contract boundary

The smart-contract node registry is external to this repository. The playbooks and variables should accept a registry identifier once it is provided, but the identifier is not hardcoded here.

## Recommended flow

1. Pick one Terraform provider root.
2. Provision the infrastructure.
3. Export or generate inventory from the provider outputs.
4. Run the Ansible playbook against the three role groups.
