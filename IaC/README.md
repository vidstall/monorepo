# Infrastructure as Code

`IaC/` is managed through the root `./vidctl` command. Do not call Pulumi or Ansible directly from this repository; `vidctl infra` wraps those tools with the required environment, credential loading, local state, and Mitogen configuration.

Pulumi manages topology state, frontend object-storage sites, and Ansible inventory exports. VM-style services are configured by Ansible after Pulumi. The `frontend` service is the exception: it uses the same lifecycle commands, but is deployed as a static object-storage site instead of a VM.

## Bootstrap

```bash
./vidctl bootstrap
./vidctl doctor
```

`bootstrap` creates `IaC/.venv`, installs `IaC/requirements.txt`, and prepares local Pulumi state under ignored `secrets/pulumi-state`. It also creates ignored `secrets/pulumi-passphrase` for non-interactive local secrets encryption.

## Credentials

Credential files are read automatically; do not manually export them.

- `secrets/cloud/digital-ocean.env`: expects `DIGITALOCEAN_TOKEN`.
- `secrets/cloud/upcloud.env`: expects `UPCLOUD_TOKEN`.
- `secrets/cloud/akamai.env`: expects `LINODE_TOKEN` (Akamai Cloud Compute is provisioned via the Linode API).
- `secrets/cloud/alibaba.env`: supports `ALICLOUD_*` cloud variables for the Alibaba admin account.
- `secrets/cloud/cloudflare.env`: expects `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and for R2 uploads `CLOUDFLARE_R2_ACCESS_KEY_ID` / `CLOUDFLARE_R2_SECRET_ACCESS_KEY`.
- `secrets/registry/<provider>.env`: stores registry image prefix and Docker login credentials.

Secret values are never printed by `doctor`.

Example Cloudflare R2 credentials:

```bash
export CLOUDFLARE_API_TOKEN="..."
export CLOUDFLARE_ACCOUNT_ID="..."
export CLOUDFLARE_R2_ACCESS_KEY_ID="..."
export CLOUDFLARE_R2_SECRET_ACCESS_KEY="..."
# Optional, used only for exported site metadata:
export CLOUDFLARE_R2_PUBLIC_URL="https://static.example.com"
```

For compatibility, `cloudflare.env` may also use generic Cloudflare/R2 keys:

```bash
export ACCOUNT_ID="..."
export API_TOKEN="..."
export ACCESS_KEY_ID="..."
export SECRET_ACCESS_KEY="..."
export S3_API_ENDPOINT="https://ACCOUNT_ID.r2.cloudflarestorage.com"
```

## Infrastructure

```bash
./vidctl infra init --env devnet
./vidctl infra preview
./vidctl infra apply --yes
./vidctl infra inventory
./vidctl infra ping
./vidctl infra configure
./vidctl infra deploy --yes
./vidctl infra start --name INSTANCE --service routes --provider digitalocean
./vidctl infra pause --name INSTANCE --service routes --provider digitalocean
./vidctl infra restart --name INSTANCE --service routes --provider digitalocean
./vidctl infra kill --name INSTANCE --service routes --provider digitalocean --yes
./vidctl infra start --name SITE --service frontend --provider cloudflare
```

`infra init --env NETWORK` creates or updates `runtime/topology.toml`, points it at `runtime/contract/NETWORK.env`, and selects or creates the matching Pulumi stack.

Lifecycle commands update topology, run Pulumi from `IaC/pulumi`, and append an audit event to `runtime/history.toml`. VM services (`routes`, `media`, `coordinator`, `vclient`) continue through Pulumi inventory and Ansible. `frontend` uses object storage:

- `start`: builds `services/client/client/dist`, creates/updates object storage, uploads static files, and marks the site running.
- `restart`: rebuilds and re-uploads static files while keeping the same bucket identity.
- `pause`: keeps the bucket/files and marks the site stopped; provider adapters make the site private where supported.
- `kill --yes`: deletes the managed object-storage resources.

`infra inventory` writes `IaC/ansible/inventory/hosts.generated.yml` from the Pulumi `ansibleInventory` output. Frontend object-storage instances are excluded from that inventory.

## Contract

```bash
./vidctl contract build
./vidctl contract test
./vidctl contract check
./vidctl contract publish --dry-run
```

Use `./vidctl contract publish --yes --gas-budget MIST` only when you intend to publish on-chain. On a successful publish or a sync of an already-published package, `vidctl` writes `runtime/contract/ENV.env` for the selected network.

## Registry

```bash
./vidctl registry login --provider alibaba
./vidctl registry build --service frontend
./vidctl registry push --service frontend
./vidctl registry publish --all
```

`registry login` loads `secrets/registry/<provider>.env`, `secrets/registry/dockerhub.env`, or `secrets/registry/selfhost.env`. `vidctl` writes the selected provider and per-service image repositories to `runtime/registry.toml`. `registry build`, `registry push`, and `registry publish` read image names from that runtime file.

Each provider env file uses generic keys:

```bash
export REGISTRY_PREFIX="registry.example.com/xaisen"
export REGISTRY_USERNAME="username"
export REGISTRY_PASSWORD="password"
```

`REGISTRY_PREFIX` is the full image prefix, such as `registry.cn-hangzhou.aliyuncs.com/xaisen`, `registry.digitalocean.com/xaisen`, or `docker.io/xaisen`. The default `alibaba` provider falls back to `ALICLOUD_CR_REGISTRY`, `ALICLOUD_CR_USERNAME`, and `ALICLOUD_CR_PASSWORD` when `secrets/registry/alibaba.env` is absent.
