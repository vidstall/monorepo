# IaC

This directory contains the infrastructure pipeline for the testbed.

## Layout

- `packer/` - cloud image build templates
- `terraform/` - provider roots that provision instances from the image manifest
- `ansible/` - role-based post-provision configuration

## Pipeline Contract

The expected flow is:

1. Build provider images with Packer
2. Read `artifacts/image/manifest.json` from Terraform
3. Generate the transient Ansible inventory from Terraform output
4. Run the Ansible playbook against the created nodes
