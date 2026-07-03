# Coordinator

`src/coordinator` contains the Redis runtime coordinator for Xaisen.

The coordinator is not a separate application server. It is a Redis service package that provides the shared control-plane state used by LiveKit when distributed mode is enabled.

## Responsibilities

- Store active LiveKit node metadata.
- Store room-to-node ownership so clients reconnect to the right media node.
- Store room, participant, ingress, egress, dispatch, and agent job state.
- Provide Redis locks and pub/sub used by LiveKit cluster coordination.

Redis does not carry media traffic. Audio, video, and data tracks stay on LiveKit/WebRTC paths.

## Local Start

```bash
docker compose -f src/coordinator/docker-compose.yml up -d
```

The default endpoint is:

```text
127.0.0.1:6379
```

Configure LiveKit with:

```yaml
redis:
  address: 127.0.0.1:6379
```

## Health Check

```bash
src/coordinator/scripts/healthcheck.sh
```

Override the endpoint when needed:

```bash
REDIS_HOST=127.0.0.1 REDIS_PORT=6379 src/coordinator/scripts/healthcheck.sh
```

## Production Notes

- Do not expose Redis directly to the public internet.
- Prefer a private network between LiveKit workers and coordinator nodes.
- Use Redis authentication and TLS when operating outside a trusted private network.
- Keep the Sui contract as the durable public worker registry; Redis is ephemeral runtime state.

## On-Chain Identity

`docker-compose.yml` also runs a small `operator` sidecar (`./operator`) next
to Redis. On first boot it generates and persists a Sui operator keypair,
registers coordinator on-chain as a worker, and self-nominates for
`ROLE_COORDINATOR`, mirroring how `services/routes` and `services/media`
register themselves. It then heartbeats periodically to prove liveness and
marks itself inactive on shutdown.

This is presence/observability only: nothing currently verifies or gates
behavior on `ROLE_COORDINATOR` at runtime, and the address it publishes
on-chain (`COORDINATOR_INTERNAL_ADDRESS`) is informational, not a public
endpoint - Redis must still never be exposed to the public internet. See
`operator/.env.example` for configuration and required funding steps.
