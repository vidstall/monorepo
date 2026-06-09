# VidCtl CLI

`vidctl.py` is the repository entrypoint for the cloud testbed pipeline.

## Prerequisites

- Python 3.8+
- Terraform 1.6+
- Ansible 2.14+

## Credentials

Store provider credentials in `secrets/cloud/`:

- `secrets/cloud/aws.env`
- `secrets/cloud/digital-ocean.env`
- `secrets/cloud/hetzner.env`
- `secrets/cloud/alibaba-cloud.env`

Store contract deployment metadata in `secrets/contract/devnet.env`, `secrets/contract/testnet.env`, or `secrets/contract/mainnet.env`. The routes service reads the selected network file to expose public contract config and build wallet-signed Sui transaction bytes.

```env
AWS_ACCESS_KEY_ID="your_access_key"
AWS_SECRET_ACCESS_KEY="your_secret_key"
AWS_DEFAULT_REGION="us-east-1"
```

## Commands

### `deploy`

Run the Docker-based deployment pipeline:

```bash
./vidctl.py deploy --provider aws --worker-nodes 2 --client-nodes 1 --coordinator-nodes 1
```

CLI writes a transient inventory file and SSH private key under `artifacts/ssh_config/`.

### `destroy`

Tear down a single provider or all providers.

```bash
./vidctl.py destroy --provider all
```

### `inventory`

Render the transient Ansible inventory from Terraform output without running Ansible.

```bash
./vidctl.py inventory --provider aws
```

### `deploy-contract`

Publish `src/contract` to a new Sui package on `devnet`, `testnet`, or `mainnet`.

```bash
./vidctl.py deploy-contract --network testnet --package-path ./src/contract --gas-budget 100000000
```

Use this for first-time deployment. If Sui reports that the package is already published, use `update-contract` for regular package upgrades. On success, the command writes package, upgrade cap, gas object, deployer, and publish digest metadata into `secrets/contract/<network>.env`.

### `update-contract`

Upgrade an existing published package using the stored `CONTRACT_UPGRADE_CAP_ID`. If `secrets/contract/<network>.env` is missing package metadata, the command falls back to `Published.toml` in the package path.

```bash
./vidctl.py update-contract --network testnet --package-path ./src/contract --gas-budget 100000000
```

On success, the command updates `CONTRACT_PACKAGE_ID`, preserves `CONTRACT_REGISTRY_OBJECT_ID`, records `CONTRACT_PREVIOUS_PACKAGE_ID`, and writes the latest upgrade digest into `CONTRACT_UPDATE_TX_DIGEST`. Use `--skip-verify-compatibility` only when you intentionally want to bypass Sui upgrade compatibility checks.

### `init-contract`

Create the shared `Registry<0x2::sui::SUI>` object for a published package and write its object id into `secrets/contract/<network>.env`.

```bash
./vidctl.py init-contract --network testnet --package-path ./src/contract --gas-budget 100000000
```

Run this after first-time `deploy-contract`. If the env file is missing, `init-contract` can recover the package id and upgrade cap from `Published.toml`.

## Generated Artifacts

- `artifacts/ssh_config/<provider>-inventory.ini` - transient Ansible inventory
- `artifacts/ssh_config/<provider>-id_ed25519` - Terraform-generated SSH private key
