# VidCtl CLI

`vidctl.py` is the repository entrypoint for all testbed and contract operations.

## Prerequisites

- Python 3.8+
- Terraform 1.6+
- Ansible 2.14+
- Sui CLI (for contract commands)

## Credentials

### Cloud provider credentials

Store provider credentials in `secrets/cloud/`:

- `secrets/cloud/alibaba-cloud.env`
- `secrets/cloud/aws.env`
- `secrets/cloud/digital-ocean.env`
- `secrets/cloud/hetzner.env`

Example (`secrets/cloud/alibaba-cloud.env`):

```env
ALIBABA_CLOUD_ACCESS_KEY="your_access_key"
ALIBABA_CLOUD_SECRET_KEY="your_secret_key"
ALIBABA_CLOUD_REGION="ap-southeast-1"
```

### Runtime configuration

Store runtime config in `secrets/runtime.env`:

```env
XAISEN_WORKER_IMAGE=ghcr.io/your-org/xaisen-worker:latest
XAISEN_ROUTES_IMAGE=ghcr.io/your-org/xaisen-routes:latest
XAISEN_CLIENT_IMAGE=ghcr.io/your-org/xaisen-client:latest
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
```

Optional variables with defaults:

| Variable | Default |
|---|---|
| `XAISEN_COORDINATOR_IMAGE` | `redis:7.4-alpine` |
| `XAISEN_PROXY_IMAGE` | `caddy:2-alpine` |

### Contract metadata

Contract deployment metadata is auto-generated in `secrets/contract/<network>.env` by `deploy-contract` and `init-contract`. The routes service reads this file to expose public contract config and build wallet-signed Sui transaction bytes.

## Commands

### `deploy`

Provision infrastructure and configure nodes with Docker containers:

```bash
python3 vidctl.py deploy --provider alibaba-cloud --worker-nodes 3 --client-nodes 1 --coordinator-nodes 1
```

With integrated contract deployment (first-time setup):

```bash
python3 vidctl.py deploy --provider alibaba-cloud \
  --worker-nodes 3 --client-nodes 1 --coordinator-nodes 1 \
  --deploy-contract --contract-network testnet
```

The `--deploy-contract` flag publishes the Move package and creates the shared Registry object between Terraform provisioning and Ansible configuration. Contract metadata is written to `secrets/contract/<network>.env` and flows into the Ansible vars automatically.

CLI writes a transient inventory file and SSH private key under `artifacts/ssh_config/`.

### `destroy`

Tear down a single provider or all providers:

```bash
python3 vidctl.py destroy --provider alibaba-cloud
python3 vidctl.py destroy --provider all
```

### `inventory`

Render the transient Ansible inventory from Terraform output without running Ansible:

```bash
python3 vidctl.py inventory --provider alibaba-cloud
```

### `deploy-contract`

Publish `src/contract` to a new Sui package on `devnet`, `testnet`, or `mainnet`:

```bash
python3 vidctl.py deploy-contract --network testnet
```

Use this for first-time deployment only. On success, writes package, upgrade cap, gas object, deployer, and publish digest metadata into `secrets/contract/<network>.env`.

### `update-contract`

Upgrade an existing published package using the stored `CONTRACT_UPGRADE_CAP_ID`:

```bash
python3 vidctl.py update-contract --network testnet
```

Use `--skip-verify-compatibility` when upgrading with struct layout changes (e.g., after adding voting fields).

### `init-contract`

Create the shared `Registry<0x2::sui::SUI>` object for a published package:

```bash
python3 vidctl.py init-contract --network testnet
```

Run this after first-time `deploy-contract`.

### `run-scenario`

Execute a test scenario script with per-entity benchmarking:

```bash
# Dry-run (prints steps, no Sui transactions or API calls)
python3 vidctl.py run-scenario scenario/basic_room.py --dry-run

# Live run
python3 vidctl.py run-scenario scenario/basic_room.py

# Save benchmark report as JSON
python3 vidctl.py run-scenario scenario/basic_room.py --output artifacts/report.json
```

See [`scenario/README.md`](/scenario/README.md) for the scenario script format and available API.

## Generated Artifacts

- `artifacts/ssh_config/<provider>-inventory.yml` — transient Ansible inventory
- `artifacts/ssh_config/<provider>-id_ed25519` — Terraform-generated SSH private key
- `artifacts/ssh_config/<provider>-vars.json` — Ansible extra-vars (runtime + contract config)
- `secrets/contract/<network>.env` — contract deployment metadata (auto-generated)

## Command Reference

| Command | Purpose |
|---|---|
| `deploy --provider <p>` | Provision infra, configure nodes |
| `deploy --provider <p> --deploy-contract` | Provision infra, deploy contract, configure nodes |
| `destroy --provider <p>` | Tear down infra |
| `inventory --provider <p>` | Render Ansible inventory only |
| `deploy-contract --network <n>` | First-time contract publish |
| `update-contract --network <n>` | Upgrade existing contract |
| `init-contract --network <n>` | Create shared Registry object |
| `run-scenario <script>` | Execute a test scenario |
