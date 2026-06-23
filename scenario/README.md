# Test Scenarios

End-to-end scenario scripts that deploy infrastructure, execute on-chain transactions, and establish real WebRTC connections via the LiveKit SFU.

## Prerequisites

```bash
pip install -r requirements.txt
```

Requires: `livekit`, `livekit-api`, `pyyaml`

## Running

```bash
# Dry-run (prints steps, no deploy, no transactions, no WebRTC)
python3 vidctl.py run-scenario scenario/basic_room.py --dry-run

# Full E2E: deploy infra + run scenario + teardown
python3 vidctl.py run-scenario scenario/basic_room.py \
  --provider alibaba-cloud --worker-nodes 3 --client-nodes 1 --coordinator-nodes 1 \
  --deploy-contract --contract-network testnet \
  --output artifacts/report.json --teardown

# Run against already-deployed infra (auto-detected from artifacts/)
python3 vidctl.py run-scenario scenario/basic_room.py --provider alibaba-cloud
```

### CLI flags

| Flag | Description |
|------|-------------|
| `--provider` | Cloud provider (default: alibaba-cloud) |
| `--worker-nodes` | Override worker count from topology |
| `--client-nodes` | Override client count from topology |
| `--coordinator-nodes` | Override coordinator count from topology |
| `--deploy-contract` | Publish + initialize Sui contract during deploy |
| `--contract-network` | Sui network (default: testnet) |
| `--teardown` | Destroy infrastructure after scenario completes |
| `--dry-run` | Print steps without executing anything |
| `--output` | Path to write JSON benchmark report |

## Scenario Script Format

Each script must define four module-level attributes:

```python
from cli.scenario import Topology, ScenarioContext

NAME = "my-scenario"
DESCRIPTION = "What this scenario tests"
TOPOLOGY = Topology(worker_nodes=3, client_nodes=1, coordinator_nodes=1, contract_network="testnet")

def run(ctx: ScenarioContext) -> None:
    # event timeline goes here
    ...
```

## ScenarioContext API

### Steps and logging

- `ctx.step("description")` — mark a new numbered step
- `ctx.log("message")` — print a log line under the current step
- `ctx.sleep(seconds, reason)` — pause execution
- `ctx.benchmark(name, fn, entity_id=...)` — time a callable, record the sample

### Worker lifecycle

- `ctx.add_worker(entity_id, address)` — register a worker in the scenario
- `ctx.register_worker(entity_id, ...)` — call `register_worker` on-chain
- `ctx.hire_worker(entity_id, worker_node_id, room_name, capacity, payment)` — direct hire, bypassing voting
- `ctx.deactivate_worker(entity_id)` — set worker inactive
- `ctx.activate_worker(entity_id)` — set worker active
- `ctx.unregister_worker(entity_id)` — unregister and withdraw stake
- `ctx.withdraw_worker_stake(entity_id)` — withdraw stake after deactivation
- `ctx.update_worker_metadata(entity_id, metadata_uri, metadata_hash)` — update metadata on-chain
- `ctx.update_worker_price(entity_id, price_per_rental)` — update price on-chain
- `ctx.worker_vote_room(entity_id, voter_node_id, rental_id, nominee_node_id)` — cast room assignment vote
- `ctx.worker_vote_role(entity_id, voter_node_id, proposal_id)` — cast role assignment vote

### Client lifecycle

- `ctx.add_client(entity_id, address)` — register a client in the scenario
- `ctx.order_room(entity_id, room_name, capacity, payment)` — order a room via voting
- `ctx.complete_rental(entity_id, rental_id)` — complete a rental
- `ctx.cancel_rental(entity_id, rental_id)` — cancel a pending rental (refund)
- `ctx.cancel_expired_order(entity_id, rental_id)` — cancel after vote deadline

### User lifecycle

- `ctx.add_user(entity_id, room_name)` — register a user in the scenario
- `ctx.join_room(entity_id, routes_url, rental_id)` — fetch token from routes service and connect via WebRTC
- `ctx.leave_room(entity_id)` — disconnect from the LiveKit room

Users that are rejected at capacity have `user.rejected = True`.

## Available Scenarios

| Script | Workers | Clients | Description |
|---|---|---|---|
| `basic_room.py` | 3 | 1 | Core lifecycle: register, order, vote, WebRTC join, session, leave, complete |
| `direct_hire.py` | 3 | 1 | Direct hire vs voting, both with real WebRTC, latency comparison |
| `capacity_enforcement.py` | 3 | 1 | Fill room to capacity, verify rejection, free slot, rejoin |
| `multi_room.py` | 3 | 2 | Multiple concurrent rooms with WebRTC, cancel, re-order |
| `worker_lifecycle.py` | 4 | 1 | Varying stakes, two exit paths, reduced pool continues |
