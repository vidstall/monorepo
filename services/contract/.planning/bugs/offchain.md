# Bug Log — OffChain (Node.js Daemons)

> Module: `dvconf-daemons/` — signaling, relay, CP, validator daemons
> Prefix: `BUG-OFF-`

---

### BUG-OFF-001: Reversal Protocol not followed on Task 4 shared type changes
- **Level**: ERROR (critical blocker)
- **Phase**: Phase 13
- **Found by**: QC Agent
- **Module/File**: `packages/shared/src/types/constants.ts`, `packages/shared/src/types/events.ts`, `packages/shared/src/types/chain.ts`, `packages/shared/src/index.ts`
- **Runtime error**: N/A (process violation)
- **Description**: OffChain Agent modified four existing files without documenting a SNAPSHOT before editing and PRESERVATION CHECK after editing, violating the mandatory Reversal Protocol specified in QC_AGENT_SKILL.md. This is a gating issue that prevents merge regardless of code quality. Agent must re-apply edits with proper protocol documentation.
- **Status**: OPEN
- **Fixed by**: pending
