# Current Route Card Design

## Goal

Add a card to the frontend homepage showing which router the frontend would
currently select for routing traffic, always reflecting genuine on-chain
latency-based selection (not the local dev `NEXT_PUBLIC_ROUTES_URL` override).

## Data layer

`services/frontend/lib/route-discovery.ts`:

- Widen `pickBestRoute`'s return type from `RouteCandidate | null` to
  `{ candidate: RouteCandidate; latencyMs: number } | null` so the measured
  latency is available to callers instead of being discarded. `getWorkingRoute`
  (the real room-joining path) is updated to read `.candidate.endpoint` from
  this — no behavior change to actual routing.
- New exported `selectOnChainRoute(): Promise<{ nodeId, endpoint, latencyMs } | null>`
  that calls `cachedCandidates()` → `pickBestRoute()` directly, skipping
  `devFallbackEndpoint()` entirely, so it always reflects genuine on-chain
  selection regardless of `NEXT_PUBLIC_ROUTES_URL`. Returns `null` when no
  registered router is currently reachable.

## UI card

New `CurrentRouteCard` component in `services/frontend/app/HomePage.tsx`,
placed in `styles.leftCol` between `ContractStatusCard` and `WorkerListCard`.
Same `styles.card` conventions, fetch-once-on-mount pattern matching the other
two cards (skeleton while loading, inline error on failure).

- Shows: node id, endpoint URL, measured latency in ms.
- Empty state: "no reachable router right now" when `selectOnChainRoute()`
  returns `null`.

## Assumptions

- No polling; a page reload re-selects, consistent with the other two cards.
- This card's selection is for visibility only and is independent of whichever
  route the room-joining flow (`PageClientImpl.tsx`) actually picks at join
  time (which still respects the dev override and its own exclusion-set retry
  logic) — the two can differ, and that's expected.
