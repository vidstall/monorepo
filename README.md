# Web3 Video Conference Testbed

This repository is for a web3 video conferencing app plus the cloud testbed used to deploy and validate it.

## Product Model

The app is organized around a contract-backed node registry:

- The smart contract acts as the node registry.
- Workers register to provide video infrastructure and earn mining/reward participation.
- Customers rent video conference rooms through the application.

## Application Layers

- `src/livekit/` is the SFU layer.
  - It is the LiveKit server/runtime used to handle media transport and conferencing.
- `src/stateful/` is the coordination layer.
  - It is responsible for Redis-backed cluster coordination, job dispatching, ingress, and egress.
- `src/routes/` is the backend routes service for the meeting app.
  - It provides the API/backend behavior.
- `src/client/` is the web frontend for the meeting app.
  - It contains the user-facing conferencing experience.
  - Both pieces were split from `livekit-examples/meet`.
- `src/contract/` is the contract boundary for the node registry and related on-chain coordination.

## Infrastructure Layer

`IaC/` is the future cloud testbed for the app.

- `IaC/packer/` builds cloud-native images for each provider.
- `IaC/terraform/` provisions the nodes from the image manifest.
- `IaC/ansible/` configures the instances after provisioning.
- `vidctl.py` orchestrates the build, deploy, inventory, and destroy pipeline.

## Current Role Model

The infrastructure is role-based:

- `worker`
- `client`
- `stateful`

For compatibility, the CLI also accepts these aliases:

- `livekit` -> `worker`
- `meet` -> `client`

## Pipeline

The intended deployment flow is:

1. Build cloud-native images with Packer.
2. Write `artifacts/image/manifest.json`.
3. Let Terraform read the manifest and provision the correct image IDs.
4. Let Terraform generate SSH material and inventory data.
5. Run Ansible against the transient inventory.

## Repo Layout

- `vidctl.py` - CLI entrypoint and orchestration layer
- `src/` - application source code
- `IaC/` - cloud testbed infrastructure
- `docs/` - CLI and repository documentation
- `artifacts/` - generated runtime outputs, ignored by git

## Credentials

Provider credentials are loaded from `secrets/cloud/<provider>.env` when present.
Contract deployment credentials and mainnet metadata are loaded from `secrets/contract.env` when present.
Keep `secrets/` out of git.
