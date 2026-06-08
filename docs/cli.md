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

Store contract deployment credentials and mainnet metadata in `secrets/contract.env`.

```env
AWS_ACCESS_KEY_ID="your_access_key"
AWS_SECRET_ACCESS_KEY="your_secret_key"
AWS_DEFAULT_REGION="us-east-1"
```

## Commands

### `deploy`

Run the Docker-based deployment pipeline:

1. `terraform apply`
2. `ansible-playbook`
3. Docker starts role containers on provisioned nodes.

```bash
./vidctl.py deploy --provider aws --worker-nodes 2 --client-nodes 1 --coordinator-nodes 1
```

The CLI writes a transient inventory file and SSH private key under `artifacts/ssh_config/`.

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

- `artifacts/ssh_config/<provider>-inventory.ini` - transient Ansible inventory
- `artifacts/ssh_config/<provider>-id_ed25519` - Terraform-generated SSH private key
