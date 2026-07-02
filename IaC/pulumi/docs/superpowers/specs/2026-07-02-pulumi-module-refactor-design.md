# Pulumi Module Refactor Design

## Goal

Replace the 939-line Pulumi entrypoint with focused Python modules. Every Python
file in this Pulumi project must contain at most 200 lines, including tests and
the entrypoint.

## Compatibility Requirements

- Preserve all Pulumi logical resource names to prevent unintended replacements.
- Preserve the `cloudCredentials`, `topology`, `frontendSites`, and
  `ansibleInventory` stack exports and their existing shapes.
- Preserve environment-variable names, defaults, topology parsing, desired-state
  behavior, and provider-specific resource settings.
- Keep provider SDK imports local to adapters so unused providers are not loaded.
- Do not modify unrelated files or the existing contract worktree change.

## Package Structure

`__main__.py` becomes a minimal entrypoint that invokes `app.program.run()`.
The `app` package is organized by domain:

- `config.py`, `models.py`, and `topology.py` own paths, shared types, and topology
  loading.
- `common/environment.py` and `common/regions.py` own environment validation and
  provider location defaults.
- `frontend/artifacts.py` owns artifact discovery, object keys, MIME types, and
  uploads.
- `frontend/service.py` selects the object-storage adapter and produces frontend
  metadata. Individual provider modules create cloud resources.
- `compute/service.py` selects VM adapters. `compute/ssh.py` reads public keys,
  while individual provider modules create compute and network resources.
- `inventory.py` builds the Ansible inventory from static and provisioned hosts.
- `program.py` composes topology loading, resource creation, inventory generation,
  credential reporting, and Pulumi exports.

Alibaba compute may use more than one focused helper module if necessary to keep
each file below 200 lines without compressing readable code.

## Data Flow

`program.run()` loads configuration and topology, passes instances to the
frontend and compute dispatchers, gives compute outputs to the inventory builder,
then exports the four existing stack values. Modules receive topology or instance
data explicitly rather than reading mutable globals.

## Error Handling

Existing errors remain explicit: missing required credentials, missing SSH key
configuration, unavailable Alibaba spot capacity, unsupported Tencent compute,
and unknown VM providers continue to raise `ValueError`. Missing topology and
frontend artifact directories retain their current fallback behavior.

## Verification

- Compile all project Python modules.
- Run focused unit tests for pure topology, artifact, region, and inventory logic
  where practical without cloud credentials.
- Check that every Python file has no more than 200 lines.
- Inspect the final diff to confirm resource names and export names are unchanged.
