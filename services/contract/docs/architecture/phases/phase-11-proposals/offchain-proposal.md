```
DESIGN PROPOSAL — OffChain: Phase 11 Signaling Daemon Chain Integration
Author: OffChain Agent
Phase: 11
Date: 2026-03-11

PURPOSE:
  Upgrade the signaling daemon from a stateless WebSocket server to a chain-aware node that
  self-registers on-chain with stake, sends periodic heartbeats, and reports connection load
  to the SignalingRegistry. Also extend @dvconf/shared with the signaling role constant,
  error code namespace 600-609, and signaling event type definitions.

OWNS:
  - Signaling role constant and error codes in @dvconf/shared (Task 5)
  - Signaling event type interfaces in @dvconf/shared (Task 5)
  - signalingRegistryId field in NetworkConfig (Task 5)
  - Signaling daemon auto-registration flow: auto-register.ts (Task 6)
  - Signaling daemon heartbeat + load reporting loop: heartbeat.ts (Task 6)
  - Signaling daemon chain-aware startup orchestration: index.ts (Task 6)

STRUCTS / TYPES:

  ── @dvconf/shared/types/constants.ts ──

  MinerRole (extend existing):
    Add `Signaling: 4` to the MinerRole const object.
    Role hierarchy: User(0) < Validator(1) < Relay(2) < CP(3) < Signaling(4)
    Note: The numeric ordering does not imply hierarchy; the on-chain staking module
    determines role from stake amount. The value 4 matches ROLE_SIGNALING in constants.move.

  ErrorCodes (extend existing):
    Add `signalingRegistry` namespace with codes 600-609:
      E_NOT_SIGNALING:      600  — MinerCap role is not ROLE_SIGNALING
      E_ALREADY_REGISTERED: 601  — signaling node already in registry table
      E_NOT_REGISTERED:     602  — signaling node not found in registry table
      E_PAUSED:             603  — network is paused
      E_NOT_OPERATOR:       604  — sender does not match registered operator
      (605-609 reserved for future signaling errors)

  ── @dvconf/shared/types/events.ts ──

  SignalingRegistered:
    miner_id:     string    — Sui object ID of the miner profile
    operator:     string    — Sui address of the signaling node operator
    endpoint_url: number[]  — UTF-8 bytes of the WebSocket endpoint URL
    region:       number[]  — UTF-8 bytes of the region identifier
    stake_amount: string    — stringified u64 stake amount

  SignalingHeartbeat:
    miner_id: string  — Sui object ID of the miner profile
    epoch:    string   — stringified u64 epoch timestamp

  SignalingLoadUpdated:
    miner_id: string  — Sui object ID of the miner profile
    new_load: string  — stringified u64 current connection count

  SignalingUnregistered:
    miner_id: string  — Sui object ID of the miner profile
    operator: string  — Sui address of the departing operator

  DvconfEvent union type: extend with all four new interfaces.

  ── @dvconf/shared/types/chain.ts ──

  NetworkConfig (extend existing):
    Add field: signalingRegistryId: string
    This is loaded from env var SIGNALING_REGISTRY_ID in loadNetworkConfig().

  ── @dvconf/shared/src/index.ts (barrel export) ──

  Add to type exports from events.ts:
    SignalingRegistered, SignalingHeartbeat, SignalingLoadUpdated, SignalingUnregistered

  ── signaling/src/auto-register.ts (NEW) ──

  ensureRegistered() return type:
    { minerCapId: string; stakePositionId: string }

  ── signaling/src/heartbeat.ts (NEW) ──

  No new exported types. Uses RoomManager from rooms.ts for getStats().

PUBLIC API:

  ── @dvconf/shared/types/constants.ts ──

  (Values added to existing const objects — no new function signatures)

  MinerRole.Signaling = 4
  ErrorCodes.signalingRegistry.E_NOT_SIGNALING = 600
  ErrorCodes.signalingRegistry.E_ALREADY_REGISTERED = 601
  ErrorCodes.signalingRegistry.E_NOT_REGISTERED = 602
  ErrorCodes.signalingRegistry.E_PAUSED = 603
  ErrorCodes.signalingRegistry.E_NOT_OPERATOR = 604

  ── @dvconf/shared/src/chain/client.ts ──

  loadNetworkConfig(): NetworkConfig
    Updated to read SIGNALING_REGISTRY_ID from env and include it in the returned config.

  ── signaling/src/auto-register.ts ──

  export async function ensureRegistered(
    client: SuiClient,
    signer: Ed25519Keypair,
    config: NetworkConfig,
    endpointUrl: string,
    region: string,
    logger: Logger,
  ): Promise<{ minerCapId: string; stakePositionId: string }>

    Two-step registration flow (mirrors cp-daemon/src/auto-register.ts):

    Step 0 — Early exit:
      If env var MINER_CAP_ID is set, log and return { minerCapId: env value, stakePositionId: '' }.
      The stakePositionId is not needed after initial registration; heartbeat uses MinerCap only.

    Step 1 — Register as miner (registration::register):
      Build TX with:
        - splitCoins(tx.gas, [250_000_000n])  — 0.25 DVCONF signaling threshold
        - moveCall: registration::register with arguments:
            tx.object(config.networkRegistryId)
            tx.object(config.minerStoreId)
            stakeCoin
            tx.pure.vector('u8', encode(endpointUrl))  — ip field (reuse for endpoint)
            tx.pure.u16(0)                              — port (unused, signaling uses URL)
            tx.pure.vector('u8', [])                    — stun_url (not applicable)
            tx.pure.vector('u8', [])                    — turn_url (not applicable)
            tx.pure.vector('u8', encode(region))        — region
            tx.pure.u64(0)                              — bandwidth_mbps (signaling is text-only)
            tx.pure.u64(0)                              — max_concurrent
            tx.pure.u64(1)                              — cpu_cores
            tx.pure.u8(0)                               — relay_mode (unused for signaling)
            tx.pure.vector('u8', [])                    — turn_credential_hash
      Extract from TX effects:
        - minerCapId via extractCreatedObjectByType(result, '::caps::MinerCap')
        - stakePositionId via extractCreatedObjectByType(result, '::staking::StakePosition')
      On failure: log error with guidance ("ensure wallet has >= 0.25 DVCONF"), exit(1).

    Step 2 — Register in SignalingRegistry (signaling_registry::register_signaling):
      Build TX with:
        - moveCall: signaling_registry::register_signaling with arguments:
            tx.object(config.networkRegistryId)         — net_reg: &NetworkRegistry
            tx.object(config.signalingRegistryId)       — registry: &mut SignalingRegistry
            tx.object(minerCapId)                       — cap: &MinerCap (from Step 1)
            tx.object(stakePositionId)                  — stake: &StakePosition (from Step 1)
            tx.pure.vector('u8', encode(endpointUrl))   — endpoint_url
            tx.pure.vector('u8', encode(region))        — region
      On failure: log error ("SignalingRegistry registration failed after miner registration
        succeeded. Manual intervention required."), exit(1).

    Step 3 — Log success:
      Log: "Auto-registered as signaling node. Set MINER_CAP_ID=<id> in .env to skip next time."
      Return { minerCapId, stakePositionId }.

  ── signaling/src/heartbeat.ts ──

  export function buildHeartbeatTx(
    tx: Transaction,
    config: NetworkConfig,
    minerCapId: string,
  ): void
    Adds moveCall: signaling_registry::heartbeat with arguments:
      tx.object(config.networkRegistryId)
      tx.object(config.signalingRegistryId)
      tx.object(minerCapId)

  export function buildUpdateLoadTx(
    tx: Transaction,
    config: NetworkConfig,
    minerCapId: string,
    load: number,
  ): void
    Adds moveCall: signaling_registry::update_load with arguments:
      tx.object(config.networkRegistryId)
      tx.object(config.signalingRegistryId)
      tx.object(minerCapId)
      tx.pure.u64(load)

  export function startHeartbeat(
    client: SuiClient,
    signer: Ed25519Keypair,
    config: NetworkConfig,
    minerCapId: string,
    intervalMs: number,
    roomManager: RoomManager,
    logger: Logger,
  ): () => void

    Combined heartbeat + load reporting loop (single setInterval):

    Every tick (default 30_000ms):
      1. Read current load: roomManager.getStats().connections
      2. Build a single Transaction containing BOTH moveCall operations:
         - buildHeartbeatTx(tx, config, minerCapId)
         - buildUpdateLoadTx(tx, config, minerCapId, currentLoad)
      3. Execute via executeWithRetry(client, signer, combinedTxBuilder, 'heartbeat+load', logger)
      4. Log success with { connections: currentLoad }

    Rationale for combining into a single TX:
      Reduces gas cost and RPC round-trips by 50%. Both operations target the same
      SignalingRegistry shared object and are idempotent — safe to batch.
      If one fails, the entire TX reverts, which is the correct behavior (stale load
      with fresh heartbeat or vice versa would be misleading).

    First tick fires immediately (same pattern as cp-daemon heartbeat.ts).
    Returns a stop function: () => { clearInterval(handle); logger.info('...stopped') }.

  ── signaling/src/index.ts (MODIFIED) ──

  Startup flow changes from:
    BEFORE:  createServer(PORT) → listen → SIGTERM/SIGINT handlers
    AFTER:   main() async function with chain bootstrap:

  export async function main(): Promise<void>

    1. Load chain config:
         import 'dotenv/config'
         const config = loadNetworkConfig()
         const client = createSuiClient(config.rpcUrl)
         const signer = loadKeypair('SIGNALING_KEYPAIR')

    2. Read signaling-specific env vars:
         const endpointUrl = process.env['ENDPOINT_URL']
           ?? `ws://127.0.0.1:${PORT}`   — default for local dev
         const region = process.env['REGION'] ?? 'local'

    3. Auto-register:
         const { minerCapId } = await ensureRegistered(
           client, signer, config, endpointUrl, region, logger
         )

    4. Start WebSocket server (existing createServer()):
         const wss = createServer(PORT)

    5. Start heartbeat loop:
         const heartbeatIntervalMs = parseInt(
           process.env['HEARTBEAT_INTERVAL_MS'] ?? '30000', 10
         )
         const stopHeartbeat = startHeartbeat(
           client, signer, config, minerCapId,
           heartbeatIntervalMs, roomManager, logger
         )

    6. Graceful shutdown (enhanced):
         function shutdown(): void {
           logger.info('Shutting down signaling server')
           stopHeartbeat()
           wss.close(() => {
             logger.info('Signaling server closed')
             process.exit(0)
           })
           setTimeout(() => process.exit(1), 5000)
         }
         process.on('SIGTERM', shutdown)
         process.on('SIGINT', shutdown)

    Module-level guard (existing pattern, preserved):
      if (isMainModule) { main().catch(...) }

  Note: The roomManager instance must be accessible to both createServer() and
  startHeartbeat(). Current code declares it at module scope — this is preserved.
  The roomManager is passed as a parameter to startHeartbeat() to avoid hidden coupling.

DEPENDS ON:
  - @dvconf/shared (types, chain helpers, logger) — already a dependency of cp-daemon,
    now also required by signaling daemon
  - @mysten/sui (SuiClient, Transaction, Ed25519Keypair) — new dependency for signaling/package.json
  - On-chain: signaling_registry module (Task 2) — defines the Move functions called by
    auto-register.ts and heartbeat.ts
  - On-chain: constants.move ROLE_SIGNALING = 4 (Task 1) — determines role from stake
  - On-chain: registration module — register() issues MinerCap for signaling role
  - rooms.ts (existing) — getStats().connections provides load data for heartbeat

ERROR CODES:
  All codes mirror on-chain signaling_registry.move error namespace 600-609:

  ErrorCodes.signalingRegistry = {
    E_NOT_SIGNALING:      600,  // MinerCap role != ROLE_SIGNALING
    E_ALREADY_REGISTERED: 601,  // duplicate registration attempt
    E_NOT_REGISTERED:     602,  // heartbeat/update for unregistered node
    E_PAUSED:             603,  // network paused
    E_NOT_OPERATOR:       604,  // sender != registered operator
  }

EVENTS EMITTED:
  Off-chain code does not emit events directly — it submits TXs that cause on-chain
  event emission. The events the daemon triggers through its TXs are:

  SignalingRegistered   — emitted by register_signaling() TX in auto-register.ts Step 2
  SignalingHeartbeat    — emitted by heartbeat() TX every 30s in heartbeat.ts
  SignalingLoadUpdated  — emitted by update_load() TX every 30s in heartbeat.ts
  SignalingUnregistered — not triggered by daemon code (manual unregister only)

OPEN QUESTIONS:

  1. RoomManager export scope:
     roomManager is currently a module-level const in index.ts. For testability,
     should we export it or inject it via a factory? The current design passes it as a
     parameter to startHeartbeat(), which is sufficient. No change proposed unless
     Architect prefers a different pattern.

  2. Combined heartbeat+load TX vs separate TXs:
     This proposal batches heartbeat and update_load into a single PTB to save gas.
     If the on-chain module requires them as separate entry functions (not composable
     in a single TX), we fall back to two sequential executeWithRetry calls. Need to
     confirm that signaling_registry::heartbeat() and signaling_registry::update_load()
     are both callable within one PTB (they both take &mut SignalingRegistry — Sui allows
     this within a single TX as sequential mutations).

  3. MINER_CAP_ID skip behavior:
     When MINER_CAP_ID is set, ensureRegistered() skips BOTH steps (miner registration
     AND signaling registry registration). This assumes the operator completed both steps
     in a previous run. If a node registered as a miner but crashed before Step 2,
     the operator must manually complete SignalingRegistry registration or clear MINER_CAP_ID
     to re-run the full flow. Is this acceptable, or should we add a check against
     SignalingRegistry to verify the node is actually registered?

  4. Stake amount source:
     The 250_000_000n (0.25 DVCONF) threshold is hardcoded in auto-register.ts.
     If the on-chain threshold changes via update_role_thresholds(), the daemon would
     need to be redeployed. Should we query the current threshold from NetworkRegistry
     via devInspect before registering? cp-daemon hardcodes 2_000_000_000n, so this
     is consistent with the existing pattern. No change proposed.

  5. package.json dependency addition:
     signaling/package.json needs `@mysten/sui` and `dotenv` added to dependencies.
     The signaling daemon currently has zero chain dependencies — this is a deliberate
     architectural shift from "ZERO chain dependencies" (comment in current index.ts)
     to "chain-aware node" as required by Phase 11. The old DAEMON-02 comment must be
     removed or updated.
```

## File Change Summary

### Modified Files

| File | Change |
|------|--------|
| `dvconf-daemons/packages/shared/src/types/constants.ts` | Add `Signaling: 4` to MinerRole, add `signalingRegistry` to ErrorCodes |
| `dvconf-daemons/packages/shared/src/types/events.ts` | Add 4 signaling event interfaces, extend DvconfEvent union |
| `dvconf-daemons/packages/shared/src/types/chain.ts` | Add `signalingRegistryId` to NetworkConfig |
| `dvconf-daemons/packages/shared/src/chain/client.ts` | Add `SIGNALING_REGISTRY_ID` env read in loadNetworkConfig() |
| `dvconf-daemons/packages/shared/src/index.ts` | Add signaling event type re-exports |
| `dvconf-daemons/apps/signaling/src/index.ts` | Add chain bootstrap (main() async, auto-register, heartbeat) |
| `dvconf-daemons/apps/signaling/package.json` | Add `@mysten/sui`, `dotenv` dependencies |

### New Files

| File | Purpose |
|------|---------|
| `dvconf-daemons/apps/signaling/src/auto-register.ts` | Two-step registration: miner + SignalingRegistry |
| `dvconf-daemons/apps/signaling/src/heartbeat.ts` | Combined heartbeat + load reporting loop (30s interval) |

### New Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SIGNALING_REGISTRY_ID` | Yes (via loadNetworkConfig) | none | Sui object ID of SignalingRegistry shared object |
| `SIGNALING_KEYPAIR` | Yes | none | Base64-encoded Ed25519 keypair for the signaling node |
| `ENDPOINT_URL` | No | `ws://127.0.0.1:<PORT>` | Public WebSocket URL clients connect to |
| `REGION` | No | `local` | Region identifier for discovery scoring |
| `MINER_CAP_ID` | No | none | Skip auto-registration if set (from previous run) |
| `HEARTBEAT_INTERVAL_MS` | No | `30000` | Heartbeat + load report interval in milliseconds |
