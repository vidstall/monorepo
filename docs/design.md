# Xaisen Design

This document describes the target application design, covering the contract model, runtime behavior, IaC testbed, and CLI surface.

## System Model

Xaisen is a decentralized video conferencing platform. Two actor types interact through an on-chain Sui contract:

- **Clients** order video conference rooms with a fixed participant capacity and pay for the service.
- **Workers** provide the infrastructure (LiveKit SFU nodes, coordination, routing) and earn payment by serving rooms.

The contract acts as the economic coordination layer — marketplace, escrow, and governance. The runtime stack (LiveKit, Redis, routes, browser client) handles the actual media transport and user experience.

## Contract Layer

### Existing Primitives (preserved)

The current `node_registry.move` contract provides:

- `Registry<T>` — shared object holding workers and rentals
- Worker registration with metadata, staking, and pricing
- Rental escrow — client pays, funds held until completion or cancellation
- Stake withdrawal guards — workers must deactivate and finish rentals first

### Extension: Room Capacity

Room orders gain a `capacity` field — the fixed number of participants the room supports.

- Client calls a room order function specifying `capacity` (e.g., 8 people) and pays accordingly.
- The contract stores capacity in the rental record.
- Pricing may scale with capacity (worker sets a per-seat or per-room price).
- The runtime uses the on-chain capacity to enforce participant limits when issuing LiveKit tokens.

### Extension: Worker Voting

Two voting scopes are added to the contract:

#### Room Assignment Voting

When a client submits a room order, instead of the client picking a specific worker, registered workers vote on who should serve the request.

- A room order enters a `pending_assignment` state.
- Active workers submit votes nominating a worker for the order.
- Once a quorum or majority is reached, the contract assigns the winning worker and transitions the rental to `active`.
- The assigned worker's `active_rental_id` is set, locking them to this room.
- If no quorum is reached within a timeout, the order can be canceled with a refund.

#### Infrastructure Role Voting

Workers also vote on cluster-level role assignments — who runs what infrastructure role.

- Roles: `sfu` (LiveKit media node), `coordinator` (Redis coordination), `router` (routes API).
- Workers propose and vote on role assignments for registered nodes.
- The contract stores the current role map as on-chain state.
- Role reassignment requires a new vote round.
- This replaces static Ansible-driven role assignment with dynamic, contract-governed topology.

#### Voting Mechanics

- Only active, staked workers can vote.
- Each worker gets one vote per proposal.
- A proposal passes when it reaches a simple majority of active workers (configurable threshold).
- Vote rounds have a deadline (clock-based). Expired rounds are discarded.
- Events are emitted for vote cast, proposal passed, and proposal expired.

## Runtime Layer

### `src/contract/`

Sui Move package. Extends the existing `node_registry.move` with:

- Room order function accepting `capacity`.
- `VoteProposal` and `Vote` structs for both room assignment and role assignment.
- Vote submission, tallying, and finalization entry functions.
- Role map storage and query functions.
- Events for all voting lifecycle transitions.

### `src/livekit/`

LiveKit SFU server (Go). No changes to the server itself. Workers assigned the `sfu` role by contract voting run this service. Configuration (node IP, Redis address, API keys) is injected at deployment time.

### `src/coordinator/`

Redis-backed coordination. No changes to Redis itself. The node assigned the `coordinator` role by contract voting runs this service. Deployed as a Docker container with the existing `redis.conf`.

### `src/routes/`

Backend API service (Next.js, port 3001). Responsibilities:

- Reads contract state to resolve the current role map and active room assignments.
- Enforces room capacity when generating LiveKit participant tokens — rejects joins beyond the on-chain capacity.
- Exposes contract configuration to the client frontend.
- Builds unsigned Sui transaction bytes for client-side wallet signing (room orders, vote submissions).

### `src/client/`

Browser frontend (Next.js, port 3000). Two user flows:

#### Owner Flow

1. Owner connects Sui wallet via `@mysten/dapp-kit-react`.
2. Owner creates a room order: selects capacity, confirms payment.
3. Frontend calls routes API to build the transaction bytes, owner signs with wallet.
4. Frontend polls or subscribes to contract events for assignment confirmation.
5. Once a worker is assigned, owner receives room connection details and shares a join link with guests.

#### Guest Flow

1. Guest opens the join link (no wallet required).
2. Frontend fetches connection details from routes API.
3. Guest joins the LiveKit room as a participant.
4. Room enforces the capacity limit set in the contract.

#### Worker Dashboard (future)

- Workers view pending room orders and cast votes.
- Workers view and vote on infrastructure role proposals.
- Workers monitor their earnings and stake status.

## IaC Testbed

### Purpose

The IaC layer provisions a testbed on Alibaba Cloud for validating the full system end-to-end. It is not a production deployment system.

### Pipeline

`vidctl.py deploy` runs the following sequence:

1. **Terraform** provisions Alibaba Cloud ECS instances for the specified number of workers and clients, plus one coordinator node. Generates SSH keys and inventory data.
2. **Contract deployment** publishes the Move package to the configured Sui network (devnet/testnet) and creates the shared Registry object. Contract metadata is written to `secrets/contract/<network>.env`.
3. **Ansible** configures all provisioned nodes — installs Docker, deploys the correct container per role, injects contract addresses and API keys.

### Testbed Shape

```
vidctl.py deploy --provider alibaba-cloud --worker-nodes 3 --client-nodes 2 --coordinator-nodes 1
```

This provisions:

- 3 worker nodes — each runs the LiveKit SFU container, configured to connect to the coordinator Redis and registered on-chain as a worker.
- 2 client nodes — each runs the routes API + client frontend + Caddy reverse proxy.
- 1 coordinator node — runs Redis, bound to its private IP.

All nodes are in the same Alibaba Cloud VPC with security group rules for SSH, HTTP (80), LiveKit ports (7880, 7881, 7882), and Redis (6379, private network only).

### Teardown

```
vidctl.py destroy --provider alibaba-cloud
```

Destroys all Terraform-managed resources and cleans up local artifacts.

## VidCtl CLI

`vidctl.py` is the single entrypoint for all testbed operations.

### Infrastructure Commands

| Command | Purpose |
|---|---|
| `deploy --provider alibaba-cloud` | Provision infra, deploy contract, configure nodes |
| `destroy --provider alibaba-cloud` | Tear down all infra |
| `inventory --provider alibaba-cloud` | Render Ansible inventory without running playbook |

### Contract Commands

| Command | Purpose |
|---|---|
| `deploy-contract --network testnet` | First-time publish of Move package |
| `update-contract --network testnet` | Upgrade existing package |
| `init-contract --network testnet` | Create shared Registry object |

### Credentials

- Alibaba Cloud credentials: `secrets/cloud/alibaba-cloud.env`
- Contract metadata: `secrets/contract/<network>.env`
- Runtime config (API keys, image names): `secrets/runtime.env`
- Generated artifacts: `artifacts/ssh_config/`

### Required Runtime Environment Variables

| Variable | Purpose |
|---|---|
| `XAISEN_CLIENT_IMAGE` | Docker image for client frontend |
| `XAISEN_ROUTES_IMAGE` | Docker image for routes API |
| `XAISEN_WORKER_IMAGE` | Docker image for LiveKit SFU |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret |

Optional variables with defaults:

| Variable | Default | Purpose |
|---|---|---|
| `XAISEN_COORDINATOR_IMAGE` | `redis:7.4-alpine` | Docker image for coordinator |
| `XAISEN_PROXY_IMAGE` | `caddy:2-alpine` | Docker image for reverse proxy |

## Scenario Framework

Test scenarios live in `scenario/` as executable Python scripts. Each scenario defines a topology, an ordered event timeline, and per-entity benchmarks.

### Running scenarios

```bash
python3 vidctl.py run-scenario scenario/basic_room.py --dry-run
python3 vidctl.py run-scenario scenario/basic_room.py --output artifacts/report.json
```

### Available scenarios

| Script | Description |
|---|---|
| `basic_room.py` | 3 workers, 1 client, room with capacity 5, users join/leave, rental completes |
| `worker_churn.py` | 5 workers joining, dropping, rejoining while serving rooms |
| `capacity_stress.py` | Rapid user joins (20+50), capacity rejection, throughput |
| `role_voting.py` | SFU/Coordinator/Router role assignment via voting |

### Per-entity tracking

Every worker, client, and user is tracked individually with:

- **Workers**: registration latency, vote latency, uptime, active/inactive transitions
- **Clients**: room order latency, rental completion latency
- **Users**: join latency, session duration, disconnect type

Reports include both aggregate statistics (min/avg/max/p50/p95) and per-entity breakdowns.

## Implementation Status

All items are implemented:

1. `build_contract_env()` in `cli/env.py` — done
2. Contract extensions (capacity, voting, roles) — done, 35 tests passing
3. Contract tests — done, 12 new tests
4. Routes API (new endpoints, capacity enforcement) — done
5. Client frontend (voting forms, capacity error handling) — done
6. IaC integration (`--deploy-contract` flag) — done
7. Scenario framework with per-entity benchmarks — done
