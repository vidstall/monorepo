# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Xaisen is a decentralized video conferencing platform. Customers rent video conference rooms from workers who register infrastructure capacity through an on-chain Sui contract (node registry). Workers register on-chain with stake, clients order rooms specifying capacity, and workers vote to assign rooms and infrastructure roles (SFU, coordinator, router). Payments are held in escrow until completion or cancellation. The runtime handles media routing (LiveKit SFU), backend APIs, browser UX, and Redis-backed coordination.

## Architecture

The codebase has two layers:

**Runtime layer** (`src/`):
- `src/contract/` — Sui Move smart contract (`xaisen_contract`). On-chain node registry with voting, escrow, and capacity. Tests in `src/contract/tests/`.
- `src/livekit/` — LiveKit SFU server (Go, forked from `livekit/livekit-server`). WebRTC media plane.
- `src/coordinator/` — Redis-backed coordination/dispatch. Docker Compose service with custom redis.conf.
- `src/routes/` — Backend API service (Next.js on port 3001, pnpm). Builds Sui transaction bytes, exposes contract config, handles CORS. Key files in `lib/` (contract-config, contract-transactions, contract-route, cors).
- `src/client/` — Browser frontend (Next.js on port 3000, pnpm). LiveKit React components, Sui dApp wallet integration (`@mysten/dapp-kit-react`), Krisp noise filter.

**Operations layer**:
- `cli/` — Python CLI modules backing `vidctl.py`. Subcommands: deploy, destroy, inventory, contract deploy, contract update, contract status, contract wallet, run-scenario.
- `IaC/terraform/` — Provider environments (aws, digital-ocean, hetzner, alibaba-cloud) with shared `modules/node_pool`.
- `IaC/ansible/` — Post-provision configuration. Roles: worker, client, coordinator. Single playbook `playbooks/site.yml`.
- `scenario/` — Executable test scenarios with per-entity benchmarking. Each script defines `NAME`, `DESCRIPTION`, `TOPOLOGY`, and a `run(ctx: ScenarioContext)` function.

## Common Commands

### CLI (vidctl.py)
```bash
python3 vidctl.py deploy --provider aws --media-nodes 1 --coordinator-nodes 1
python3 vidctl.py destroy --provider aws
python3 vidctl.py inventory --provider aws
python3 vidctl.py contract deploy --network testnet
python3 vidctl.py contract update --network testnet

# Deploy infra + contract together
python3 vidctl.py deploy --provider alibaba-cloud --media-nodes 3 --coordinator-nodes 1 \
  --deploy-contract --contract-network testnet

# Run scenarios
python3 vidctl.py run-scenario scenario/basic_room.py --dry-run
python3 vidctl.py run-scenario scenario/basic_room.py --output artifacts/report.json
```

### Frontend services (pnpm)
```bash
# Client (port 3000)
cd src/client && pnpm install && pnpm dev

# Routes (port 3001)
cd src/routes && pnpm install && pnpm dev
```

### Linting and formatting
```bash
# Client (has both lint and format)
cd src/client && pnpm lint && pnpm format:check
cd src/client && pnpm lint:fix && pnpm format:write

# Routes (format only, no lint script)
cd src/routes && pnpm format:check
```

### Tests
```bash
# Python CLI tests
python3 -m pytest tests/

# Single test file
python3 -m pytest tests/test_infra.py

# Client (vitest)
cd src/client && pnpm test

# Move contract tests
cd src/contract && sui move test
```

### Terraform
```bash
cd IaC/terraform/environments/<provider> && terraform init && terraform plan
```

## Credentials

- Cloud provider creds: `secrets/cloud/<provider>.env` (aws, digital-ocean, hetzner, alibaba-cloud)
- Contract metadata: `secrets/contract/<network>.env` (devnet, testnet, mainnet)
- Runtime configuration (Docker images, LiveKit keys): `secrets/runtime.env`
- Generated SSH keys and inventory: `artifacts/ssh_config/`

## Key Conventions

- The deployment pipeline is: Terraform provisions → generates SSH material/inventory → Ansible installs Docker and runs role containers.
- `vidctl.py` is the single entrypoint that sequences Terraform and Ansible steps.
- Contract lifecycle: `contract deploy` (publish package and create shared Registry object) → `contract update` (upgrades). Metadata is persisted in `secrets/contract/<network>.env`.
- Each runtime service has its own Dockerfile for containerized deployment.
- The `routes` service reads contract env files to expose public contract config and build wallet-signed Sui transaction bytes for the client.
- Scenario scripts in `scenario/` use the `ScenarioContext` API from `cli/scenario.py` for worker/client lifecycle operations and per-entity benchmarking. See `scenario/README.md` for the full API.
- Documentation lives in `docs/` — update the relevant doc when behavior or architecture changes.
