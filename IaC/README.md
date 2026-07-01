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
- `secrets/cloud/alibaba-cloud.env`: supports `ALICLOUD_*` cloud variables.
- `secrets/registry/<provider>.env`: stores registry image prefix and Docker login credentials.

Secret values are never printed by `doctor`.

## Infrastructure

```bash
./vidctl infra init --env devnet
./vidctl infra preview
./vidctl infra apply --yes
./vidctl infra inventory
./vidctl infra ping
./vidctl infra configure
./vidctl infra deploy --yes
./vidctl start --name <instance> --service routes --provider digitalocean
./vidctl pause --name <instance> --service routes --provider digitalocean
./vidctl restart --name <instance> --service routes --provider digitalocean
./vidctl kill --name <instance> --service routes --provider digitalocean --yes
```

`infra init --env <network>` creates or updates `runtime/topology.toml`, points it at
`runtime/contract/<network>.env`, and selects or creates the matching Pulumi stack.
Top-level lifecycle commands update that topology, run Pulumi from `IaC/pulumi`, and
append an audit event to `runtime/history.toml`. Cloud control must be implemented
through Pulumi providers in `IaC/pulumi`; `vidctl` does not call cloud CLIs directly.

`infra inventory` writes `IaC/ansible/inventory/hosts.generated.yml` from the Pulumi `ansibleInventory` output.

## Contract

```bash
./vidctl contract build
./vidctl contract test
./vidctl contract check
./vidctl contract publish --dry-run
```

Use `./vidctl contract publish --yes --gas-budget <MIST>` only when you intend to publish on-chain.
On a successful publish or a sync of an already-published package, `vidctl` writes `runtime/contract/<env>.env` for the selected network.

## Registry

```bash
./vidctl registry login --provider alibaba
./vidctl registry build --service frontend
./vidctl registry push --service frontend
./vidctl registry publish --all
```

`registry login` loads `secrets/registry/<provider>.env`, for example `secrets/registry/dockerhub.env` or `secrets/registry/selfhost.env`. After a successful login, `vidctl` writes the selected provider and per-service image repositories to `runtime/registry.toml`. `registry build`, `registry push`, and `registry publish` read image names from that runtime file.

Each provider env file uses generic keys:

```bash
export REGISTRY_PREFIX="registry.example.com/xaisen"
export REGISTRY_USERNAME="username"
export REGISTRY_PASSWORD="password"
```

`REGISTRY_PREFIX` is the full image prefix, for example `registry.cn-hangzhou.aliyuncs.com/xaisen`, `registry.digitalocean.com/xaisen`, or `docker.io/xaisen`. For backward compatibility, the default `alibaba` provider falls back to `ALICLOUD_CR_REGISTRY`, `ALICLOUD_CR_USERNAME`, and `ALICLOUD_CR_PASSWORD` when `secrets/registry/alibaba.env` is absent.
