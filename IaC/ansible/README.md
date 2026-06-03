# Ansible Layout

Ansible configures nodes after Terraform has provisioned them.

## Role model

The canonical infrastructure roles are:

- `worker`
- `client`
- `coordinator`

`vidctl.py` renders a transient inventory from Terraform output and passes that inventory to `ansible-playbook`.

## Flow

1. Terraform provisions the nodes and generates SSH key output.
2. The CLI writes a short-lived inventory under `artifacts/ssh_config/`.
3. `ansible-playbook` runs against that inventory.
