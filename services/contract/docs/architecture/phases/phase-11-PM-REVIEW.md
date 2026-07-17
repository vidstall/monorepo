PM REVIEW — Phase 11: Signaling Node Registry
Date: 2026-03-11
ADD reviewed: docs/architecture/phases/phase-11-ADD.md

---

REQUIREMENTS CHECK:
  SIG-01: COVERED — signaling_registry.move register_signaling() with stake check via StakePosition, role check via MinerCap (ROLE_SIGNALING=4), constants.move + staking.move + miner_store.move changes for role support
  SIG-02: COVERED — signaling_registry.move heartbeat() + heartbeat.ts 30s loop, emits SignalingHeartbeat event, updates last_heartbeat timestamp
  SIG-03: COVERED — useSignalingDiscovery.ts queries get_active_nodes() via devInspect, falls back to CONFIG.SIGNALING_URL if no nodes registered
  SIG-04: COVERED — useSignalingDiscovery.ts scoring: region_match_bonus + (1 / (load + 1)), selects highest-scoring node endpoint_url
  BUG-RR-01: COVERED — relay_registry.move update_load() gets operator ownership check (ctx.sender() == info.operator), error 524
  BUG-RR-02: COVERED — relay_registry.move update_mode() gets operator ownership check (ctx.sender() == info.operator), error 524

  All 6 requirements are covered. No gaps.

---

SOURCE OF TRUTH COMPLIANCE:

  No floating point:
    PASS — All values are integer (u64). Load is raw WebSocket connection count. Stake threshold is 250_000_000 raw units. Scoring formula uses integer-safe operations. No floating point in on-chain code.
    NOTE: The FE scoring formula "score = region_match_bonus + (1 / (load + 1))" will use JavaScript number division, which is floating point. This is acceptable because it runs entirely client-side (off-chain), not in Move. The on-chain module stores only raw u64 integers. No violation.

  Cap constructors package-private:
    PASS — signaling_registry.move does not mint any caps. It consumes existing MinerCap via &MinerCap (immutable borrow). The registry create() function is public but AdminCap-gated, consistent with control_plane_registry, relay_registry, validator_registry, room_manager, and user_registry. This is not a cap constructor -- it is a registry factory.

  Pause flag checked on state-mutating functions:
    WARNING — unregister_signaling() does NOT check pause flag. The ADD explicitly resolves this (Q3): "Allowing operators to exit even when the network is paused is the safer design." This is a deliberate, documented deviation from the literal CLAUDE.md rule. The rationale is sound (operators must always be able to withdraw from the system), and no other registry has an unregister function to set precedent.
    RECOMMENDATION: Add a comment in the Move source code explicitly documenting why unregister_signaling skips the pause check, so future QC reviews do not flag it as a bug. Example: `// NOTE: No pause check -- operators must always be able to exit (ADD Q3 resolution)`.
    All other state-mutating functions (register_signaling, heartbeat, update_load) correctly check pause. ACCEPTABLE.

  All math in basis points:
    PASS — No basis-point math introduced in this phase. Stake threshold is a raw token amount (u64), not a ratio. Load is a raw count. No weight sums or ratio sums introduced.

  Chain carries no media:
    PASS — SignalingRegistry stores only metadata (endpoint_url, region, load, timestamps, operator address, stake_amount). No video, audio, or SDP/ICE data touches the chain. The signaling node routes WebSocket messages entirely off-chain.

  Spec is canonical:
    PASS — The ADD cites the context document, proposals, and REQUIREMENTS.md. SIG-05 and SIG-06 are explicitly deferred to Phase 13, consistent with 11-CONTEXT.md phase boundary.

  Validator identity hidden during session:
    N/A — Phase 11 does not involve validator identity or session proofs.

  Stake lock enforced:
    NOTE — register_signaling takes &StakePosition (immutable borrow) for stake_amount verification but does NOT lock the stake. This is consistent with the CP and relay registry patterns where stake locking happens at session time, not registration time. No violation.

  Slash returns a Coin:
    N/A — No slashing in Phase 11 (deferred to Phase 13).

  RTT is validator-probed:
    N/A — No RTT measurement in Phase 11.

  Rewards are work-based:
    N/A — No rewards in Phase 11 (deferred to Phase 13).

---

INTEGRATION CONTRACTS:

  IC-1 (OnChain <-> OffChain auto-register): COMPLETE
    - Full moveCall target, argument list, and type annotations specified
    - Error codes mapped (600, 601, 603)
    - MinerCap role invariant documented
    - No ambiguity — daemon agent can implement from this contract alone

  IC-2 (OnChain <-> OffChain heartbeat): COMPLETE
    - Combined PTB pattern documented with both move calls
    - Error codes mapped (602, 603, 604)
    - PTB viability confirmed with rationale (IMP-3)
    - No ambiguity

  IC-3 (OnChain <-> FE discovery): COMPLETE
    - devInspect target and arguments specified
    - Return type documented (vector<SignalingNodeInfo>)
    - BCS field layout specified with exact types and byte sizes
    - Fallback behavior documented
    - get_active_nodes() accessor mandated by IMP-1
    - No ambiguity — FE agent can implement from this contract alone

  IC-4 (Events <-> shared types): COMPLETE
    - All 4 events mapped with Move fields and TypeScript equivalents
    - Sui JSON serialization rules documented (ID->hex string, u64->string, vector<u8>->number[])
    - No mismatches

  IC-5 (Error codes): COMPLETE
    - All 5 error codes (600-604) mapped across Move constants and TypeScript constants
    - Verified aligned per ADD

  All 5 integration contracts are complete and unambiguous. Domain agents can implement from these contracts alone without requiring cross-domain coordination.

---

OPEN QUESTIONS:

  OnChain Q1 (MinerStore struct migration): RESOLVED — re-publish for thesis, tech debt TD-P11-01
  OnChain Q2 (RoleThresholds struct migration): RESOLVED — re-publish for thesis, tech debt TD-P11-02
  OnChain Q3 (unregister pause check): RESOLVED — no pause check, documented rationale
  OnChain Q4 (signaling load unit): RESOLVED — raw WebSocket connection count as u64
  OnChain Q5 (update_load ownership): RESOLVED — dual check (MinerCap role + ctx.sender())

  OffChain Q1 (RoomManager export scope): RESOLVED — pass as parameter to startHeartbeat()
  OffChain Q2 (combined heartbeat+load TX): RESOLVED — viable, confirmed by PTB semantics
  OffChain Q3 (MINER_CAP_ID skip behavior): RESOLVED — lightweight verification + auto-Step-2
  OffChain Q4 (stake amount source): RESOLVED — hardcoded 250_000_000n
  OffChain Q5 (package.json dependency): RESOLVED — add @mysten/sui and dotenv

  FE Q1 (Table iteration from devInspect): RESOLVED — get_active_nodes() accessor (IMP-1)
  FE Q2 (region string format): RESOLVED — free-form strings with canonical vocabulary table
  FE Q3 (URL change during active session): RESOLVED — lock URL at connect() time (IMP-4)

  All 13 open questions are resolved. No items remain open.

---

SPEC GAP ANALYSIS:

  1. SignalingNodeInfo copy semantics: The get_active_nodes() function in IMP-1 dereferences table entries with `*table::borrow()`. This requires SignalingNodeInfo to have the `copy` ability. The ADD does not explicitly state the abilities on SignalingNodeInfo. The OnChain agent must ensure `SignalingNodeInfo has key, store, copy, drop` (or at minimum `copy`). Minor gap — the agent will infer this from the code, but it should be documented.

  2. miner_store.move signaling_miners integration: The ADD says "add signaling_miners VecSet and role_signaling() accessor" (IMP-2) but does not specify WHO calls add/remove on this VecSet. The registration module presumably handles this in register/unregister flows. The existing cp_miners/relay_miners/validator_miners VecSets are managed by registration.move. The OnChain agent should follow the same pattern. Minor gap — inferable from existing code.

  3. update_role_thresholds ordering invariant: Task 1 description in PLAN.md says `update_role_thresholds()` must enforce `cp >= relay >= validator >= signaling`. The ADD does not explicitly repeat this invariant in the function signatures section. The OnChain agent should enforce this ordering check. Minor gap — covered in PLAN.md but not in ADD.

  4. REQUIREMENTS.md traceability not updated: The REQUIREMENTS.md traceability table does not yet include SIG-01..04 or BUG-RR-01..02 phase mappings. This should be updated when Phase 11 tasks begin.

  None of these gaps block implementation. All are minor and inferable.

---

VERDICT: APPROVED

REASON: The ADD comprehensively covers all 6 requirements (SIG-01 through SIG-04, BUG-RR-01, BUG-RR-02), resolves all 13 open questions from the three domain proposals, provides 5 complete and unambiguous integration contracts, introduces no Source of Truth violations (the unregister pause-check deviation is explicitly justified and acceptable), and documents tech debt honestly. The design is a straightforward extension of established patterns (mirrors ControlPlaneRegistry, CP daemon, and useNetworkStats). The one critical addition (IMP-1: get_active_nodes accessor) was correctly identified and mandated. The architecture is ready for implementation.

---

NOTES FOR IMPLEMENTATION:

  1. OnChain Agent: SignalingNodeInfo MUST have `copy` ability for get_active_nodes() to compile. Verify this when defining the struct. The existing ControlPlaneNodeInfo has `store, copy, drop` — follow the same pattern.

  2. OnChain Agent: Add an inline comment on unregister_signaling explaining the intentional pause-check omission. QC will flag this otherwise. Suggested: `// No pause check: operators must always be able to exit (Phase 11 ADD Q3)`.

  3. OnChain Agent: update_role_thresholds() must enforce the ordering invariant `cp >= relay >= validator >= signaling` when the 4th parameter is added. Add an assert for this.

  4. OnChain Agent: The relay_registry bug fix (Task 4) is independent. It can proceed in parallel with Tasks 1-3. Use error code 524 (E_NOT_OPERATOR in relay namespace 520-529).

  5. OffChain Agent: The combined heartbeat+load PTB (IC-2) is confirmed viable. Build both move calls in a single Transaction object. Follow the CP daemon's heartbeat.ts structure.

  6. OffChain Agent: For the MINER_CAP_ID skip behavior (OffChain Q3), implement the lightweight devInspect check at startup to detect the crash-between-steps scenario. Log clearly so operators can diagnose registration state.

  7. FE Agent: The BCS decoding of vector<SignalingNodeInfo> from devInspect will require a BCS layout definition matching the field order in IC-3 (operator, miner_id, stake_amount, last_heartbeat, is_active, endpoint_url, region, load, registered_at). Test this carefully — field order matters.

  8. FE Agent: The scoring formula uses JavaScript floating point division (1 / (load + 1)). This is fine for client-side ranking. Do NOT attempt integer-only scoring on the client — it adds complexity with no benefit since this never touches the chain.

  9. All Agents: The REQUIREMENTS.md traceability table should be updated to map SIG-01..04 and BUG-RR-01..02 to Phase 11 when implementation begins.

  10. All Agents: Re-publish (not upgrade) is required on localnet/testnet due to struct layout changes (MinerStore + RoleThresholds). The deploy script (run-local.ps1) must call signaling_registry::create() and export the new SignalingRegistry object ID.
