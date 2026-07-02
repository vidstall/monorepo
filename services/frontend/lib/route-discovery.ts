import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { bcs } from "@mysten/sui/bcs";

const ROLE_SFU = 0;
const ROLE_COORDINATOR = 1;
const ROLE_ROUTER = 2;

const ROLE_LABELS: Record<number, string> = {
  [ROLE_SFU]: "SFU",
  [ROLE_COORDINATOR]: "COORDINATOR",
  [ROLE_ROUTER]: "ROUTER",
};
const STALE_THRESHOLD_MS = 15 * 60 * 1000;
const HEALTH_PROBE_TIMEOUT_MS = 4000;
const CANDIDATES_CACHE_TTL_MS = 60 * 1000;
const SUI_COIN_TYPE = "0x2::sui::SUI";
const ZERO_SENDER =
  "0x0000000000000000000000000000000000000000000000000000000000000000";

const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

type Network = keyof typeof JSON_RPC_URLS;

export type RouteCandidate = {
  nodeId: string;
  endpoint: string;
  updatedAtMs: number;
};

type ChainConfig = {
  network: Network;
  packageId: string;
  registryObjectId: string;
};

function loadChainConfig(): ChainConfig {
  const network = (process.env.NEXT_PUBLIC_SUI_NETWORK ?? "devnet") as Network;
  const packageId = process.env.NEXT_PUBLIC_PACKAGE_ID;
  const registryObjectId = process.env.NEXT_PUBLIC_REGISTRY_OBJECT_ID;
  if (!(network in JSON_RPC_URLS)) throw new Error(`Unsupported contract network: ${network}`);
  if (!packageId) throw new Error("NEXT_PUBLIC_PACKAGE_ID not set");
  if (!registryObjectId) throw new Error("NEXT_PUBLIC_REGISTRY_OBJECT_ID not set");
  return { network, packageId, registryObjectId };
}

function moveTarget(config: ChainConfig, functionName: string): string {
  return `${config.packageId}::node_registry::${functionName}`;
}

function client(config: ChainConfig): SuiJsonRpcClient {
  return new SuiJsonRpcClient({ network: config.network as never, url: JSON_RPC_URLS[config.network] });
}

async function devInspect(
  config: ChainConfig,
  build: (tx: Transaction) => void,
): Promise<Uint8Array[] | null> {
  const tx = new Transaction();
  build(tx);
  const result = await client(config).devInspectTransactionBlock({
    transactionBlock: tx,
    sender: ZERO_SENDER,
  });
  if (result.effects.status.status !== "success" || !result.results) return null;
  return result.results.map((r) => new Uint8Array(r.returnValues?.[0]?.[0] ?? []));
}

function parseU64(bytes: Uint8Array): bigint {
  return BigInt(bcs.u64().parse(bytes));
}

function parseBool(bytes: Uint8Array): boolean {
  return bcs.bool().parse(bytes);
}

function parseU8(bytes: Uint8Array): number {
  return bcs.u8().parse(bytes);
}

function parseUtf8Vector(bytes: Uint8Array): string {
  return new TextDecoder().decode(bcs.byteVector().parse(bytes));
}

async function fetchNextNodeId(config: ChainConfig): Promise<number> {
  const results = await devInspect(config, (tx) => {
    tx.moveCall({
      target: moveTarget(config, "next_node_id"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [tx.object(config.registryObjectId)],
    });
  });
  if (!results?.[0]) throw new Error("failed to read next_node_id from registry");
  return Number(parseU64(results[0]));
}

/**
 * Move aborts a whole devInspect PTB the moment any command in it aborts, so this can only call
 * accessors that never assert (node_exists / has_worker_role) across the full id range in one shot.
 * A second, narrower pass (fetchRouterDetails) fetches the asserting accessors only for ids already
 * confirmed to exist and have a role assigned.
 */
async function fetchExistingWithRole(config: ChainConfig, nextNodeId: number): Promise<number[]> {
  if (nextNodeId <= 1) return [];
  const results = await devInspect(config, (tx) => {
    for (let nodeId = 1; nodeId < nextNodeId; nodeId++) {
      tx.moveCall({
        target: moveTarget(config, "node_exists"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), tx.pure.u64(BigInt(nodeId))],
      });
      tx.moveCall({
        target: moveTarget(config, "has_worker_role"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), tx.pure.u64(BigInt(nodeId))],
      });
    }
  });
  if (!results) return [];

  const candidates: number[] = [];
  for (let nodeId = 1; nodeId < nextNodeId; nodeId++) {
    const base = (nodeId - 1) * 2;
    const exists = parseBool(results[base]);
    const hasRole = parseBool(results[base + 1]);
    if (exists && hasRole) candidates.push(nodeId);
  }
  return candidates;
}

export type WorkerRecord = {
  nodeId: string;
  role: number;
  roleLabel: string;
  active: boolean;
  endpoint: string;
  updatedAtMs: number;
};

async function fetchWorkerRecords(config: ChainConfig, nodeIds: number[]): Promise<WorkerRecord[]> {
  if (nodeIds.length === 0) return [];
  const results = await devInspect(config, (tx) => {
    for (const nodeId of nodeIds) {
      const id = tx.pure.u64(BigInt(nodeId));
      tx.moveCall({
        target: moveTarget(config, "worker_role"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
      tx.moveCall({
        target: moveTarget(config, "worker_active"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
      tx.moveCall({
        target: moveTarget(config, "worker_metadata_uri"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
      tx.moveCall({
        target: moveTarget(config, "worker_updated_at_ms"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
    }
  });
  // A race between the two passes (e.g. a worker unregistering in between) can abort this whole
  // batch; treat that as "no fresh data available" rather than surfacing an error to the caller.
  if (!results) return [];

  return nodeIds.map((nodeId, index) => {
    const base = index * 4;
    const role = parseU8(results[base]);
    const active = parseBool(results[base + 1]);
    const endpoint = parseUtf8Vector(results[base + 2]);
    const updatedAtMs = Number(parseU64(results[base + 3]));
    return {
      nodeId: String(nodeId),
      role,
      roleLabel: ROLE_LABELS[role] ?? `ROLE_${role}`,
      active,
      endpoint,
      updatedAtMs,
    };
  });
}

export async function fetchActiveRouters(): Promise<RouteCandidate[]> {
  const config = loadChainConfig();
  const nextNodeId = await fetchNextNodeId(config);
  const candidateIds = await fetchExistingWithRole(config, nextNodeId);
  const records = await fetchWorkerRecords(config, candidateIds);
  const now = Date.now();
  return records
    .filter((r) => r.role === ROLE_ROUTER && r.active && now - r.updatedAtMs <= STALE_THRESHOLD_MS)
    .map((r) => ({ nodeId: r.nodeId, endpoint: r.endpoint, updatedAtMs: r.updatedAtMs }));
}

export async function fetchAllWorkers(): Promise<WorkerRecord[]> {
  const config = loadChainConfig();
  const nextNodeId = await fetchNextNodeId(config);
  const candidateIds = await fetchExistingWithRole(config, nextNodeId);
  return fetchWorkerRecords(config, candidateIds);
}

export async function probeLatency(
  candidate: RouteCandidate,
  timeoutMs = HEALTH_PROBE_TIMEOUT_MS,
): Promise<number | null> {
  const start = performance.now();
  try {
    const response = await fetch(`${candidate.endpoint}/contract/health`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return null;
    return performance.now() - start;
  } catch {
    return null;
  }
}

async function pickBestRoute(
  candidates: RouteCandidate[],
): Promise<{ candidate: RouteCandidate; latencyMs: number } | null> {
  const probes = await Promise.all(
    candidates.map(async (candidate) => ({
      candidate,
      latencyMs: await probeLatency(candidate),
    })),
  );
  const reachable = probes.filter((p): p is { candidate: RouteCandidate; latencyMs: number } => p.latencyMs !== null);
  if (reachable.length === 0) return null;
  reachable.sort((a, b) => a.latencyMs - b.latencyMs);
  return reachable[0];
}

let _candidatesCache: { candidates: RouteCandidate[]; fetchedAtMs: number } | null = null;

async function cachedCandidates(): Promise<RouteCandidate[]> {
  const now = Date.now();
  if (_candidatesCache && now - _candidatesCache.fetchedAtMs < CANDIDATES_CACHE_TTL_MS) {
    return _candidatesCache.candidates;
  }
  const candidates = await fetchActiveRouters();
  _candidatesCache = { candidates, fetchedAtMs: now };
  return candidates;
}

function devFallbackEndpoint(): string | null {
  const override = process.env.NEXT_PUBLIC_ROUTES_URL;
  if (override) return override;
  if (process.env.NODE_ENV !== "production") return "http://localhost:3001/api";
  return null;
}

export async function getWorkingRoute(exclude: Set<string> = new Set()): Promise<string> {
  const fallback = devFallbackEndpoint();
  if (fallback && !exclude.has(fallback)) return fallback;

  let onChainCandidates: RouteCandidate[] = [];
  try {
    onChainCandidates = await cachedCandidates();
  } catch {
    onChainCandidates = [];
  }
  const candidates = onChainCandidates.filter((c) => !exclude.has(c.endpoint));
  const best = await pickBestRoute(candidates);
  if (!best) throw new Error("No reachable routes are currently registered on-chain");
  return best.candidate.endpoint;
}

export type SelectedRoute = { nodeId: string; endpoint: string; latencyMs: number };

/**
 * Always reflects genuine on-chain latency-based selection, bypassing the
 * NEXT_PUBLIC_ROUTES_URL/localhost dev fallback that getWorkingRoute uses for
 * the real room-joining path. For display purposes only.
 */
export async function selectOnChainRoute(): Promise<SelectedRoute | null> {
  let onChainCandidates: RouteCandidate[] = [];
  try {
    onChainCandidates = await cachedCandidates();
  } catch {
    onChainCandidates = [];
  }
  const best = await pickBestRoute(onChainCandidates);
  if (!best) return null;
  return { nodeId: best.candidate.nodeId, endpoint: best.candidate.endpoint, latencyMs: Math.round(best.latencyMs) };
}
