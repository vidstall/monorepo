# VidCtl

VidCtl is a small orchestration CLI for a multi-cloud video testbed.

It coordinates three tools:

- `Packer` builds cloud-native images
- `Terraform` provisions provider infrastructure from the generated image manifest
- `Ansible` configures the nodes after they are created

## Repository Layout

- `vidctl.py` - CLI entrypoint and pipeline orchestrator
- `IaC/packer/` - Packer templates for AWS, DigitalOcean, Hetzner, and Alibaba Cloud
- `IaC/terraform/` - Provider roots that consume `artifacts/image/manifest.json`
- `IaC/ansible/` - Post-provision configuration playbooks and role data
- `artifacts/` - Generated build and runtime outputs, ignored by git

## Roles

The infrastructure contract is role-based:

- `worker`
- `client`
- `stateful`

For compatibility, the CLI also accepts the older aliases:

- `livekit` -> `worker`
- `meet` -> `client`

## Typical Flow

1. Build the provider images with `./vidctl.py build --provider aws`
2. Provision the infrastructure with `./vidctl.py deploy --provider aws`
3. Tear everything down with `./vidctl.py destroy --provider aws`

## Credentials

Provider credentials are loaded from `secrets/cloud/<provider>.env` when present.
Keep `secrets/` out of git.
