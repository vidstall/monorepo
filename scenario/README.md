# Test Scenarios

Each `.py` file in this folder is a scenario script that `vidctl.py run-scenario` can execute against a live or dry-run testbed.

## Running

```bash
# Dry-run (prints steps, no Sui transactions or API calls)
python3 vidctl.py run-scenario scenario/basic_room.py --dry-run

# Live run against a deployed testbed
python3 vidctl.py run-scenario scenario/basic_room.py

# Save benchmark report as JSON
python3 vidctl.py run-scenario scenario/basic_room.py --output artifacts/report.json
```

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

Each method benchmarks itself and attaches the sample to the worker entity.

- `ctx.add_worker(entity_id, address)` — register a worker in the scenario
- `ctx.register_worker(entity_id, ...)` — call `register_worker` on-chain
- `ctx.deactivate_worker(entity_id)` — set worker inactive (drop from network)
- `ctx.activate_worker(entity_id)` — set worker active (rejoin network)
- `ctx.unregister_worker(entity_id)` — unregister and withdraw stake
- `ctx.worker_vote_room(entity_id, voter_node_id, rental_id, nominee_node_id)` — cast room assignment vote
- `ctx.worker_vote_role(entity_id, voter_node_id, proposal_id)` — cast role assignment vote

### Client lifecycle

- `ctx.add_client(entity_id, address)` — register a client in the scenario
- `ctx.order_room(entity_id, room_name, capacity, payment)` — order a room on-chain
- `ctx.complete_rental(entity_id, rental_id)` — complete a rental
- `ctx.cancel_rental(entity_id, rental_id)` — cancel a rental

### User lifecycle

- `ctx.add_user(entity_id, room_name)` — register a user in the scenario
- `ctx.join_room(entity_id, routes_url, rental_id)` — fetch connection details (benchmarks API latency)
- `ctx.leave_room(entity_id)` — record departure and session duration

## Benchmark Report

The report prints two sections:

**Aggregate metrics** — grouped by event name with count, min, avg, max, p50, p95.

**Per-entity metrics** — each worker, client, and user with their individual measurements.

JSON output (`--output`) includes both sections plus a full sample ledger with entity attribution.

## Available Scenarios

| Script | Workers | Clients | Description |
|---|---|---|---|
| `basic_room.py` | 3 | 1 | Room lifecycle: register, order, vote, join, leave, complete |
| `worker_churn.py` | 5 | 1 | Worker dynamics: join, drop, rejoin, unregister |
| `capacity_stress.py` | 3 | 2 | Rapid user joins, capacity enforcement, throughput |
| `role_voting.py` | 4 | 1 | Infrastructure role assignment via voting |
