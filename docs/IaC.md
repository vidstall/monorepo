# IaC

This repository uses infrastructure-as-code to build and validate the cloud deployment layer for the web3 video conferencing app.

## Purpose

`IaC/` is the testbed layer for the system.

- It builds cloud-native images for each provider.
- It provisions provider infrastructure from the image manifest.
- It configures the resulting nodes after they are created.
- It gives the app a repeatable way to exercise the deployment pipeline across cloud vendors.

## Pipeline

The orchestration flow is:

1. Packer builds images for the selected provider and roles.
2. Packer writes `artifacts/image/manifest.json`.
3. Terraform reads that manifest and provisions infrastructure from the image IDs.
4. Terraform generates SSH material and inventory data.
5. Ansible runs against the transient inventory.

`vidctl.py` is the entrypoint that sequences those steps.

## Layout

- `IaC/packer/` contains the cloud image build templates.
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

- [`README.md`](/Users/qvanle/projects/personal/livekit/codebase/README.md)
- [`docs/cli.md`](/Users/qvanle/projects/personal/livekit/codebase/docs/cli.md)
- [`IaC/README.md`](/Users/qvanle/projects/personal/livekit/codebase/IaC/README.md)
- [`IaC/packer/README.md`](/Users/qvanle/projects/personal/livekit/codebase/IaC/packer/README.md)
- [`IaC/terraform/README.md`](/Users/qvanle/projects/personal/livekit/codebase/IaC/terraform/README.md)
- [`IaC/ansible/README.md`](/Users/qvanle/projects/personal/livekit/codebase/IaC/ansible/README.md)

