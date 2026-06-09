# Xaisen Sui Contract

`src/contract` contains the Sui Move package for Xaisen's on-chain worker marketplace.

The contract supports:

- workers registering node records with metadata, fixed rental pricing, and required stake
- worker owner metadata, pricing, availability, unregister, and stake withdrawal flows
- clients hiring an available worker for a room by paying the exact fixed rental price
- escrowed generic `Coin<T>` payments
- client completion that releases escrow to the worker as a reward
- client cancellation that refunds escrow before completion

LiveKit media sessions, participant tokens, Redis coordination, ingress, egress, and runtime room state remain off-chain.

## Build

```bash
sui move build --path src/contract --build-env testnet
```

## Test

```bash
sui move test --path src/contract --build-env testnet
```
