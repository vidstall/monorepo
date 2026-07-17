# Phase 11: Signaling Node Registry - Context

**Gathered:** 2026-03-11
**Status:** Ready for planning

## Phase Boundary

Phase 11 covers on-chain SignalingRegistry (register, heartbeat, load), upgrading the signaling daemon to be chain-aware, and client-side signaling discovery from the chain. Rewards (SIG-05) and slashing (SIG-06) are **deferred to Phase 13** (Economic Layer) since they depend on infrastructure that doesn't exist yet. This phase also includes fixing critical relay_registry ownership bugs found in code review.

**In scope:** SIG-01, SIG-02, SIG-03, SIG-04 + relay_registry bug fixes
**Out of scope:** SIG-05 (rewards), SIG-06 (slashing) — deferred to Phase 13

## Implementation Decisions

### Stake Threshold
- Signaling node stake: **0.25 DVCONF** (250_000_000 raw units at 9 decimals) — lowest tier, reflecting lightweight work (text routing only, no media)
- New role hierarchy: User (free) < Signaling (0.25) < Validator (0.5) < Relay (1.5) < CP (2.0)

### On-Chain Module
- New module: `sources/registry/signaling_registry.move`
- Mirror `control_plane_registry.move` pattern exactly: register, heartbeat, load update, events
- Error code namespace: **600-609** (next unassigned range per AGENT_ROUTING.md)
- Struct: `SignalingNodeInfo { operator, miner_id, stake_amount, last_heartbeat, is_active, endpoint_url, region, load, registered_at }`
- AdminCap-gated `create()` function (follows all registry patterns)
- Pause enforcement on all state-mutating functions
- Events: `SignalingRegistered`, `SignalingHeartbeat`, `SignalingLoadUpdated`, `SignalingUnregistered`

### Signaling Role
- Signaling nodes use `MinerCap` (not a new cap type) — reuse existing cap system
- Need new role constant in `constants.move`: `ROLE_SIGNALING = 4`
- `registration.move` needs threshold for signaling role (0.25 DVCONF)
- Signaling role is auto-determined by stake amount like other roles

### Off-Chain Daemon Upgrade
- Upgrade `@dvconf/signaling` from stateless → chain-aware
- Add: auto-register with stake, periodic heartbeat TX, report active connection count as load
- Reuse `@dvconf/shared` utilities (SuiClient, executeWithRetry, EventPoller, keypair)
- Follow `cp-daemon` auto-register pattern (two-step: miner registration then signaling registration)

### Client Discovery
- New hook: `useSignalingDiscovery` in dvconf-client
- Query SignalingRegistry via devInspect (same pattern as useNetworkStats)
- Score nodes by: region_match bonus + (1/load) — simplified scoring
- Fallback to `VITE_SIGNALING_URL` env var if no signaling nodes registered (bootstrap)
- Replace hardcoded signaling URL in `useSignaling.ts` with dynamic discovery result

### Bug Fixes (relay_registry)
- Fix `update_load()`: add ownership check — verify `ctx.sender() == info.operator`
- Fix `update_mode()`: add ownership check — verify `ctx.sender() == info.operator`
- Add tests for both fixes

### Claude's Discretion
- Exact event field naming
- Test structure and coverage level
- Internal helper function organization
- Whether to add `endpoint_url` as vector<u8> or separate ip/port fields for signaling

## Specific Ideas

- `signaling_registry.move` follows `control_plane_registry.move` line-for-line (create, register, heartbeat, unregister, events, accessors)
- Add `signaling_count()` and `signaling_set()` accessors for cp_queries
- Signaling nodes don't need `mode` (SFU/MCU) — they only route text messages
- Heartbeat interval reuses existing 30s pattern from CP daemon
- Load = active WebSocket connection count (already tracked in signaling `rooms.ts`)
- `useSignalingDiscovery` returns `{ url: string, isFromChain: boolean }` — client knows if it fell back

## Existing Code Insights

### Reusable Assets
- `control_plane_registry.move` — exact registration + heartbeat pattern to copy
- `relay_registry.move` — load tracking pattern
- `@dvconf/shared` — SuiClient, executeWithRetry, EventPoller, keypair utils
- `cp-daemon/auto-register.ts` — two-step registration pattern
- `cp-daemon/heartbeat.ts` — heartbeat TX loop pattern
- `client/src/hooks/useNetworkStats.ts` — devInspect query pattern

### Established Patterns
- Error codes in 10-code namespaces (600-609 for signaling)
- `public(package)` constructors for all internal types
- Pause check on every state-mutating function
- Events emitted for all state changes
- All math in basis points

### Integration Points
- `constants.move` — add ROLE_SIGNALING = 4, DEFAULT_SIGNALING_THRESHOLD
- `registration.move` — add signaling role threshold to role determination logic
- `network_registry.move` — add signaling threshold to update_role_thresholds()
- `cp_queries.move` — optionally add signaling accessors
- `@dvconf/shared/types/constants.ts` — add MinerRole.Signaling
- `@dvconf/shared/types/events.ts` — add signaling event types
- `dvconf-client/src/config.ts` — add VITE_SIGNALING_REGISTRY_ID
- `dvconf-client/src/hooks/useSignaling.ts` — replace hardcoded URL with discovery result

## Deferred Ideas

- **SIG-05 (rewards):** Signaling node earns rewards for routing — deferred to Phase 13 (Economic Layer)
- **SIG-06 (slashing):** Signaling node slashed for misbehavior — deferred to Phase 13 (Economic Layer)
- **Signaling node health monitoring:** CP monitors signaling node health — deferred to Phase 14 (Integration)
- **Cap aliasing bug (role upgrade):** Old MinerCap not revoked on role upgrade — noted but not in scope for this phase

## Revision Log

- **2026-03-11 (initial):** Context gathered via /dvconf:discuss-phase. Scoped to SIG-01..04 + relay bug fixes. SIG-05/06 deferred to Phase 13. Stake threshold set to 0.25 DVCONF.
