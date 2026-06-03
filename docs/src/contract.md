# Contract Layer

This document describes the on-chain contract boundary for the web3 video conferencing app.

## Purpose

The smart contract acts as the node registry for the system.

- Workers register through the contract before they participate in the network.
- The registry is the on-chain source of truth for available worker nodes.
- Customers use the application to rent video conference rooms backed by the registered infrastructure.

## Role In The System

The application is split into three main runtime layers:

- `src/livekit/` is the SFU layer.
  - It provides the media plane and conferencing runtime.
- `src/coordinator/` is the coordination layer.
  - It provides Redis-backed cluster coordination, job dispatching, ingress, and egress state.
- `src/routes/` is the meeting app backend routes service.
  - It contains the API/backend behavior split out from `livekit-examples/meet`.
- `src/client/` is the meeting app frontend.
  - It contains the user-facing conferencing UI split out from `livekit-examples/meet`.

The contract layer sits above those components and provides the registry that ties worker participation to the application model.

## Contract Boundary

The contract should stay focused on registry and coordination responsibilities.

- It should track worker registration and availability.
- It should support the workflow that maps workers to video infrastructure participation.
- It should expose the minimum metadata needed for the application to reason about rented rooms and node membership.
- It should not own Redis runtime state; that belongs to `src/coordinator/`.
- Operational secrets and deployment metadata for the mainnet contract live in `secrets/contract.env`.
- That file is for private values only and should never be committed to git.

Implementation details for the on-chain contract are intentionally kept separate from the cloud deployment testbed.

## Relationship To IaC

`IaC/` is the cloud testbed for the app.

- It is used to build images, provision infrastructure, and configure nodes for future deployments.
- It is not the contract implementation itself.
- It exists to validate how the app can be deployed across cloud providers once the contract-backed registry is in place.

## Naming Model

The internal infrastructure role model remains:

- `worker`
- `client`
- `coordinator`

For compatibility, the CLI still accepts these aliases:

- `livekit` -> `worker`
- `meet` -> `client`
