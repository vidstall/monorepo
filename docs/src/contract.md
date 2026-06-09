# Contract Layer

Sui on-chain contract boundary for Xaisen.

## Purpose

The contract acts as the durable worker marketplace for the application:

- workers register node metadata and stake collateral before becoming rentable
- clients hire available workers for room-backed service
- client payments are held in escrow until completion or cancellation
- completed rentals pay worker rewards on-chain

LiveKit media transport, participant tokens, Redis coordination, ingress, egress, and operational room state remain off-chain.

## Current Implementation

The Sui Move package lives in `src/contract`.

- `sources/node_registry.move` implements the generic `Registry<T>` marketplace.
- `tests/node_registry_tests.move` covers registration, staking, hiring, escrow, completion, cancellation, rewards, and withdrawal guards.
- `src/livekit/` remains the SFU/runtime layer.
- `src/coordinator/` remains the Redis-backed runtime coordination layer.
- `src/routes/` and `src/client/` remain the API/frontend layers.

## Marketplace Model

- Workers register with metadata URI, 32-byte metadata hash, fixed price per rental, and a required stake.
- One worker can have one active rental at a time.
- Clients hire a worker by paying exactly the worker's fixed price with `Coin<T>`.
- Pending rental funds are held as contract escrow.
- The client can complete a pending rental, releasing escrow to the worker owner.
- The client can cancel a pending rental, refunding escrow.
- Stake has no slashing in this version; it can be withdrawn only when the worker is inactive and idle.

## Build And Test

```bash
sui move test --path src/contract --build-env testnet
sui move build --path src/contract --build-env testnet
```

## Relationship To IaC

`IaC/` is the cloud testbed for the app. It provisions infrastructure and configures Docker-managed nodes for deployments, but it is not the contract implementation itself.

## Naming Model

The internal infrastructure role model remains:

- `worker`
- `client`
- `coordinator`

CLI aliases remain:

- `livekit` -> `worker`
- `meet` -> `client`
