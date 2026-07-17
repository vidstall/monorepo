> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/pm/SKILL.md` (workspace root). This file retained as deep playbook reference for full domain lenses, review templates, spec gap resolution patterns. M3 hygiene will decide split-out vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# PM Agent — Architecture Review Skill
> Skill for: DVConf Thesis Project
> Used by: PM Agent in `CLAUDE.md`
> Purpose: Structured methodology for reviewing architecture decisions, design trade-offs, and spec quality

---

## GSD Integration

When invoked by GSD executor (as `PM Agent` subagent), also read:
- `.planning/ROADMAP.md` — phase goals, success criteria, blockers
- `.planning/REQUIREMENTS.md` — requirement coverage and traceability
- `docs/architecture/TECH_DEBT.md` — known tech debt to watch for in current phase

PM Agent is spawned by GSD for:
- Architecture review before high-risk phases (e.g., Phase 3 validator assignment)
- Spec gap resolution when a task is blocked on an open question
- Design trade-off analysis when multiple implementation paths exist

---

## When to Apply This Skill

Apply this skill whenever the PM Agent is asked to:
- Review a design decision or architectural choice
- Evaluate a new module or service before implementation begins
- Resolve an open question from the spec
- Assess whether a proposed implementation matches the spec's intent
- Identify risks before a phase begins

---

## Step 1 — Understand the Decision in Context

Before evaluating anything, establish:

1. **What layer does this touch?**
   - On-chain only (Move contract)
   - Off-chain only (daemon / service)
   - Cross-boundary (on-chain coordination + off-chain execution)
   - Client (FE only)

2. **Which phase does it belong to?** (1–6)

3. **What does the spec say about it?**
   - Quote the relevant section from the spec document
   - If the spec is silent, flag this as a gap before proceeding

4. **What invariants must this decision preserve?**
   - Economic: no incentive for Sybil attacks, reward manipulation, or stake griefing
   - Security: validator identity hidden during session, caps not externally mintable
   - Correctness: basis-point math sums, paused flag enforced, stake lock respected
   - Liveness: system still functions if one node class misbehaves or goes offline

---

## Step 2 — Evaluate the Design Decision

For every significant design decision, produce this structured output:

```
DECISION: <one-sentence description of the choice>

WHAT IT SOLVES:
  <The specific problem this design addresses. Be concrete — name the attack, 
   failure mode, or user experience issue it prevents.>

TRADE-OFFS:
  (+) <Advantage 1>
  (+) <Advantage 2>
  (-) <Disadvantage 1 — cost, complexity, or limitation it introduces>
  (-) <Disadvantage 2>

ALTERNATIVES CONSIDERED:
  Alt A: <description> — rejected because <reason>
  Alt B: <description> — rejected because <reason>

FAILURE MODES:
  If <condition>: <what breaks and how badly>
  If <condition>: <what breaks and how badly>

VERDICT: ACCEPTED | NEEDS REVISION | REJECTED
REASON: <one sentence>
```

---

## Step 3 — Domain-Specific Review Lenses

Apply each lens that is relevant to the decision being reviewed.

---

### Lens A — On-Chain Economics

Ask these questions for any decision involving tokens, staking, rewards, or slashing:

- **Incentive alignment:** Does every actor maximize their reward by behaving honestly? Is there any scenario where misbehaving pays better than cooperating?
- **Sybil resistance:** Can an attacker create many identities cheaply to extract disproportionate rewards? What is the cost of a Sybil attack?
- **Griefing resistance:** Can a malicious actor force honest participants to lose stake without gaining anything themselves?
- **Stake lock timing:** Is the lock applied before the session can begin? Is there a race condition between locking and session start?
- **Reward basis:** Are rewards based on verifiable on-chain data (validator-attested work) or self-reported metrics? Self-reported = attack surface.
- **Slash redistribution:** Who receives slashed tokens? Is this fair and Sybil-resistant?
- **Basis-point invariants:** Do all weight sets and ratio sets sum to exactly 10,000?

---

### Lens B — Distributed Systems & Consensus

Ask these questions for any decision involving multiple nodes agreeing on state:

- **Consistency model:** What happens if two CP nodes run the relay scoring algorithm independently and get different results? What is the tie-breaking mechanism?
- **≥ 2/3 consensus assumption:** What is the minimum number of CP nodes needed for this to be Byzantine-fault-tolerant? With 3 CPs and one byzantine, does 2/3 still hold?
- **Liveness under partition:** If a CP node goes offline mid-vote, does the room creation stall? Is there a timeout and fallback?
- **Heartbeat failure handling:** What is the grace period before a CP is marked inactive? Is this stored on-chain or only in memory?
- **Median aggregation safety:** With N validators, how many can be malicious before the median is corrupted? (Answer: less than N/2)
- **Event ordering:** Can two chain events arrive out of order at an off-chain daemon? Does the daemon handle this correctly?

---

### Lens C — Security & Trust Assumptions

Ask these questions for any decision involving identity, credentials, or proofs:

- **Trust assumptions made explicit:** What must be true for this design to be secure? List every assumption.
- **Validator identity concealment:** Is there any on-chain transaction during the session that could link wallet B (session) to wallet A (public)? (Must be zero.)
- **Cap forgery:** Is there any code path where a Cap can be minted without going through the proper registration flow?
- **Dual-key proof:** Can a validator forge a SessionProof by only signing with one key? Does the contract verify both signatures independently?
- **Replay attacks:** Can an old SessionProof be resubmitted for a different session? Is the `room_id` binding enforced?
- **ValidatorSessionCap reuse:** Is `destroy_session_cap()` called atomically with proof submission, or is there a window where it could be reused?
- **Encrypted on-chain data:** The spec stores validator session wallet assignments "encrypted on-chain." Who holds the decryption key? What breaks if this key is lost or leaked?

---

### Lens D — On-Chain / Off-Chain Boundary

Ask these questions whenever the design crosses the chain boundary:

- **What goes on-chain and why?** On-chain storage is expensive and public. Everything on-chain should be either: (a) needed for trustless verification, or (b) needed for dispute resolution.
- **What stays off-chain and why?** Media data, ICE candidates, TURN credentials — these must never touch the chain.
- **Event reliability:** Off-chain daemons that subscribe to chain events may miss events (network drop, node restart). Does the daemon have a catch-up mechanism (e.g. polling for missed events)?
- **Time synchronization:** The chain uses epoch timestamps. Off-chain daemons use system clocks. Are these ever compared? If so, how is clock skew handled?
- **Finality assumptions:** Does the off-chain daemon act on unconfirmed transactions? Should it wait for finality before taking action?

---

### Lens E — Sui Move Specifics

Ask these questions for any Move contract decision:

- **Shared vs Owned objects:** Is this object accessed by many callers concurrently? If yes, it must be Shared. If it's only ever accessed by its owner, Owned is better (avoids contention).
- **Object contention:** Multiple transactions touching the same Shared object in the same epoch are serialized. Does a high-traffic shared object (e.g. RoomManager, RelayRegistry) become a bottleneck?
- **`public(package)` scope:** Are constructors that should be internal correctly scoped to `public(package)` rather than `public`?
- **One-time witness pattern:** Is the coin type using the correct OTW pattern (`has drop`, used exactly once in `init`)?
- **Object deletion:** When an object is consumed (e.g. `StakePosition` on withdrawal, `ValidatorSessionCap` on proof submission), is `object::delete(id)` called? Forgetting this leaks UIDs.
- **Abort codes:** Are all abort codes defined as named constants? Magic numbers in `assert!` are not acceptable.

---

### Lens F — WebRTC & Media (for OffChain and FE decisions)

Ask these questions for any decision involving real-time media:

- **NAT traversal path:** For the specific connection type (user→relay, relay→CDN), which NAT traversal method is used? Is it sufficient for symmetric NAT?
- **Relay as TURN:** The relay node naturally acts as a TURN server for user→relay connections. Is the relay exposing a TURN interface, or only a raw WebRTC endpoint?
- **mediasoup Router capacity:** A single mediasoup Worker has CPU limits. For MCU mode (active transcoding), how many concurrent rooms can one relay handle? Is there a cap enforced on-chain?
- **ICE candidate exchange timing:** Signaling must complete before the session starts. Is there a timeout? What happens if ICE fails?
- **Codec negotiation:** Does the SFU relay pass through without transcoding? Does the MCU relay transcode to a fixed output codec? Are these configs consistent between relay and client?
- **Stream continuity on relay failover:** If a relay drops mid-session, how quickly can the CP assign a replacement? What do clients experience during the gap?

---

## Step 4 — Output a PM Review

After applying the relevant lenses, produce a structured PM review:

```
PM REVIEW — <subject>
Phase: <1–6>
Spec reference: <section number or "not in spec">

SUMMARY:
  <2–3 sentences describing what is being reviewed and why it matters>

LENS RESULTS:
  [Economics]          PASS | WARNING | FAIL — <one-line finding>
  [Distributed Sys]    PASS | WARNING | FAIL — <one-line finding>
  [Security]           PASS | WARNING | FAIL — <one-line finding>
  [Chain Boundary]     PASS | WARNING | FAIL — <one-line finding>
  [Sui Move]           PASS | WARNING | FAIL — <one-line finding>
  [WebRTC/Media]       PASS | WARNING | FAIL — <one-line finding>

CRITICAL ISSUES (must resolve before implementation):
  [P0-1] <description and recommended fix>

WARNINGS (should resolve, won't block):
  [P1-1] <description and recommended approach>

OPEN QUESTIONS RAISED:
  [Q1] <new question this review surfaces, add to spec §15>

RECOMMENDATION: PROCEED | REVISE SPEC FIRST | BLOCKED ON <dependency>
```

---

## Step 4b -- Task Tracking

Task state lives in `.planning/STATE.md` (GSD canonical source).
For ad-hoc tasks outside GSD, add to STATE.md "Pending Todos" section.
Priority levels: P0 (blocks next phase), P1 (important), P2 (nice to have).

When QC returns NEEDS REVISION: convert every `[C*]` and `[N*]` item into a concrete entry in STATE.md immediately -- untracked issues get lost.

---

## Step 5 — Spec Gap Protocol

If the spec is silent on a topic that must be decided before implementation, follow this protocol:

1. **State the gap explicitly:** "The spec does not define X."
2. **Propose two or three concrete options** with trade-offs for each.
3. **Make a recommendation** with a one-sentence justification.
4. **Tag it as a new Open Question** to be added to `decentralized_video_conference-rev4.md §15`.
5. **Do not let implementation proceed** on the gapped item until the team has agreed on a resolution.

---

## Step 6 — Collaborative Requirements & Spec Evolution

The spec is a **living document**, not a frozen contract. The PM Agent must actively facilitate discussion when requirements need to change or when new insights surface during implementation. This is especially important in a 2-person thesis team where speed and correctness must both be preserved.

---

### When to Open a Requirements Discussion

The PM Agent **must** proactively open a discussion (do not silently proceed) in any of these situations:

- An implementation agent discovers that the spec, if followed literally, produces a broken or insecure result
- A new requirement is raised mid-phase that conflicts with existing design decisions
- An open question from spec §15 is about to become a blocker for the next task
- A pattern that worked in Phase N creates unexpected friction in Phase N+1
- External constraints change (e.g. Sui framework update, mediasoup API change)
- One of the two developers proposes a change verbally that hasn't been written into the spec yet

---

### How to Open a Requirements Discussion

When opening a discussion, the PM Agent always uses this format:

```
📋 REQUIREMENTS DISCUSSION — <topic title>
Triggered by: <what surfaced this — agent output, dev question, blocker, etc.>
Affects: Phase <N> · Module/Service: <name>
Current spec says: "<exact quote or 'spec is silent'>

THE PROBLEM:
  <1–3 sentences describing why the current spec or requirement is insufficient,
   ambiguous, or in conflict with something else>

OPTIONS:
  Option A — <name>
    Description: <what this option does>
    (+) <advantage>
    (-) <trade-off or cost>
    Spec change required: YES / NO / MINOR

  Option B — <name>
    Description: <what this option does>
    (+) <advantage>
    (-) <trade-off or cost>
    Spec change required: YES / NO / MINOR

  Option C — <name> (if applicable)
    ...

PM RECOMMENDATION: Option <X>
REASON: <one sentence — why this option is best given our constraints>

⏳ WAITING FOR YOUR DECISION before proceeding.
What do you think — go with Option <X>, or do you want to explore this differently?
```

The PM Agent **never unilaterally updates the spec** or instructs an implementation agent to proceed on an unresolved discussion. It waits for explicit confirmation from the developer.

---

### After the Developer Decides

Once a decision is confirmed:

1. **State the decision clearly:** "Confirmed: we go with Option B."
2. **Identify every spec document and section that needs updating** — list them explicitly.
3. **Identify every existing implementation** (Move module, TypeScript file, React component) that is affected by this change — flag them for the relevant agent.
4. **Update the Open Questions table** in `CLAUDE.md` if this resolves one, or add a new row if it surfaces another.
5. **Write the spec change as a diff summary** — "Section §X, paragraph Y: replace 'self_reported_rtt' with 'validator_probed_rtt'" — so the developer can apply it to the actual markdown file.

---

### Challenging the Spec (PM's Right and Duty)

The PM Agent has an explicit responsibility to push back on the spec when something looks architecturally wrong — even if both developers agreed on it previously. This is not obstruction; it is the PM doing its job.

Challenge the spec when:
- A decision has a known, severe failure mode that the spec doesn't acknowledge
- Two sections of the spec are internally inconsistent
- A best practice from distributed systems, blockchain security, or WebRTC engineering directly contradicts a spec decision
- An open question was implicitly resolved in the implementation in a way that conflicts with how it was resolved elsewhere

When challenging the spec, the PM Agent:
1. Quotes the exact spec text being challenged
2. States the specific problem — not a vague concern, a concrete failure scenario
3. Proposes a fix with the same Option A / B / C format above
4. **Waits for the developer to confirm** before treating the challenge as accepted

---

### Requirements Change Log

The PM Agent maintains a running change log in each session. At the end of any session where requirements changed, output this summary:

```
📝 REQUIREMENTS CHANGE LOG — <date / session>

CHANGED:
  [RC-1] <module/section> — <what changed and why>
  [RC-2] ...

SPEC FILES TO UPDATE:
  - decentralized_video_conference-rev4.md §<N>: <what to change>
  - phase1-foundation.md §<N>: <what to change> (if applicable)

IMPLEMENTATIONS AFFECTED:
  - <file.move / file.ts / Component.tsx>: <what needs to be revisited>

NEW OPEN QUESTIONS:
  - <question> → blocks Phase <N>
```

---

## Common Patterns & Decisions for This Project

Reference these when reviewing similar decisions:

| Pattern | Used In | Why Chosen | Known Trade-off |
|---|---|---|---|
| AdminCap governance | NetworkRegistry | Safe to transfer to multisig without changing logic | AdminCap holder is a single point of failure until DAO migration |
| Shared singletons per registry | All registries | Avoid contention by splitting write paths | High-traffic registries (RoomManager) may still serialize under load |
| Dual-key validator identity | ValidatorRegistry, SessionProof | Unlinkable during session, verifiable after | Requires secure key management; losing wallet B key loses ability to claim session reward |
| Basis points everywhere | All math | Integer-only arithmetic, no floating point | Large multiplications can overflow u64 — must check intermediate values |
| Median aggregation for proofs | Economic layer | Outlier-resistant, Sybil-resistant if < N/2 malicious | Requires minimum validator count per room; undefined in spec (Open Question) |
| `locked` flag on StakePosition | Staking | Enforces stake-at-risk during sessions | Lock/unlock is permissioned -- session module must be trusted to call these correctly |
| Work-based rewards | Economic layer | Eliminates self-reporting incentive | BASE_RATE calibration is critical; wrong value either under- or over-rewards relays |
| Secret auditor pattern | Validator design | Eliminates observer effect | Validators must maintain perfect behavioral camouflage; any distinguishing action reveals identity |
| queryEvents + cursor | All daemons | subscribeEvent deprecated; cursor gives crash recovery | Polling interval must be tuned (too fast = rate limit, too slow = stale) |
| JSON+TextEncoder proof serialization | Validator daemon | Simple, debuggable, no BCS dependency | BCS needed for production -- must migrate before mainnet |
| vi.hoisted mock pattern | All daemon tests | Vitest mock factories hoist above imports | Requires specific import ordering |

---

## DVConf-Specific Rules — Learned from Phase 1

### Parameter change → mandatory caller audit

Whenever a PM review covers output that adds, removes, or renames a parameter on any `public`, `public(package)`, or `entry` function, the PM **must** include a mandatory checklist item in the review output:

```
CALLER AUDIT REQUIRED:
  Function changed: <module>::<function> — added parameter: <name: Type>
  Callers to verify:
    - <module>_tests.move — search for all call sites
    - <other callers if known>
  Status: [ ] confirmed all callers updated
```

This item must be marked resolved before the PR moves to QC. Phase 1 lesson: `update_endpoint` had `turn_credential_hash` added to the source but tests still called with the old five-argument signature — the mismatch was caught by QC but should have been caught at PM review time.

---

### Skill files are living documents — PM update obligation

When a new pattern, pitfall, or rule is confirmed across multiple interactions (i.e., it happened, it was fixed, and it should not happen again), the PM Agent must update the relevant skill file(s) before closing the session. The skill files are in `docs/skills/`.

Steps when a new pattern is confirmed:
1. Identify which agent's skill file the lesson belongs to (OnChain, OffChain, FE, QC, PM).
2. Add the lesson to the appropriate section — as a concrete rule with a wrong/correct example where possible.
3. Note the update in the session's Requirements Change Log under `SPEC FILES TO UPDATE`.

Do not accumulate lessons as floating text in chat history. If it is worth knowing, it must be written into the skill file where the relevant agent will read it before the next task.
