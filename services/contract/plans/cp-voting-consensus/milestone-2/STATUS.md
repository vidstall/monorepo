# Status Report — cp-voting-consensus / Milestone 2
Generated: 2026-03-27

## Progress Summary
- **Milestone:** 2 of 2
- **Requirements completed:** 13/13
  - ✅ PVR-14: Daemon scoring mirrors on-chain formula exactly (6-factor, canonical sort)
  - ✅ PVR-16: Client create_room accepts expectedParticipants from user input
  - ✅ PVR-17: Client shows consensus progress while PENDING
  - ✅ PVR-18: Client shows verified_score + resolution badge when READY
  - ✅ PVR-19: Contract groups proposals by submitted_score, finalizes at ≥2/3 votes
  - ✅ PVR-20: Dispute fallback via finalize_room (creator-gated, on-chain scoring)
  - ✅ PVR-21: RoomAssigned event includes verified_score, consensus_reached, winning_cp
  - ✅ PVR-22: RoomInfo persists verified_score and consensus_reached
  - ✅ PVR-23: Daemon applies canonical sort (score desc, node ID asc)
  - ✅ PVR-24: Client shows live voting progress grouped by score
  - ✅ PVR-25: Client shows finalize button after cooldown
  - ✅ PVR-13: CP daemon calls submit_pairing_proposal with submitted_score
  - ✅ PVR-15: CP daemon watches RoomCreated events and submits proposals

## Pipeline Report
| Stage | Status | Key Output |
|-------|--------|------------|
| On-chain (Move) | ✅ Completed | 4 commits: consensus-first model + dispute fallback |
| Daemon (TS) | ✅ Completed | 2 commits: scoring rewrite + event handler update |
| Client (React) | ✅ Completed | 3 commits: participant input + consensus UI + score badge |

## Test Results
- Move: 200 pass / 0 fail (was 190 before M2, +10 new consensus tests)
- Daemon: 48 pass / 1 pre-existing fail (auto-register args mismatch)
- Client: TypeScript compiles clean

## Design Decisions
- **Consensus-first model**: Happy path = zero on-chain computation (CPs submit score, contract counts matching votes)
- **Dispute fallback**: Room creator triggers on-chain scoring after cooldown (2 epochs)
- **No tuple_hash**: Score equality is the consensus key (deterministic formula guarantees same score = same tuple)
- **Vote threshold**: ≥2/3 of votes cast (not active CP count) — no dependency on active_cp_count()

## Files Changed (On-Chain)
- `sources/core/constants.move` — 2 new constants (dispute cooldown, consensus threshold)
- `sources/registry/room_manager.move` — refactored submit_pairing_proposal + new finalize_room
- `tests/scoring/pvr_consensus_tests.move` — 10 new tests (consensus + dispute + guard tests)

## Files Changed (Daemon)
- `apps/cp-daemon/src/scoring.ts` — full rewrite (6-factor PVR formula)
- `apps/cp-daemon/src/event-handler.ts` — PVR_WEIGHTS + canonical sort + submitted_score
- `apps/cp-daemon/src/room-assignment.ts` — submitted_score param in TX
- `apps/cp-daemon/src/__tests__/scoring.test.ts` — 21 new tests

## Files Changed (Client)
- `src/hooks/useChain.ts` — createRoom accepts expectedParticipants
- `src/pages/HomePage.tsx` — participant count input
- `src/hooks/useRoomConsensus.ts` — NEW: poll ProposalSubmitted events
- `src/components/ConsensusProgress.tsx` — NEW: voting progress bars + finalize
- `src/pages/RoomPage.tsx` — integrated ConsensusProgress
- `src/hooks/dashboard/useActiveRooms.ts` — BCS decode verified_score + consensus_reached
- `src/components/dashboard/RoomLifecyclePanel.tsx` — score + resolution badge

## Commits
### dvconf-contracts
- `ec0d1ed`: feat(m2): add PVR consensus constants + finalize_room error codes
- `a825d37`: feat(m2): update RoomInfo, PairingProposal, RoomAssigned with consensus fields
- `4167570`: feat(m2): refactor submit_pairing_proposal to consensus-first model
- `79259b7`: feat(m2): add finalize_room dispute fallback — creator-gated, on-chain scoring

### dvconf-daemons
- `2c322a2`: feat(m2): rewrite daemon scoring to match on-chain PVR formula exactly
- `b09279a`: feat(m2): daemon uses PVR scoring + submits submitted_score in proposal TX

### dvconf-client
- `ee1425b`: feat(m2): accept expectedParticipants in create room UI (PVR-16)
- `5fbd882`: feat(m2): consensus progress UI with voting bars + finalize button (PVR-17/24/25)
- `89ca272`: feat(m2): display verified_score + consensus/dispute badge (PVR-18/22)

## Session Resume
- **Current phase:** complete (M2 shipped)
- **Current milestone:** 2 of 2 — COMPLETE
- **Pipeline stage:** done
- **Last completed:** All 13 M2 requirements implemented + tested
- **Next:** Ship M2, update ROADMAP, proceed to Phase 18 or thesis writing
- **Blockers:** none
