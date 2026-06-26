# IaC

This repository uses infrastructure-as-code to build and validate the cloud deployment layer for the web3 video conferencing app.

## Purpose

`IaC/` is the testbed layer for the system.

- It builds cloud-native images for each provider.
- It provisions provider infrastructure from base OS images.
- It configures the resulting nodes after they are created.
- It gives the app a repeatable way to exercise the deployment pipeline across cloud vendors.

## Pipeline

The orchestration flow is:

1. Terraform provisions base instances for the selected provider and roles.
2. Terraform generates SSH material and inventory data.
3. (Optional) Contract is published to Sui and the shared Registry object is created.
4. Ansible installs Docker and runs the role containers with contract config injected.

`vidctl.py` is the entrypoint that sequences those steps. Use `--deploy-contract` to include step 3:

```bash
python3 vidctl.py deploy --provider alibaba-cloud \
  --worker-nodes 3 --coordinator-nodes 1 \
  --deploy-contract --contract-network testnet
```

## Layout

- `IaC/terraform/` contains the provider roots and shared modules.
- `IaC/ansible/` contains the post-provision configuration.

## Role And Provider Model

The infrastructure is role-based:

- `worker`
- `client`
- `coordinator`

The supported cloud providers are:

- AWS
- DigitalOcean
- Hetzner
- Alibaba Cloud

## Relationship To The App

The IaC layer supports the runtime split documented elsewhere in the repo:

- `src/livekit/` is the SFU/runtime layer.
- `src/routes/` is the backend API service.
- `src/client/` is the browser frontend.
- `src/coordinator/` is the Redis-backed coordination layer.
- `src/contract/` is the on-chain node registry boundary.

IaC should stay focused on deployment and validation, not app feature logic.

## Related Docs

- [`README.md`](../README.md)
- [`docs/cli.md`](cli.md)
- [`docs/design.md`](design.md)
- [`IaC/README.md`](../IaC/README.md)
- [`IaC/terraform/README.md`](../IaC/terraform/README.md)
- [`IaC/ansible/README.md`](../IaC/ansible/README.md)
