# Infrastructure as Code

`IaC/` is managed through the root `./vidctl` command. Do not call Pulumi or Ansible directly from this repository; `vidctl infra` wraps those tools with the required environment, credential loading, local state, and Mitogen configuration.

The current Pulumi project is scaffold-only. It loads cloud credentials, exports Ansible inventory data, and does not create paid cloud resources until resource definitions are added to `pulumi/__main__.py`.

## Bootstrap

```bash
./vidctl bootstrap
./vidctl doctor
```

`bootstrap` creates `IaC/.venv`, installs `IaC/requirements.txt`, and prepares local Pulumi state under ignored `secrets/pulumi-state`. It also creates ignored `secrets/pulumi-passphrase` for non-interactive local secrets encryption.

## Credentials

Credential files are read automatically; do not manually export them.

- `secrets/cloud/digital-ocean.env`: expects `DIGITALOCEAN_TOKEN`.
- `secrets/cloud/alibaba-cloud.env`: supports `ALICLOUD_*` cloud variables and `ALICLOUD_CR_*` registry variables.

Secret values are never printed by `doctor`.

## Infrastructure

```bash
./vidctl infra init
./vidctl infra preview
./vidctl infra apply --yes
./vidctl infra inventory
./vidctl infra ping
./vidctl infra configure
./vidctl infra deploy --yes
```

`infra inventory` writes `IaC/ansible/inventory/hosts.generated.yml` from the Pulumi `ansibleInventory` output.

## Contract

```bash
./vidctl contract build
./vidctl contract test
./vidctl contract check
./vidctl contract publish --dry-run
```

Use `./vidctl contract publish --yes --gas-budget <MIST>` only when you intend to publish on-chain.

## Registry

```bash
./vidctl registry login
./vidctl registry build --service frontend
./vidctl registry push --service frontend
./vidctl registry publish --all
```

Registry commands use `ALICLOUD_CR_REGISTRY`, `ALICLOUD_CR_USERNAME`, and `ALICLOUD_CR_PASSWORD`. `ALICLOUD_CR_REGISTRY` is treated as the full image prefix, for example `registry.cn-hangzhou.aliyuncs.com/xaisen`.
