# VidCtl CLI

`vidctl.py` is the repository entrypoint for the cloud testbed pipeline.

## Prerequisites

- Python 3.8+
- Terraform 1.6+
- Packer 1.9+
- Ansible 2.14+

## Credentials

Store provider credentials in `secrets/cloud/`:

- `secrets/cloud/aws.env`
- `secrets/cloud/digital-ocean.env`
- `secrets/cloud/hetzner.env`
- `secrets/cloud/alibaba-cloud.env`

Store contract deployment credentials and mainnet metadata in `secrets/contract.env`.
This file should hold private deployment information for the on-chain registry, such as the contract address, network identifiers, and any other values needed by the CLI or future contract tooling.

Example:

```env
AWS_ACCESS_KEY_ID="your_access_key"
AWS_SECRET_ACCESS_KEY="your_secret_key"
AWS_DEFAULT_REGION="us-east-1"
```

## Commands

### `build`

Build images for one provider.

```bash
./vidctl.py build --provider aws
```

Options:

- `--provider` - one of `aws`, `digital-ocean`, `hetzner`, `alibaba-cloud`
- `--role` - `all` or a single role (`worker`, `client`, `coordinator`, plus aliases `livekit`, `meet`)
- `--testbed-name` - image and resource prefix, default `depin-testbed`

### `deploy`

Run the full pipeline:

1. `packer build`
2. `terraform apply`
3. `ansible-playbook`

```bash
./vidctl.py deploy --provider aws --worker-nodes 2 --client-nodes 1 --coordinator-nodes 1
```

The CLI writes a transient inventory file and SSH private key under `artifacts/ssh_config/`.

The deploy flow reflects the app architecture:

- `worker` nodes run the video infrastructure layer.
- `client` nodes represent the conferencing frontend side in `src/client/`.
- `coordinator` nodes carry the Redis/coordination layer.

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

## Generated Artifacts

- `artifacts/image/manifest.json` - Packer build manifest
- `artifacts/ssh_config/<provider>-inventory.ini` - transient Ansible inventory
- `artifacts/ssh_config/<provider>-id_ed25519` - Terraform-generated SSH private key
