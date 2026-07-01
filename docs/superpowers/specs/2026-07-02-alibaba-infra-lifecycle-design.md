# Alibaba Infrastructure Lifecycle Design

## Goal

Make `vidctl infra start`, `pause`, `restart`, and `kill` report and apply truthful lifecycle state for Alibaba-hosted VM services. Frontend object-storage behavior remains unchanged.

## Lifecycle behavior

- `start` sets Alibaba ECS to `Running`, regenerates inventory, and configures only the selected host with its container in the `started` state.
- `pause` sets Alibaba ECS to `Stopped` with `stopped_mode="KeepCharging"`. It retains the VM and allocated resources and does not run Ansible after shutdown.
- `restart` sets ECS to `Running`, regenerates inventory, reapplies configuration to only the selected host, and explicitly uses Docker container state `restarted`.
- `kill --yes` removes the Pulumi-managed resources and only then removes the topology entry and generated SSH key.
- Alibaba is the first provider with complete powered pause/restart semantics. Unsupported VM providers reject those two operations before topology mutation.

## Orchestration and state

Pulumi maps topology `running` and `stopped` to Alibaba ECS `Running` and `Stopped`. Stopped instances remain managed but are excluded from active Ansible inventory.

VM start and restart execute Pulumi, inventory generation, and host-limited Ansible configuration in order. Every stage propagates its exit code. `last_status` advances only after all required stages succeed. Failures record the stage in `last_error` and runtime history.

If Pulumi succeeds but inventory or Ansible fails, topology retains the applied desired infrastructure state instead of pretending the cloud operation was rolled back. The error records that service configuration is incomplete.

The Ansible deployment wrapper accepts a host limit and explicit Docker container state. Ordinary deployment defaults to `started`; lifecycle restart supplies `restarted`.

## Validation

Automated tests cover Alibaba ECS status mapping, stage ordering, host targeting, explicit restart, pause without SSH, kill cleanup, failure propagation, unsupported providers, and unchanged frontend lifecycle behavior. The Python test suite and syntax/import checks must pass.

## Decisions

- Pause uses Alibaba `KeepCharging` to retain resources and favor reliable restart.
- Restart means reconfigure and restart the container, not reboot or replace the VM.
- Tencent and Cloudflare remain unsupported for VM lifecycle operations.
