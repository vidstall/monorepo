# Scenarios

A scenario file declares a full deployment: which network/env to publish the
contract on, which frontend sites to publish, which Docker images to publish,
and which workers (service daemons running on VM hosts) should be running.
`vidctl scenario apply <path> --yes` applies one scenario file as the complete
source of truth for compute workers (`[[workers]]`). Frontend sites
(`[[frontends]]`) are publish-only -- a scenario updates them but never
deletes/recreates them, since domain/SSL setup on an object-storage-hosted
frontend (e.g. Alibaba OSS) is too costly to churn automatically.

```bash
./vidctl scenario apply scenario/example.toml --yes
./vidctl scenario apply scenario/digitalocean-sample.toml --yes
./vidctl scenario status
./vidctl scenario destroy
```

Only one scenario can be active at a time. While a scenario is active, manual
`vidctl infra ...` commands and `vidctl scenario apply` of a *different* file
are refused -- run `vidctl scenario destroy` first, or re-apply the same file
to reconcile drift.

## Fields

- `name` -- human-readable label (used in status/log output).
- `env` -- `devnet` | `testnet` | `mainnet`. Scenario-wide; every worker in
  the file is provisioned against this one Sui/Pulumi environment.
- `[contract]` -- passed through to `contract.publish()`: `gas_budget`,
  `create_registry_if_missing`, `force`. Publish is always confirmed
  (`--yes`) internally once you've confirmed `scenario apply` itself.
- `[registry]` -- `provider` (optional; if set, `scenario apply` runs
  `registry.login(provider)` itself before publishing, so a fresh checkout
  doesn't need a separate manual `vidctl registry login` first) and `tag`
  (optional; defaults to the current git short SHA). Scenario apply always
  builds+pushes every worker service image.
- `[[frontends]]` -- optional, zero or more: `name` (topology-unique
  identity/bucket-name component), `object` (defaults to `"frontend"`, the
  only object type today -- always `services/client/client`), `provider`
  (object-storage provider, e.g. `"alibaba"`). Published via
  `object_cmd.publish()` (which runs `pnpm build` itself) right after the
  contract step, since the build needs the contract IDs the publish step just
  wrote into `services/client/client/.env`. Never deleted by `apply` or
  `destroy` -- reuse the same `name`/`provider` across scenarios to update an
  existing site in place rather than creating a new one.
- `[[workers]]` -- one entry per VM-backed worker (a service daemon deployed
  onto a host): `host` (the VM/droplet it runs on -- multiple `[[workers]]`
  entries sharing the same `host` colocate several services on ONE VM). A
  `host` is a zero-padded, >=3-digit instance id counting from 1 (`"001"`,
  `"002"`, ...), unique across the WHOLE scenario file regardless of how
  many providers it spans -- not a real provider VM/droplet id, since that's
  only assigned by the provider after `pulumi up` and would churn on every
  redeploy (see `worker_identifier()` in `cli/infra/topology.py`). Combined
  with `provider`/`service`/`worker_index` it forms the worker's stable
  identity string (container name, public hostname, registry key):
  `<provider>-<host>-<service>-<worker_index>`, e.g. `digitalocean-001-relay-2`.
  A non-conforming `host` is rejected at `load_scenario()` time. See
  `multicloud.toml` for how a multi-provider scenario renumbers each source
  file's hosts into one continuous sequence.
  `service` (one of the worker services), `provider`, optional `size`
  (VM SKU override) and `worker_index` (defaults to `1`; only meaningful
  when running multiple replicas of the same service under one `host`).

Workers present in `runtime/topology.toml` but absent from the scenario
file are killed on `apply` (full declarative reconcile) -- this applies only
to `[[workers]]`, never to `[[frontends]]`.

## Samples

- `example.toml` -- minimal two-service DigitalOcean example.
- `digitalocean-sample.toml` -- one `s-4vcpu-8gb` DigitalOcean node running
  all 4 worker services colocated (1x signaling, 1x relay, 1x cp-daemon, 5x
  validator-daemon replicas), plus a DigitalOcean registry publish and an
  Alibaba OSS frontend update.
