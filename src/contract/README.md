# Xaisen Sui Contract

`src/contract` contains the Sui Move package for Xaisen's on-chain worker registry.

The first contract version is intentionally narrow:

- workers self-register node records
- metadata is stored as a URI plus a 32-byte content hash
- owners can update metadata, toggle availability, or unregister
- room state, payments, rewards, staking, and Redis runtime state stay off-chain

## Build

```bash
sui move build --path src/contract
```

## Test

```bash
sui move test --path src/contract
```

## Runtime Boundary

The Sui registry is the durable public source of worker membership. The Redis coordinator remains the ephemeral runtime state layer for active LiveKit nodes, room ownership, ingress, egress, and job dispatch.
