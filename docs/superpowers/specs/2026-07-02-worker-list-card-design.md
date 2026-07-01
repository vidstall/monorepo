# Worker List Card Design

## Goal

Add a card to the frontend homepage, below "CONTRACT STATUS", listing every worker
registered in the on-chain `node_registry`, with its role and public URL.

## Data layer

`services/frontend/lib/route-discovery.ts` already implements the two-pass
devInspect query needed to enumerate registry nodes (`fetchNextNodeId` →
`fetchExistingWithRole` → a details pass). Generalize instead of duplicating:

- Rename `fetchRouterDetails` to `fetchWorkerRecords`; it returns the full,
  unfiltered set of `{ nodeId, role, active, endpoint, updatedAtMs }` for the
  given node IDs (no ROLE_ROUTER / active / staleness filtering).
- `fetchActiveRouters()` (used by `getWorkingRoute`, the live routing path)
  filters/maps from `fetchWorkerRecords`'s output exactly as it filters today —
  no behavior change to routing.
- New exported `fetchAllWorkers()` calls the same `fetchNextNodeId` →
  `fetchExistingWithRole` → `fetchWorkerRecords` pipeline and returns everything,
  mapped with a human-readable role label via the existing role constants
  (`ROLE_SFU = 0`, `ROLE_COORDINATOR = 1`, `ROLE_ROUTER = 2`, matching
  `services/contract/sources/node_registry.move`).
- Workers that exist but never called `propose_role` are excluded by the
  existing `has_worker_role` gate in `fetchExistingWithRole` — consistent with
  current behavior, not a new filter.

## UI card

New `WorkerListCard` component in `services/frontend/app/HomePage.tsx`, rendered
directly below `ContractStatusCard` in `styles.leftCol`, reusing `styles.card` /
`styles.cardLabel` / `styles.statusRow` / `styles.statusDot` conventions already
used by `ContractStatusCard`.

- Fetches once on mount via `fetchAllWorkers()` (no polling), same pattern as
  `ContractStatusCard`'s `useEffect` + `fetchRegistryStats()`.
- Loading: same skeleton-row treatment as `ContractStatusCard`.
- Each worker renders as a row: role label, status dot (green = active, dim =
  inactive), and the metadata URL truncated with the existing `truncateAddr`-style
  helper (full URL available via `title` attribute on hover).
- Empty state: "no workers registered yet" when the array is empty.
- Error state: inline error message, same styling as `ContractStatusCard`'s
  error row.
- No pagination; the card scrolls if the list overflows (devnet-scale worker
  counts expected).

## Assumptions

- No live refresh/polling needed — a page reload is sufficient to see new
  registrations, matching `ContractStatusCard`'s existing one-shot-fetch pattern.
- No new environment variables or contract changes required; all accessor
  functions (`worker_role`, `worker_active`, `worker_metadata_uri`,
  `worker_updated_at_ms`, `node_exists`, `has_worker_role`) already exist on
  the deployed contract.
