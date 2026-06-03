# Shared Terraform Modules

This directory is reserved for reusable Terraform modules.

Suggested module responsibilities:

- provision role-specific node groups
- expose inventory-friendly outputs
- keep provider-specific logic out of shared code

The initial focus for this testbed is to keep the interface stable across provider roots so the same Ansible layer can consume the outputs.
