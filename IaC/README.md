# IaC

This directory contains the cloud testbed for the web3 video conference app.

## Purpose

The infrastructure exists to validate the deployment model for the application:

- `worker` nodes run the media/SFU workload
- `client` nodes represent user-facing conference participants
- `coordinator` nodes host Redis-backed coordination, job dispatch, ingress, and egress

## Layout

- `terraform/` - provider roots that provision base instances
- `ansible/` - Docker-based role configuration

## Pipeline Contract

The expected flow is:

1. Provision provider instances from base OS images with Terraform.
2. Generate the transient Ansible inventory from Terraform output.
3. Install Docker and run role containers with Ansible.
