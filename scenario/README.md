# Scenarios

A scenario file declares a full compute topology: which network/env to publish
the contract on, which Docker images to publish, and which VM instances should
be running. `vidctl scenario apply <path> --yes` applies one scenario file as
the complete source of truth for compute instances (`[[instances]]` only --
frontend/object-storage entries are never touched by the scenario subsystem).

```bash
./vidctl scenario apply scenario/example.toml --yes
./vidctl scenario status
./vidctl scenario destroy
```

Only one scenario can be active at a time. While a scenario is active, manual
`vidctl infra ...` commands and `vidctl scenario apply` of a *different* file
are refused -- run `vidctl scenario destroy` first, or re-apply the same file
to reconcile drift.

## Fields

- `name` -- human-readable label (used in status/log output).
- `env` -- `devnet` | `testnet` | `mainnet`. Scenario-wide; every instance in
  the file is provisioned against this one Sui/Pulumi environment.
- `[contract]` -- passed through to `contract.publish()`: `gas_budget`,
  `create_registry_if_missing`, `force`. Publish is always confirmed
  (`--yes`) internally once you've confirmed `scenario apply` itself.
- `[registry]` -- `tag` (optional; defaults to the current git short SHA).
  Scenario apply always builds+pushes every worker service image.
- `[[instances]]` -- one entry per VM-backed service instance: `name`,
  `service` (one of the worker services), `provider`, optional `size`
  (VM SKU override) and `instance_index` (defaults to `1`; only meaningful
  when running multiple replicas of the same service under one `name`).

Instances present in `runtime/topology.toml` but absent from the scenario
file are killed on `apply` (full declarative reconcile).
