# IaC

This directory contains the cloud testbed for the web3 video conference app.

## Purpose

The infrastructure exists to validate the deployment model for the application:

- `worker` nodes run the media/SFU workload
- `client` nodes represent user-facing conference participants
- `coordinator` nodes host Redis-backed coordination, job dispatch, ingress, and egress

## Layout

- `packer/` - cloud image build templates
- `terraform/` - provider roots that provision instances from the image manifest
- `ansible/` - role-based post-provision configuration

## Pipeline Contract

The expected flow is:

1. Build provider images with Packer.
2. Read `artifacts/image/manifest.json` from Terraform.
3. Generate the transient Ansible inventory from Terraform output.
4. Run the Ansible playbook against the created nodes.
