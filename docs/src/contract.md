# Contract Layer

Sui on-chain contract boundary for Xaisen.

## Purpose

The contract is the economic coordination layer for the platform:

- Workers register node metadata and stake collateral before becoming available.
- Clients order rooms with a fixed participant capacity.
- Workers vote to assign rooms and infrastructure roles.
- Payments are held in escrow until completion or cancellation.
- Completed rentals pay worker rewards on-chain.

LiveKit media transport, participant tokens, Redis coordination, and operational room state remain off-chain.

## Implementation

The Sui Move package lives in `src/contract`.

- `sources/node_registry.move` implements the generic `Registry<T>` with marketplace, voting, and role assignment.
- `tests/node_registry_tests.move` covers registration, staking, hiring, escrow, voting, capacity, role assignment, and withdrawal guards.

## Marketplace Model

### Worker Registration

- Workers register with a metadata URI, 32-byte metadata hash, fixed price per rental, and a required stake (minimum 1000 MIST).
- Registration increments the active worker count used for voting quorum.
- Workers can update metadata, toggle active/inactive status, and update pricing.
- Deactivating decrements the active worker count; reactivating increments it.
- Stake withdrawal requires the worker to be inactive with no active rental.

### Direct Hire (legacy)

- Clients hire a specific worker by paying exactly the worker's fixed price with `Coin<T>`.
- The `hire_worker` function accepts a `capacity` parameter specifying the room's participant limit.
- One worker can have one active rental at a time.

### Room Ordering with Voting

- Clients call `order_room` specifying room name, capacity, and payment.
- The rental enters `AWAITING_ASSIGNMENT` status with a `RoomAssignmentProposal`.
- Active workers vote on which worker should serve the room via `cast_room_vote`.
- Each worker gets one vote per proposal, nominating a specific node.
- When a nominee receives votes from more than half the active workers, the proposal finalizes: the rental becomes `ACTIVE` and the worker is assigned.
- Proposals have a 1-hour deadline. After expiration, `cancel_expired_order` refunds the client.

### Infrastructure Role Voting

- Workers propose infrastructure role assignments via `propose_role`: SFU (0), Coordinator (1), or Router (2).
- The proposer's vote is counted automatically.
- Other workers vote via `cast_role_vote`.
- When a majority is reached, the role is written to the on-chain role map.
- Roles can be queried via `worker_role` and `has_worker_role`.

### Escrow and Settlement

- Pending rental funds are held as contract escrow in a `Balance<T>`.
- The client can complete a pending or active rental, releasing escrow to the worker owner.
- The client can cancel a pending rental, refunding escrow.

## Entry Functions

| Function | Purpose |
|---|---|
| `create_registry` | Create shared `Registry<T>` object |
| `register_worker` | Register with metadata, price, and stake |
| `update_worker_metadata` | Update metadata URI and hash |
| `set_worker_active` | Toggle active/rentable status |
| `update_worker_price` | Change rental price |
| `unregister_worker` | Remove worker, return stake |
| `withdraw_worker_stake` | Withdraw stake (must be inactive + idle) |
| `hire_worker` | Direct hire with capacity (legacy) |
| `order_room` | Client orders room with voting-based assignment |
| `cast_room_vote` | Worker votes on room assignment |
| `cancel_expired_order` | Refund client after expired proposal |
| `complete_rental` | Client completes rental, pays worker |
| `cancel_rental` | Client cancels rental, gets refund |
| `propose_role` | Propose infrastructure role for a worker |
| `cast_role_vote` | Vote on a role proposal |

## Events

`WorkerRegistered`, `WorkerMetadataUpdated`, `WorkerStatusUpdated`, `WorkerUnregistered`, `WorkerPriceUpdated`, `WorkerStakeWithdrawn`, `WorkerHired`, `RentalCompleted`, `RentalCanceled`, `WorkerRewardPaid`, `RoomOrderCreated`, `VoteCast`, `RoomAssignmentFinalized`, `RoleProposalCreated`, `RoleAssigned`, `ProposalExpired`

## Build And Test

```bash
sui move test --path src/contract --build-env testnet
sui move build --path src/contract --build-env testnet
```

## Naming Model

The internal infrastructure role model:

- `worker` (alias: `livekit`)
- `client` (alias: `meet`)
- `coordinator`
