# Terraform Layout

Terraform is organized by provider so each cloud can keep its own instance and networking details while sharing the same role contract.

## Provider roots

- `environments/aws`
- `environments/digital-ocean`
- `environments/hetzner`
- `environments/alibaba-cloud`

Each provider root now:

- uses provider base image variables for generic OS instances
- provisions `worker`, `client`, and `coordinator` nodes from those base images
- generates a Terraform-managed SSH key pair
- outputs a transient inventory payload and a sensitive private key

## Shared modules

`modules/` is still available for reusable shared pieces, but the current provider roots own the cloud-specific resources so the image and key lifecycle stays explicit.
