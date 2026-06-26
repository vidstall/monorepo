# Xaisen

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![Terraform 1.6+](https://img.shields.io/badge/Terraform-1.6%2B-844FBA.svg)
![Docker](https://img.shields.io/badge/Docker-runtime-2496ED.svg)

A decentralized video conferencing platform powered by a contract-backed node registry with worker voting.

## Overview

Xaisen connects customers who need video conference rooms with workers that provide the infrastructure for running them. Workers register on-chain by staking collateral, and the network assigns rooms through worker voting. The contract layer handles the marketplace, escrow, and governance, while the runtime layer handles conferencing, media routing, backend APIs, frontend UX, and Redis-backed coordination.

![Xaisen system architecture](docs/images/architecture.svg)

## Key Features

- **Decentralized worker registry** — workers register on-chain with stake and metadata.
- **Room ordering with capacity** — clients order rooms specifying a fixed participant count.
- **Worker voting** — workers vote to assign rooms and infrastructure roles (SFU, coordinator, router).
- **Escrow payments** — rental payments are held on-chain until completion or cancellation.
- **LiveKit SFU media plane** — real-time conferencing with WebRTC transport.
- **Cloud testbed pipeline** — Terraform, Ansible, and Docker for repeatable deployments on Alibaba Cloud.
- **Scenario-based benchmarking** — executable test scenarios with per-entity performance tracking.

## Quick Start

### Prerequisites

- Python 3.8+
- Terraform 1.6+
- Ansible 2.14+
- Sui CLI with a funded wallet (for contract operations)
- Docker-compatible target hosts

### Deploy a testbed

```bash
git clone https://github.com/your-username/xaisen.git
cd xaisen
python3 vidctl.py --help

# Deploy infrastructure + contract in one command
python3 vidctl.py deploy --provider alibaba-cloud \
  --worker-nodes 3 --coordinator-nodes 1 \
  --deploy-contract --contract-network testnet
```

### Credentials

Provider credentials live in `secrets/cloud/<provider>.env`. Contract deployment metadata lives in `secrets/contract/<network>.env`. Runtime configuration (Docker images, LiveKit keys) lives in `secrets/runtime.env`.

See [`docs/cli.md`](docs/cli.md) for credential format and examples.

### Run a test scenario

```bash
# Dry-run (no infrastructure needed)
python3 vidctl.py run-scenario scenario/basic_room.py --dry-run

# Live run with JSON benchmark output
python3 vidctl.py run-scenario scenario/basic_room.py --output artifacts/report.json
```

## Documentation

### Operations & CLI

- [`docs/cli.md`](docs/cli.md) — CLI usage, credentials, and generated artifacts
- [`docs/IaC.md`](docs/IaC.md) — infrastructure overview and deployment pipeline
- [`docs/design.md`](docs/design.md) — system design: voting, capacity, and architecture

### Runtime Layer

- [`docs/src/contract.md`](docs/src/contract.md) — on-chain contract boundary
- [`docs/src/livekit.md`](docs/src/livekit.md) — LiveKit runtime layer
- [`docs/src/coordinator.md`](docs/src/coordinator.md) — Redis coordination layer
- [`docs/src/routes.md`](docs/src/routes.md) — backend routes service
- [`docs/src/client.md`](docs/src/client.md) — browser client

### Scenarios

- [`scenario/README.md`](scenario/README.md) — scenario format and API reference
- [`scenario/basic_room.py`](scenario/basic_room.py) — room lifecycle: register, order, vote, join, leave
- [`scenario/worker_churn.py`](scenario/worker_churn.py) — worker network dynamics
- [`scenario/capacity_stress.py`](scenario/capacity_stress.py) — rapid user join throughput
- [`scenario/role_voting.py`](scenario/role_voting.py) — infrastructure role assignment

## Project Structure

### Operations & CLI

- [`IaC/`](IaC/) — cloud testbed infrastructure (Terraform + Ansible)
- [`cli/`](cli/) — Python CLI modules backing `vidctl.py`
- [`scenario/`](scenario/) — test scenario scripts with benchmarks
- [`docs/`](docs/) — project documentation

### Runtime Layer

- [`src/contract/`](src/contract/) — Sui Move node registry with voting and escrow
- [`src/livekit/`](src/livekit/) — SFU and media runtime (Go)
- [`src/coordinator/`](src/coordinator/) — Redis-backed coordination and dispatch
- [`src/routes/`](src/routes/) — backend API service (Next.js, port 3001)
- [`src/client/`](src/client/) — browser frontend (Next.js, port 3000)

## Contributing

- Keep changes aligned with the docs-first layout of the repository.
- Prefer updating the relevant document under `docs/` when behavior or architecture changes.
- Keep runtime code, contract boundaries, and cloud testbed concerns separated.

## License

MIT
