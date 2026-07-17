PM REVIEW -- Phase 14: Integration & Hardening
Date: 2026-03-12
ADD reviewed: phase-14-ADD.md

VERDICT: APPROVED WITH NOTES

---

## REQUIREMENTS COVERAGE

  SIG-01 (signaling registration with stake): COVERED — already implemented in Phase 11 (signaling_registry.move). Phase 14 extends with cleanup (Task 2).
  SIG-02 (signaling heartbeat): COVERED — already implemented in Phase 11. No Phase 14 changes needed.
  SIG-03 (client discovers signaling from chain): COVERED — IC-2 get_room_assignment returns assigned signaling ID; Task 7 useRoomAssignment resolves it to endpoint.
  SIG-04 (client selects signaling by region/load scoring): COVERED — Task 5 CP daemon scoreSignalingNodes() applies region+load scoring; client receives the winning node via assignment.
  SIG-05 (signaling earns rewards): NOT DIRECTLY COVERED — the economic_layer::distribute_rewards distributes to relay and validators. Signaling node reward distribution is not part of any IC or task. See PM NOTES below.
  SIG-06 (signaling slashing for dropping connections): NOT COVERED — no slashing mechanism for signaling nodes is defined in any IC or task. This matches the CLAUDE.md Open Questions ("Signaling node slashing criteria" is Open). Acceptable to defer.
  RELAY-01 (client connects to SFU relay via mediasoup): COVERED — Task 7 wires assignment-based relay URL into useRelay.
  RELAY-02 (client connects to MCU relay via mediasoup): COVERED — same as RELAY-01; relay_mode is set at room creation and scored in Task 5.
  RELAY-03 (adaptive SFU/MCU session view): COVERED — relay_mode from chain drives client view (existing Phase 9/10 work + Task 7 integration).
  RELAY-04 (join room resolves relay from chain): COVERED — IC-1 assign_relay_and_signaling, IC-2 get_room_assignment, Task 5, Task 7.
  RELAY-05 (relay forwards media via mediasoup): COVERED — already implemented in Phase 12 relay daemon. Phase 14 adds metrics (Task 3).
  RELAY-06 (relay earns rewards based on bytes+quality): COVERED — IC-3 distribute_rewards, IC-5 metrics endpoint, Task 6 reward-trigger.
  ECON-01 (reward distribution via SessionProofs): COVERED — IC-3 distribute_rewards, IC-7 create_escrow, Tasks 6+7.
  ECON-02 (slashing returns Coin): COVERED — economic_layer.move slash logic already implemented Phase 13; Task 6 integrates the trigger.
  ECON-03 (validator dual-key signed SessionProofs): COVERED — already implemented Phase 13; Task 4 adds real measurements, Task 6 wires lifecycle.

---

## SOURCE OF TRUTH COMPLIANCE

  No floating point: COMPLIANT — ADD uses integer-only fields (bytesForwarded as bigint string, jitter in ms, loss in basis points). Scoring weights from NetworkRegistry are basis-point sums. No floating point anywhere.
  Cap constructors are public(package): COMPLIANT — IMP-1 confirms ControlPlaneCap constructor is public(package) in caps.move. The new assign_relay_and_signaling is public (not a constructor) gated by ControlPlaneCap reference. remove_if_registered is public(package). Correct.
  Paused flag always checked: COMPLIANT — IC-1 checks E_PAUSED (500) via NetworkRegistry. IC-3 checks E_PAUSED (650). IC-7 checks E_PAUSED (650). All state-mutating entry points check pause.
  Validator identity hidden during session: COMPLIANT — no new code exposes validator-to-session-wallet mapping during session. Dual-key proofs are post-session only.
  Stake lock enforced: COMPLIANT — no changes to stake lock logic. distribute_rewards already checks relay_stake lock state.
  Slash returns a Coin: COMPLIANT — economic_layer slash logic (Phase 13) returns Coin. No Phase 14 changes to this.
  RTT is validator-probed: COMPLIANT — Task 4 replaces simulated measurements with real STUN probing. IC-5 metrics endpoint provides validator-measured data. No self-reported RTT.
  Rewards are work-based: COMPLIANT — IC-3 distribute_rewards uses median bytes_transferred * quality_multiplier from SessionProofs. Not membership-based.
  Chain carries no media: COMPLIANT — media flows over WebSocket/WebRTC (relay). Chain carries only IDs, proofs, and assignments.

---

## INTEGRATION CONTRACTS

  IC-1 (assign_relay_and_signaling PTB): COMPLETE — full Move signature, PTB argument order, error cases, event emission all specified. One note: the function is public with ControlPlaneCap gating, which is correct for PTB callability.
  IC-2 (get_room_assignment devInspect): COMPLETE — BCS decoding documented (returnValues[0] and [1] separately), error cases listed.
  IC-3 (distribute_rewards PTB): COMPLETE — full signature, argument order, relay StakePosition discovery strategy, all error codes documented.
  IC-4 (unregister signature change): COMPLETE — before/after signatures, PTB argument order, affected callers listed, CC-004 notice drafted.
  IC-5 (relay metrics HTTP): COMPLETE — endpoint URL, response schema with field types, error responses, health check endpoint, default port all specified. bytesForwarded as string (bigint) is a good choice to avoid JSON precision loss.
  IC-6 (RoomAssigned event): COMPLETE — event fields, TypeScript interface, consumer list all specified.
  IC-7 (create_escrow PTB): COMPLETE — full signature, PTB construction steps, coin type specified (TOKEN not SUI), error humanization, event emission.
  IC-8 (collectMeasurements internal): COMPLETE — before/after signatures, backward compatibility noted, async migration documented.

---

## OPEN QUESTIONS

  "Relay failover mid-session -- reconnect flow" (Phase 14 scope): RESOLVED — Task 8 implements client-side reconnect with exponential backoff (1s, 2s, 4s, 3 retries). Diagram 2 documents the sequence. The ADD correctly limits this to client-side reconnect to the same relay; CP-driven relay reassignment to a different relay is not implemented. This is a reasonable thesis scope. The Open Questions table in CLAUDE.md should be updated to mark this as "Partially resolved: client reconnect in Phase 14; CP-driven reassignment deferred."

  "Minimum validators per room for median to be statistically valid" (v3): ACKNOWLEDGED — the ADD does not change the existing default (3 validators). The economic_layer already uses E_INSUFFICIENT_PROOFS with a minimum proof count. This is adequate for thesis.

  "Signaling node stake threshold and reward mechanism" (Open): NOT RESOLVED — the ADD does not address signaling rewards. See SIG-05 coverage gap below. This was already marked as "Open -- needs design before Phase 11" in CLAUDE.md. Phase 11 shipped without resolving it. This should be explicitly acknowledged as deferred post-thesis or given a minimal design.

  "Signaling node slashing criteria" (Open): NOT RESOLVED — same status. Explicitly deferred.

---

## ARCHITECT IMPROVEMENTS

  IMP-1 (ControlPlaneCap vs CpCap): ACCEPTED — verified in caps.move: the type is `ControlPlaneCap` (line 4), constructor is `new_cp_cap` (line 18, public(package)), accessor is `cp_cap_miner_id` (line 28). The proposal's `CpCap` was incorrect. Correction is necessary.

  IMP-2 (public with ControlPlaneCap gating): ACCEPTED — public(package) functions cannot be called from external PTBs. The function must be `public fun` with `&ControlPlaneCap` parameter for the CP daemon to call it via PTB. This follows the established pattern in control_plane_registry.move (register_cp, heartbeat). Correct.

  IMP-3 (assignment allows non-CLOSED, not just PENDING): ACCEPTED WITH NOTE — the check `status != CLOSED` is simpler and supports future failover reassignment. However, this diverges from the spec (Section 8, Step 3: "Room status: READY" after assignment, implying assignment only during PENDING). For thesis, this is acceptable since: (a) the CP daemon only assigns on RoomCreated events (when room IS PENDING), so the broader check is never exercised in practice; (b) it correctly prepares for failover. The spec divergence should be documented as intentional.

  IMP-4 (no on-chain cross-registry validation for assignment IDs): ACCEPTED — the ControlPlaneCap gate ensures only authorized CP nodes can call the function. The CP daemon scores against live registry data before submitting. Adding on-chain validation would require passing &RelayRegistry and &SignalingRegistry as additional shared object parameters, increasing gas cost and contention. Trust in the CP is already established by the cap.

  IMP-5 (registration_tests migration to setup_phase2): ACCEPTED — pragmatic. Migrating all tests to setup_phase2() avoids confusion about which helper to use. The cost is slightly more setup per test, but test clarity wins.

  IMP-6 (relay StakePosition discovery via getOwnedObjects): ACCEPTED — the query returns a small result set (1-3 positions per operator). The edge case of transferred StakePosition is correctly identified and handled (log error, skip distribution). For production, an on-chain miner_id-to-StakePosition mapping would be more robust. Acceptable tech debt for thesis.

  IMP-7 (FE BCS tuple decoding via separate returnValues): ACCEPTED — Move tuple returns serialize as separate entries in devInspect. This matches the existing pattern in the codebase (useRoomStatus). Correct.

---

## REVISION ITEMS

None blocking. The ADD is approved for implementation.

---

## PM NOTES

1. **SIG-05 gap (signaling rewards):** The economic_layer::distribute_rewards splits escrow among relay (70%), validators (15%), and CPs (15%) per the spec. Signaling nodes are NOT included in the reward split. The REQUIREMENTS.md lists SIG-05 as a v3 requirement, and the spec (Section 11) does not mention signaling in the token flow. This means SIG-05 is structurally unaddressable without a spec change to the reward ratios. For Phase 14 (integration of what exists), this is acceptable. SIG-05 should be explicitly marked as "deferred post-thesis" in REQUIREMENTS.md with a note that the reward split would need to change (e.g., relay 60%, signaling 10%, validators 15%, CPs 15%) to accommodate it.

2. **CP consensus simplification:** The ADD uses single-CP assignment (one ControlPlaneCap holder calls assign_relay_and_signaling). The spec (Sections 8 and 10) describes multi-CP voting with 2/3 consensus. This is documented in the Phase 14 CONTEXT as an intentional thesis simplification. The ADD should have called this out explicitly in its RESOLVED OPEN QUESTIONS section. Not a blocker.

3. **Task 1 PLAN description inconsistency:** The PLAN.md Task 1 description says `public(package) fun assign_relay_and_signaling` but the ADD (IC-1, IMP-2) correctly specifies `public fun` with ControlPlaneCap gating. The ADD is authoritative. OnChain agent must follow the ADD, not the PLAN description.

4. **CALLER AUDIT REQUIRED (IC-4 breaking change):**
   Function changed: registration::unregister -- added parameter: signaling_reg: &mut SignalingRegistry
   Callers to verify:
     - tests/miner/registration_tests.move -- all unregister call sites
     - dvconf-daemons (any daemon code building unregister PTBs)
   Status: [ ] confirmed all callers updated
   This is tracked as CC-004. OnChain and OffChain agents must both update.

5. **Open Questions table update needed:** After Phase 14 ships, update CLAUDE.md Open Questions:
   - "Relay failover mid-session" -> "Partially resolved: client reconnect in Phase 14; CP-driven reassignment deferred v3+"
   - "Signaling node stake threshold and reward mechanism" -> remains Open, explicitly deferred post-thesis
   - "Signaling node slashing criteria" -> remains Open, explicitly deferred post-thesis

6. **Shared object contention analysis:** The ADD includes a thorough contention analysis. All assessments are reasonable for thesis scale. The note about RoomManager potentially benefiting from per-room owned objects in production is good forward-looking tech debt documentation.

7. **Execution wave validation:** The ADD validates the PLAN's execution order against dependency constraints. All waves are correctly ordered. No issues.

---

PM SIGN-OFF: APPROVED for implementation.
QC review remains required before final phase completion per workflow rules.
Verification Agent RTM required after implementation to confirm all REQ-IDs are test-covered.
