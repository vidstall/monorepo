# `src/coordinator`

`src/coordinator` is the Redis-backed runtime coordination layer for Xaisen.

## Purpose

The coordinator stores shared control-plane state for distributed LiveKit operation.

- It tracks active LiveKit nodes and room ownership.
- It stores room, participant, ingress, egress, dispatch, and agent job state.
- It provides Redis locks and pub/sub coordination used by LiveKit.

The coordinator does not process WebRTC media and does not replace the Sui contract registry.

## Runtime Boundary

- `src/livekit/` reads and writes Redis through its existing Redis store and router.
- `src/routes/` talks to LiveKit APIs, not directly to the coordinator.
- `src/contract/` owns durable public worker registration on Sui.
- `src/coordinator/` provides ephemeral operational state for the running cluster.

## Local Operation

Start Redis manually with:

```bash
docker compose -f src/coordinator/docker-compose.yml up -d
```

Then configure LiveKit with:

```yaml
redis:
  address: 127.0.0.1:6379
```

Run the health check with:

```bash
src/coordinator/scripts/healthcheck.sh
```

## Deployment Notes

This first implementation is manual-only. The existing Ansible, Terraform, and Packer testbed role names already use `coordinator`, but this package does not install Redis through IaC yet.

For production deployment, keep Redis on a private network, enable authentication/TLS where appropriate, and avoid using Redis as a durable source of worker truth.
