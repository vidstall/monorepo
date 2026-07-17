DESIGN PROPOSAL — FE: Phase 11 Client Signaling Discovery
Author: FE Agent
Phase: 11
Date: 2026-03-11

PURPOSE:
  Replace the hardcoded signaling server URL with on-chain discovery that queries
  the SignalingRegistry, scores available nodes by region affinity and load, and
  falls back to the env-var URL when no nodes are registered.

OWNS:
  - Client-side signaling node discovery logic (query, score, select)
  - Fallback behavior when the registry is empty or unreachable
  - The bridge between discovery result and WebSocket connection in useSignaling

STRUCTS / TYPES:

  /** Raw on-chain signaling node info decoded from devInspect BCS response. */
  interface SignalingNodeEntry {
    operator: string;        // Sui address of the signaling node operator
    endpoint_url: string;    // WebSocket URL (decoded from vector<u8>)
    region: string;          // Region tag (decoded from vector<u8>), e.g. "eu-west"
    load: number;            // Current connection count reported by the node
    is_active: boolean;      // Whether the node passed heartbeat liveness
  }

  /** Scored node after client-side ranking. */
  interface ScoredSignalingNode {
    url: string;             // endpoint_url from on-chain
    score: number;           // Computed score (higher is better)
    region: string;          // Region tag for debug display
    load: number;            // Current load for debug display
  }

  /** Return type of useSignalingDiscovery hook. */
  interface UseSignalingDiscoveryResult {
    url: string;             // Best signaling node URL to connect to
    isFromChain: boolean;    // true = discovered from registry; false = env-var fallback
    isLoading: boolean;      // true while the devInspect call is in flight
    error: string | null;    // Human-readable error message if discovery failed
    allNodes: ScoredSignalingNode[];  // Full scored list for debug/UI inspection
    refetch: () => void;     // Manual refetch trigger
  }

PUBLIC API:

  // ── New hook: src/hooks/useSignalingDiscovery.ts ──────────────────────

  /**
   * Discovers the best signaling node from the on-chain SignalingRegistry.
   *
   * @param clientRegion  Optional region hint (e.g. "eu-west"). When provided,
   *                      nodes in the same region receive a score bonus.
   *                      Defaults to CONFIG.CLIENT_REGION (env var) or undefined.
   * @returns UseSignalingDiscoveryResult
   */
  function useSignalingDiscovery(clientRegion?: string): UseSignalingDiscoveryResult

  // ── Changed hook: src/hooks/useSignaling.ts ───────────────────────────

  /**
   * BEFORE (current):
   *   function useSignaling(callbacks: SignalingCallbacks)
   *     // Reads CONFIG.SIGNALING_URL internally on line 30
   *
   * AFTER:
   *   function useSignaling(signalingUrl: string, callbacks: SignalingCallbacks)
   *     // Accepts URL as first parameter; no longer reads CONFIG.SIGNALING_URL
   *     // Re-connects when signalingUrl changes (close old WS, open new)
   */
  function useSignaling(signalingUrl: string, callbacks: SignalingCallbacks)

  // ── Changed config: src/config.ts ─────────────────────────────────────

  /**
   * New fields added to AppConfig interface:
   *
   *   SIGNALING_REGISTRY_ID: string
   *     — Required. Shared object ID of the on-chain SignalingRegistry.
   *     — Source: requireEnv('VITE_SIGNALING_REGISTRY_ID')
   *
   *   SIGNALING_URL: string
   *     — Kept as-is. Now serves as the fallback URL when discovery returns
   *       zero active nodes or fails.
   *
   *   CLIENT_REGION: string
   *     — Optional. Hint for region-aware scoring.
   *     — Source: import.meta.env.VITE_CLIENT_REGION ?? ''
   *
   *   SIGNALING_DISCOVERY_POLL_INTERVAL: number
   *     — Optional. How often to re-query the registry (ms).
   *     — Source: import.meta.env.VITE_SIGNALING_DISCOVERY_POLL_INTERVAL ?? '30000'
   *     — Default: 30000 (30s, matches heartbeat interval)
   */

DEPENDS ON:

  On-chain (Task 2 — SignalingRegistry module):
    - signaling_registry::active_signaling_count(&SignalingRegistry): u64
      Used to determine if any nodes are registered before iterating.

    - signaling_registry::borrow_info(&SignalingRegistry, miner_id: ID): &SignalingNodeInfo
      Used to read individual node details (endpoint_url, region, load, is_active).

    NOTE: The devInspect approach requires an accessor that returns the full set of
    active signaling nodes, OR a way to iterate the internal Table. Since Move Tables
    are not directly iterable from devInspect, the on-chain module must expose either:
      (a) A vector-returning accessor: get_active_nodes(&SignalingRegistry): vector<SignalingNodeInfo>
      (b) An indexed accessor: get_node_at(&SignalingRegistry, index: u64): SignalingNodeInfo
    See OPEN QUESTIONS below.

  Client-internal:
    - CONFIG object (src/config.ts) — for SIGNALING_REGISTRY_ID, SIGNALING_URL fallback,
      CLIENT_REGION, SIGNALING_DISCOVERY_POLL_INTERVAL, PACKAGE_ID
    - useSuiClient() from @mysten/dapp-kit — for devInspect calls
    - Transaction from @mysten/sui/transactions — for building devInspect TX

ERROR CODES:
  N/A — This is a client-side hook. No on-chain error codes are introduced.
  Client-side error strings:
    - "Signaling discovery failed: <reason>"      — devInspect call threw
    - "No active signaling nodes found"           — registry returned zero active nodes
    - "Failed to decode signaling registry data"  — BCS decode error

EVENTS EMITTED:
  N/A — No on-chain events. The hook is read-only (devInspect).

  Console logging (development only):
    - console.info('[SignalingDiscovery] Discovered N nodes, best: <url> (score: X.XX)')
    - console.warn('[SignalingDiscovery] No active nodes, falling back to CONFIG.SIGNALING_URL')
    - console.error('[SignalingDiscovery] Query failed:', error)

OPEN QUESTIONS:

  1. Table iteration from devInspect:
     The SignalingRegistry stores nodes in a sui::table::Table<ID, SignalingNodeInfo>.
     Move Tables are key-value stores that cannot be iterated without knowing the keys.
     devInspect can only call Move functions, not scan dynamic fields directly.

     Proposed solution: Request the OnChain Agent to add one of:
       (a) get_active_endpoints(&SignalingRegistry): vector<SignalingNodeInfo>
           — Iterates the internal table, filters is_active == true, returns a vector.
           — Pro: Single devInspect call. Con: Gas cost scales with node count.
       (b) A parallel VecSet<ID> of active node IDs alongside the Table, plus an indexed
           accessor get_node_at(registry, index): (vector<u8>, vector<u8>, u64, bool)
           — Pro: Supports pagination. Con: More on-chain storage.
       (c) Use sui_getDynamicFields RPC to enumerate table keys client-side, then
           devInspect borrow_info for each key.
           — Pro: No on-chain changes. Con: N+1 RPC calls, slower.

     Recommendation: Option (a) is simplest and sufficient for the expected node count
     (<100 signaling nodes). If the OnChain Agent already included a vector accessor
     in Task 2, this is resolved.

  2. Region string format:
     What format will region tags use? Free-form strings (e.g. "eu-west", "us-east")
     or an enum? The scoring algorithm does an exact string match, so both the daemon
     (REGION env var) and the client (VITE_CLIENT_REGION env var) must use the same
     vocabulary. Suggest documenting a canonical region list, or accepting that exact
     match is best-effort.

  3. Re-connection on URL change:
     When useSignalingDiscovery returns a different URL (e.g. because the best node
     changed due to load), useSignaling must close the old WebSocket and open a new one.
     This will briefly disconnect the user from signaling. Should we:
       (a) Only switch URLs when not currently in a room (safest)
       (b) Switch immediately and let the new WS rejoin the room automatically
       (c) Never switch mid-session — lock the URL once connect() is called
     Recommendation: Option (c) — lock URL at connect() time. Discovery runs
     continuously for the next connection, but the active session is not disrupted.

---

IMPLEMENTATION DETAILS (for Architect review):

## Scoring Algorithm

  function scoreNode(node: SignalingNodeEntry, clientRegion: string): number {
    const REGION_MATCH_BONUS = 10;
    const regionScore = (clientRegion && node.region === clientRegion)
      ? REGION_MATCH_BONUS
      : 0;
    const loadScore = 1 / (node.load + 1);
    return regionScore + loadScore;
  }

  Rationale:
  - REGION_MATCH_BONUS = 10 makes region affinity dominate over load differences.
    A same-region node with 100 connections (score = 10.0099) beats a cross-region
    node with 0 connections (score = 1.0). This is intentional: latency savings
    from region proximity outweigh load balancing across regions.
  - 1/(load+1) ensures zero-load nodes score 1.0, and score degrades smoothly.
    +1 in the denominator avoids division by zero.
  - Ties are broken by array order (first registered wins). No randomization needed
    at this scale.

## devInspect Query Pattern (following useNetworkStats.ts)

  const tx = new Transaction();

  // Assuming option (a) from OPEN QUESTIONS — vector-returning accessor
  tx.moveCall({
    target: `${CONFIG.PACKAGE_ID}::signaling_registry::get_active_endpoints`,
    arguments: [tx.object(CONFIG.SIGNALING_REGISTRY_ID)],
  });

  const result = await client.devInspectTransactionBlock({
    transactionBlock: tx as any,
    sender: ZERO_ADDRESS,
  });

  // Decode BCS-encoded vector<SignalingNodeInfo>
  // Each entry: endpoint_url (vector<u8>), region (vector<u8>), load (u64), is_active (bool)
  // Use @mysten/bcs or manual decoding depending on available tooling.

## Fallback Behavior

  1. devInspect call succeeds, returns active nodes -> score and select best
  2. devInspect call succeeds, returns empty vector -> fallback to CONFIG.SIGNALING_URL
  3. devInspect call fails (network error, bad object ID) -> fallback to CONFIG.SIGNALING_URL
  4. CONFIG.SIGNALING_REGISTRY_ID is empty string -> skip discovery entirely, use CONFIG.SIGNALING_URL

  In cases 2-4, isFromChain is set to false so the caller can display a warning
  or log that discovery was not used.

## useSignaling.ts Changes

  Current line 30:
    const ws = new WebSocket(CONFIG.SIGNALING_URL);

  Changes to:
    const ws = new WebSocket(signalingUrl);

  The signalingUrl parameter is added as the first argument to useSignaling().
  The hook no longer imports or references CONFIG.SIGNALING_URL.

  Additionally, a useEffect or ref-based guard ensures that if signalingUrl changes
  while a WebSocket is already open, the hook does NOT automatically reconnect
  (per OPEN QUESTIONS item 3, recommendation (c) — lock at connect time). The new
  URL will only be used on the next explicit connect() call.

## Caller Integration Example

  // In the room join page or session component:
  const { url: signalingUrl, isFromChain } = useSignalingDiscovery(CONFIG.CLIENT_REGION);
  const signaling = useSignaling(signalingUrl, callbacks);

  // Optionally show a badge:
  // isFromChain ? "Connected via on-chain discovery" : "Using fallback signaling server"

## New Environment Variables

  # .env.example additions:
  VITE_SIGNALING_REGISTRY_ID=0x...     # Required: SignalingRegistry shared object ID
  VITE_CLIENT_REGION=                   # Optional: client region hint for scoring (e.g. "eu-west")
  VITE_SIGNALING_DISCOVERY_POLL_INTERVAL=30000  # Optional: discovery poll interval in ms

## File Change Summary

  | File | Change |
  |------|--------|
  | src/hooks/useSignalingDiscovery.ts | NEW — discovery hook with devInspect + scoring |
  | src/hooks/useSignaling.ts | MODIFIED — accept signalingUrl param instead of CONFIG.SIGNALING_URL |
  | src/config.ts | MODIFIED — add SIGNALING_REGISTRY_ID, CLIENT_REGION, SIGNALING_DISCOVERY_POLL_INTERVAL |
  | .env.example | MODIFIED — add VITE_SIGNALING_REGISTRY_ID, VITE_CLIENT_REGION, VITE_SIGNALING_DISCOVERY_POLL_INTERVAL |
