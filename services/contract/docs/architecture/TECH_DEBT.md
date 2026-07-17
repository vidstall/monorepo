# Tech Debt Registry — DVConf

> Maintained by: Architect Agent
> Last updated: 2026-03-16 (Phase 16)

---

## Active Tech Debt

| ID | Severity | Module | Description | Phase Introduced | Remediation Phase |
|----|----------|--------|-------------|------------------|-------------------|
| TD-001 | MEDIUM | cp-daemon | Scoring weights hardcoded, don't match on-chain constants (rtt=2500, stake=1500) | Phase 3 | Phase 6 |
| TD-002 | LOW | cp-daemon/validator-daemon | `.env.example` key names don't match what daemons read | Phase 3 | Phase 6 |
| TD-003 | MEDIUM | cp-daemon/validator-daemon | TX effects parsing uses fragile `createdObjects[0]?.reference?.objectId` | Phase 3 | Phase 6 |
| TD-004 | LOW | cp-daemon | Hardcoded `roomId: 'pending-room'` placeholder | Phase 3 | Phase 6 |
| TD-005 | HIGH | cp-daemon/validator-daemon | Auto-registration TX argument type/order mismatches | Phase 3 | Phase 4 |
| TD-P11-01 | MEDIUM | miner_store.move | MinerStore struct change (signaling_miners field) requires re-publish, not upgrade | Phase 11 | Production |
| TD-P11-02 | MEDIUM | network_registry.move | RoleThresholds struct change (signaling_threshold field) requires re-publish | Phase 11 | Production |
| TD-P11-03 | LOW | auto-register.ts | Hardcoded stake threshold (250M) -- should query on-chain threshold at runtime for production | Phase 11 | Production |
| TD-P11-04 | LOW | signaling_registry.move | No cross-registry cleanup on registration::unregister() -- SignalingRegistry entry becomes stale | Phase 11 | RESOLVED (Phase 14) |
| TD-P11-05 | LOW | signaling_registry.move | Region strings are free-form with no on-chain validation | Phase 11 | Production |
| TD-P13-01 | LOW | economic_layer.move | u64 overflow risk in reward calc (base_rate * median_bytes * qm) -- documented, safe within thesis bounds | Phase 13 | Production |
| TD-P13-02 | LOW | economic_layer_tests.move | Missing test for E_ROOM_NOT_FOUND (652) in create_escrow | Phase 13 | RESOLVED (Phase 14) |
| TD-P13-03 | LOW | economic_layer_tests.move | Missing test for E_PAUSED (650) on entry functions | Phase 13 | RESOLVED (Phase 14) |
| TD-P14-01 | CRITICAL | reward-trigger.ts | distribute_rewards PTB passes 4 args in wrong order; on-chain requires 6 shared objects + ctx | Phase 14 | RESOLVED (Phase 14) |
| TD-P14-02 | CRITICAL | load-test.ts | create_room PTB missing UserRegistry shared object argument | Phase 14 | RESOLVED (Phase 14) |
| TD-P15-01 | LOW | validator-daemon/index.ts | Dual escrow tracking: `escrowMap` duplicates `activeRooms[].escrowId` -- risk of desync | Phase 15 | Post-thesis |
| TD-P16-01 | LOW | registration.move | Fan-out to 8 imports; any registry interface change now requires a registration.move edit | Phase 16 | Post-thesis |
| TD-P16-02 | LOW | relay/validator/cp registries | `remove_if_registered` emits no event; inconsistent with signaling baseline (daemons have blind spot on relay/validator/CP forced exits) | Phase 16 | Post-thesis |
| TD-P16-03 | MEDIUM | validator_registry.move | `remove_if_registered` does not clean up `session_wallets` table; stale entries can cause E_SESSION_EXISTS (534) on session wallet reuse and allow `has_session_wallet` to return true for a removed validator | Phase 16 | Production |
| TD-P16-04 | LOW | control_plane_registry.move | `remove_if_registered` does not clean up `room_assignments` table; stale CP-to-room entries persist after forced unregister | Phase 16 | Post-thesis |

## Resolved Tech Debt

| ID | Severity | Module | Description | Phase Introduced | Resolved Phase |
|----|----------|--------|-------------|------------------|----------------|
| TD-P11-04 | LOW | signaling_registry.move | No cross-registry cleanup on registration::unregister() -- SignalingRegistry entry becomes stale | Phase 11 | Phase 14 |
| TD-P13-02 | LOW | economic_layer_tests.move | Missing test for E_ROOM_NOT_FOUND (652) in create_escrow | Phase 13 | Phase 14 |
| TD-P13-03 | LOW | economic_layer_tests.move | Missing test for E_PAUSED (650) on entry functions | Phase 13 | Phase 14 |
| TD-P14-01 | CRITICAL | reward-trigger.ts | distribute_rewards PTB argument mismatch (found and fixed during verification) | Phase 14 | Phase 14 |
| TD-P14-02 | CRITICAL | load-test.ts | create_room PTB missing UserRegistry (found and fixed during verification) | Phase 14 | Phase 14 |

---

## How to Add Entries

The Architect Agent adds entries during post-implementation verification.
Domain agents may also flag items by writing `// TECH-DEBT: <description>` in code.
Each entry needs: ID, severity (LOW/MEDIUM/HIGH/CRITICAL), module, description, and target remediation phase.
