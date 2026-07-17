PM REVIEW — Phase 7: Client Stabilization
Date: 2026-03-09
ADD reviewed: docs/architecture/phases/phase-7-ADD.md

---

REQUIREMENTS COVERAGE:

  FIX-01: Covered by App.tsx localStreamRef change (useRef instead of plain object) — YES
          ADD references this in Module Boundaries (App.tsx) and Integration Contracts.
          PLAN Task 2 maps directly.

  FIX-02: Covered by useSignaling.ts connect() returning Promise<void> — YES
          ADD specifies the contract change (connect: () => Promise<void>) and the
          invariant (joinRoom MUST only be called after connect() resolves).
          PLAN Task 3 maps directly.

  FIX-03: Covered by useChain.ts throwing on missing RoomCreated event — YES
          ADD specifies internal change (throw instead of digest fallback), roomError
          state in App.tsx, and the RoomControls Props interface with roomError prop.
          PLAN Task 4 maps directly.

  FIX-04: Covered by useWebRTC.ts Map-based peer tracking + cleanupPeer — YES
          ADD specifies peerConnections Map, pendingCandidates Map, cleanupPeer function,
          and the corrected onPeerLeft callback in App.tsx.
          PLAN Task 5 maps directly.

  FIX-05: Covered by useWebRTC.ts mediaError state + clearMediaError — YES
          ADD specifies mediaError and clearMediaError in the useWebRTC return type,
          and the inline banner pattern in App.tsx.
          PLAN Task 2 maps directly (combined with FIX-01).

  FIX-06: Covered by config.ts reading VITE_ env vars + AppConfig type — YES
          ADD specifies the full AppConfig interface, CONFIG singleton, validateConfig(),
          .env file layout, and the SUI_NETWORK union type.
          PLAN Task 1 maps directly.

  VERDICT: All 6 requirements are fully covered. No gaps in traceability.

---

SOURCE OF TRUTH COMPLIANCE: PASS

  Checked each Source of Truth rule from CLAUDE.md against the ADD:

  - No floating point: N/A (FE-only, no math)
  - Cap constructors package-private: N/A (no Move code)
  - Paused flag: N/A (no Move code)
  - Validator identity: N/A (no Move code)
  - Stake lock: N/A (no Move code)
  - Slash returns Coin: N/A (no Move code)
  - RTT validator-probed: N/A (no Move code)
  - Rewards work-based: N/A (no Move code)
  - Chain carries no media: PASS — no media data touches the chain. WebRTC streams are
    browser-only; signaling is WebSocket-only; chain interactions are limited to
    registerUser and createRoom transactions.
  - Spec is canonical: PASS — the ADD does not contradict the spec. The changes are
    client-side bug fixes consistent with the spec's architecture.

  No violations found. Phase 7 is entirely FE-scoped, so most on-chain rules do not apply.

---

INTEGRATION CONTRACTS: COMPLETE

  Every hook-to-component boundary is fully specified with TypeScript signatures:

  1. App.tsx <-> useWebRTC: Full return type specified (12 members). Invariant on
     fromPeerId threading documented. cleanupPeer vs cleanup semantics clear.

  2. App.tsx <-> useSignaling: Full return type specified (8 members). connect() change
     from void to Promise<void> explicitly called out. SignalingCallbacks interface
     documented as UNCHANGED (the bug was in App.tsx lambda wrappers, not the interface).

  3. App.tsx <-> useChain: Full return type specified (3 members). createRoom return type
     UNCHANGED. Internal throw-on-missing-event documented. handleCreateRoom wrapper
     pattern with roomError clear-on-next-action documented.

  4. App.tsx <-> RoomControls: Full Props interface specified (6 members). roomError
     prop is NEW and marked as such. Clear ownership: RoomControls renders the error,
     App.tsx clears it.

  5. App.tsx <-> VideoGrid: Props UNCHANGED (2 members). remoteStream null behavior on
     peer-left documented.

  6. config.ts <-> consumers: CONFIG shape UNCHANGED. SUI_NETWORK type widened to union.
     Validation-at-import-time invariant documented.

  7. Appendix provides canonical type signatures as a quick reference — matches the
     contracts section exactly.

  A developer could implement from this ADD alone without ambiguity. COMPLETE.

---

USER DECISIONS RESPECTED: YES

  Checked each decision from 07-CONTEXT.md:

  1. Error Display Style — "Inline banners, not toasts or modals"
     ADD: Uses inline red banners for mediaError, roomError, and connectionError. No
     toast library. Banners stay until next action (clear-on-next-action). Camera errors
     include Retry button. Room errors use the normal Create Room button.
     MATCH.

  2. Environment Variable Configuration — "VITE_ env vars with mode-based .env files"
     ADD: Uses VITE_PACKAGE_ID, VITE_NETWORK_REGISTRY_ID, etc. Files in apps/client/.
     Validation at import time. .env.example shipped.
     MINOR DISCREPANCY: CONTEXT says ".env.local for localnet, .env.testnet for testnet"
     but the ADD's IMP-3 changed this to ".env for localnet (committed), .env.testnet for
     testnet (gitignored)". This is a deliberate Architect improvement (IMP-3) that
     supersedes the original CONTEXT naming. The Architect's rationale is sound: committing
     .env with defaults enables clone-and-run, and .env.local becomes the personal override
     (Vite built-in behavior). The PLAN.md Risk #3 also flagged this naming conflict.
     ACCEPTABLE — the Architect resolved the PLAN's open risk correctly.

  3. Peer Disconnect Feedback — "Remove video immediately, no transition"
     ADD: cleanupPeer sets remoteStream to null, which removes the video tile instantly.
     No overlay or message.
     MATCH.

  4. Video Grid Scope — "Keep 1-local + 1-remote for Phase 7"
     ADD: VideoGrid Props UNCHANGED (localStream + remoteStream, not an array). Multi-peer
     tiled layout deferred to Phase 9.
     MATCH.

---

ARCHITECT IMPROVEMENTS:

  [IMP-1] connectionError state for handleJoin — ACCEPT

    Reason: The FE proposal left this as an open question. The Architect's resolution is
    correct: mediaError and connectionError have different causes, different recovery
    actions, and should not be conflated. The implementation is minimal (3 lines of state +
    try/catch + banner). The lastRoomIdRef pattern for the Retry button is a clean solution
    to the roomId scoping problem. Cost is small and risk is near-zero.

    One minor note: The CONTEXT.md decision says "Room creation errors show the error
    message only — user retries via the normal Create Room button." The connectionError
    Retry button is for WebSocket failures, not room creation, so it does not conflict with
    this decision. The Retry button for connectionError is appropriate because the user
    needs a way to re-attempt the join flow after a network failure.

  [IMP-2] cleanupPeer sets remoteStream to null internally — ACCEPT

    Reason: This is a correctness fix, not an improvement. The FE proposal's App.tsx
    snippet was impossible (setRemoteStream is not exported from the hook). The Architect
    caught this and corrected it. Option (a) is the right choice: the hook owns its own
    state, and Map.size === 0 is the correct trigger for nulling remoteStream in the 1+1
    model. The Phase 9 caveat is properly noted.

    Cost is zero — this is a clarification, not new work.

  [IMP-3] .env committed as development defaults — ACCEPT

    Reason: Committing .env with localnet defaults is the right call for a thesis project.
    The clone-and-run experience matters for the thesis examiner. The Vite .env loading
    order is correctly documented. The .env.local override path for personal customization
    is standard Vite convention.

    The Architect correctly identified the risk (monorepo .gitignore scope) and escalated
    it as ESC-1. See escalation decision below.

    This resolves PLAN.md Risk #3 (Vite mode file naming conflict) — the original
    ".env.local for localnet" naming would have collided with Vite's built-in .env.local
    behavior. The Architect's ".env for localnet + .env.local for overrides" avoids this.

---

ESCALATION DECISIONS:

  [ESC-1] Monorepo .gitignore scope — DECISION: APPROVE the Architect's recommended safe path.

    The Architect recommends app-specific .gitignore at apps/client/.gitignore rather than
    modifying the monorepo-level dvconf-daemons/.gitignore. This is the correct decision
    for three reasons:

    1. Isolation: Other apps in dvconf-daemons (signaling server, future daemons) may use
       .env for secrets. Removing the blanket .env ignore from the monorepo .gitignore
       would risk accidentally committing those secrets.

    2. Minimal blast radius: An app-specific .gitignore only affects apps/client/. No other
       team member or app is impacted.

    3. Force-add is a one-time operation: `git add -f apps/client/.env` is needed once.
       After that, git tracks the file normally despite the monorepo .gitignore.

    Implementation directive for the FE Agent:
    - Create `apps/client/.gitignore` containing:
        .env.local
        .env.testnet
        .env.*.local
    - Do NOT modify the monorepo-level .gitignore.
    - Force-add apps/client/.env with `git add -f apps/client/.env`.
    - Document the force-add in the .env.example file header comment.

---

SPEC GAPS: TWO MINOR ITEMS

  [GAP-1] PLAN.md vs ADD .env file naming mismatch — needs PLAN.md update

    The PLAN.md Task 1 still references creating `.env.local` for localnet defaults
    (lines 29-30: "Create .env.local with current localnet IDs"). The ADD's IMP-3 changed
    this to `.env` (committed). The PLAN.md must be updated before execution to avoid
    confusion:
    - Task 1 should say: "Create .env with current localnet IDs (committed)"
    - Task 1 should remove the ".env.local" creation step
    - Task 1 should update the .gitignore instruction to match ESC-1 decision

    Severity: LOW — would cause confusion but not a wrong implementation if the developer
    reads the ADD (which is the implementation spec). Still, the PLAN should not contradict
    the ADD.

  [GAP-2] connectionError Retry button roomId access — minor implementation detail

    The ADD's IMP-1 specifies storing the roomId in lastRoomIdRef. However, the
    connectionError banner is rendered in App.tsx, and the Retry button calls
    handleJoin(lastRoomIdRef.current). This is fully specified in the ADD but the
    RoomControls Props interface does not include connectionError — meaning the
    connectionError banner is rendered directly in App.tsx (above VideoGrid), not in
    RoomControls.

    This is actually correct per the CONTEXT.md decision ("above video area for camera
    errors"). Connection errors and camera errors both display above VideoGrid, while room
    errors display above room controls (in RoomControls). The ADD is internally consistent
    here. No gap — noting this for clarity during implementation.

    Severity: NONE — this is consistent. Removing from gap list.

  Revised gap count: 1 (GAP-1 only).

---

CALLER AUDIT REQUIRED:

  Function changed: useSignaling.connect() — return type changed from void to Promise<void>
  Callers to verify:
    - apps/client/src/App.tsx — handleJoin function (primary caller)
    - Any other file importing connect from useSignaling
  Status: [ ] confirmed all callers updated

  Function changed: useWebRTC — new cleanupPeer(peerId) function added
  Callers to verify:
    - apps/client/src/App.tsx — onPeerLeft callback
  Status: [ ] confirmed all callers updated

  Function changed: RoomControls Props — new roomError prop added
  Callers to verify:
    - apps/client/src/App.tsx — <RoomControls ... /> JSX
  Status: [ ] confirmed all callers updated

  Note: These are FE-only changes with a small call graph. Risk of missed callers is low
  but the audit must still be performed during QC review.

---

VERDICT: APPROVED

  The Architecture Design Document for Phase 7 is thorough, well-structured, and ready
  for implementation. All 6 FIX-* requirements are fully covered with unambiguous
  integration contracts. The Architect's 3 improvements are sound and add no unnecessary
  complexity. User decisions are respected. Source of Truth rules are not violated.

  Before execution begins:
  1. Update PLAN.md Task 1 to align .env file naming with ADD IMP-3 decision (GAP-1).
  2. Apply ESC-1 decision: app-specific .gitignore, not monorepo .gitignore modification.

  These are minor alignment items, not blocking issues. The ADD itself is the
  implementation authority and is correct as written.

---
*PM Review completed: 2026-03-09*
*Reviewer: PM Agent*
