# Xaisen

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![Terraform 1.6+](https://img.shields.io/badge/Terraform-1.6%2B-844FBA.svg)
![Packer 1.9+](https://img.shields.io/badge/Packer-1.9%2B-02A8EF.svg)

A decentralized video conferencing platform powered by a contract-backed node registry.

## Overview

Xaisen connects customers who need video conference rooms with workers that provide the infrastructure for running them. The contract layer acts as the node registry, while the runtime layer handles conferencing, media routing, backend APIs, frontend UX, and Redis-backed coordination.

![Xaisen system architecture](docs/images/architecture.svg)

## Key Features

- Decentralized infrastructure model where workers register through an on-chain node registry.
- Rentable video conference rooms backed by registered worker capacity.
- LiveKit SFU media plane for real-time conferencing and WebRTC transport.
- Cloud testbed pipeline using Packer, Terraform, and Ansible for repeatable deployments.

## Quick Start

### Prerequisites

- Python 3.8+
- Terraform 1.6+
- Packer 1.9+
- Ansible 2.14+

```bash
git clone https://github.com/your-username/xaisen.git
cd xaisen
python3 vidctl.py --help
python3 vidctl.py build --provider aws --role worker
```

Provider credentials live in `secrets/cloud/<provider>.env`. Contract deployment credentials and mainnet metadata live in `secrets/contract.env`. See [`docs/cli.md`](docs/cli.md) before running provider builds or deployments.

## Documentation

### Operations & CLI

- [`docs/cli.md`](docs/cli.md) - CLI usage, credentials, and generated artifacts
- [`docs/IaC.md`](docs/IaC.md) - infrastructure overview and deployment pipeline

### Runtime Layer

- [`docs/src/contract.md`](docs/src/contract.md) - on-chain contract boundary
- [`docs/src/livekit.md`](docs/src/livekit.md) - LiveKit runtime layer
- [`docs/src/coordinator.md`](docs/src/coordinator.md) - Redis coordination layer
- [`docs/src/routes.md`](docs/src/routes.md) - backend routes service
- [`docs/src/client.md`](docs/src/client.md) - browser client

## Project Structure

### Operations & CLI

- [`IaC/`](IaC/) - cloud testbed infrastructure
- [`docs/`](docs/) - project documentation
- [`vidctl.py`](vidctl.py) - CLI orchestration entrypoint

### Runtime Layer

- [`src/contract/`](src/contract/) - node registry and on-chain coordination boundary
- [`src/livekit/`](src/livekit/) - SFU and media runtime
- [`src/coordinator/`](src/coordinator/) - Redis-backed coordination and dispatch layer
- [`src/routes/`](src/routes/) - backend API service
- [`src/client/`](src/client/) - browser frontend

## Contributing

- Keep changes aligned with the docs-first layout of the repository.
- Prefer updating the relevant document under `docs/` when behavior or architecture changes.
- Keep runtime code, contract boundaries, and cloud testbed concerns separated.

## License

MIT
