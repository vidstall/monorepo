# Xaisen Sui Contract

This package is the Sui Move package for Xaisen's on-chain worker marketplace.

The contract supports:

- workers registering node records with metadata, fixed rental pricing, and required stake
- worker owner metadata, pricing, availability, unregister, and stake withdrawal flows
- clients hiring an available worker for a room by paying the exact fixed rental price
- escrowed generic `Coin<T>` payments
- client completion that releases escrow to the worker as a reward
- client cancellation that refunds escrow before completion
- room-assignment and infrastructure-role voting among active workers
- routed media-cluster assignment with reward-split payments between a router and a media node

LiveKit media sessions, participant tokens, Redis coordination, ingress, egress, and runtime room state remain off-chain.

## Module tree

The contract is split by domain, each store module owning its structs, invariants, and accessors:

- `sources/registry.move` — the shared `Registry<T>` object aggregating one store per domain
- `sources/stores/` — `worker_store` (+ `worker_accessors`), `rental_store`, `room_vote_store`, `role_vote_store`, `media_store`
- `sources/events/` — `worker_events`, `rental_events`, `governance_events`, `media_events`
- `sources/workers.move`, `rentals.move`, `room_governance.move`, `role_governance.move`, `media_routing.move` — the transaction (entry function) modules for each domain
- `tests/` — one test module per domain, plus `tests/test_fixtures.move` for shared test-only helpers

## Build

```bash
sui move build --path . --build-env testnet
```

## Test

```bash
sui move test --path . --build-env testnet
```

## Line-length check

Every `.move` file under `sources/` and `tests/` is capped at 200 physical lines. Verify with:

```bash
bash scripts/check_loc.sh
```
