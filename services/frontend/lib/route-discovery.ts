import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { bcs } from "@mysten/sui/bcs";

const ROLE_SFU = 0;
const ROLE_COORDINATOR = 1;
const ROLE_ROUTER = 2;
const ROLE_NONE = -1;

const ROLE_LABELS: Record<number, string> = {
  [ROLE_SFU]: "SFU",
  [ROLE_COORDINATOR]: "COORDINATOR",
  [ROLE_ROUTER]: "ROUTER",
  [ROLE_NONE]: "NONE",
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
  if (!(network in JSON_RPC_URLS))
    throw new Error(`Unsupported contract network: ${network}`);
  if (!packageId) throw new Error("NEXT_PUBLIC_PACKAGE_ID not set");
  if (!registryObjectId)
    throw new Error("NEXT_PUBLIC_REGISTRY_OBJECT_ID not set");
  return { network, packageId, registryObjectId };
}

const FUNCTION_MODULES: Record<string, string> = {
  next_node_id: "workers",
  node_exists: "workers",
  worker_active: "workers",
  worker_metadata_uri: "workers",
  worker_updated_at_ms: "workers",
  has_worker_role: "role_governance",
  worker_role: "role_governance",
};

function moveTarget(config: ChainConfig, functionName: string): string {
  const module = FUNCTION_MODULES[functionName];
  if (!module) {
    throw new Error(
      `moveTarget: no module mapping for function "${functionName}"`,
    );
  }
  return `${config.packageId}::${module}::${functionName}`;
}

function client(config: ChainConfig): SuiJsonRpcClient {
  return new SuiJsonRpcClient({
    network: config.network as never,
    url: JSON_RPC_URLS[config.network],
  });
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
  if (result.effects.status.status !== "success" || !result.results)
    return null;
  return result.results.map(
    (r) => new Uint8Array(r.returnValues?.[0]?.[0] ?? []),
  );
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
  if (!results?.[0])
    throw new Error("failed to read next_node_id from registry");
  return Number(parseU64(results[0]));
}

/**
 * Move aborts a whole devInspect PTB the moment any command in it aborts, so this can only call
 * accessors that never assert (node_exists / has_worker_role) across the full id range in one shot.
 * A second, narrower pass (fetchWorkerRecords) fetches the asserting accessors (worker_role) only
 * for ids already confirmed to have a role assigned; ids without a role are still returned so the
 * UI can list them with roleLabel "NONE" instead of silently dropping them.
 */
async function fetchExistingNodeIds(
  config: ChainConfig,
  nextNodeId: number,
): Promise<{ nodeId: number; hasRole: boolean }[]> {
  if (nextNodeId <= 1) return [];
  const results = await devInspect(config, (tx) => {
    for (let nodeId = 1; nodeId < nextNodeId; nodeId++) {
      tx.moveCall({
        target: moveTarget(config, "node_exists"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [
          tx.object(config.registryObjectId),
          tx.pure.u64(BigInt(nodeId)),
        ],
      });
      tx.moveCall({
        target: moveTarget(config, "has_worker_role"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [
          tx.object(config.registryObjectId),
          tx.pure.u64(BigInt(nodeId)),
        ],
      });
    }
  });
  if (!results) return [];

  const nodes: { nodeId: number; hasRole: boolean }[] = [];
  for (let nodeId = 1; nodeId < nextNodeId; nodeId++) {
    const base = (nodeId - 1) * 2;
    const exists = parseBool(results[base]);
    const hasRole = parseBool(results[base + 1]);
    if (exists) nodes.push({ nodeId, hasRole });
  }
  return nodes;
}

export type WorkerRecord = {
  nodeId: string;
  role: number;
  roleLabel: string;
  active: boolean;
  endpoint: string;
  updatedAtMs: number;
};

async function fetchWorkerRecords(
  config: ChainConfig,
  nodes: { nodeId: number; hasRole: boolean }[],
): Promise<WorkerRecord[]> {
  if (nodes.length === 0) return [];
  const roleNodeIds = nodes.filter((n) => n.hasRole).map((n) => n.nodeId);

  const results = await devInspect(config, (tx) => {
    for (const { nodeId } of nodes) {
      const id = tx.pure.u64(BigInt(nodeId));
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
    for (const nodeId of roleNodeIds) {
      tx.moveCall({
        target: moveTarget(config, "worker_role"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [
          tx.object(config.registryObjectId),
          tx.pure.u64(BigInt(nodeId)),
        ],
      });
    }
  });
  // A race between the two passes (e.g. a worker unregistering in between) can abort this whole
  // batch; treat that as "no fresh data available" rather than surfacing an error to the caller.
  if (!results) return [];

  const roleByNodeId = new Map<number, number>();
  roleNodeIds.forEach((nodeId, index) => {
    roleByNodeId.set(nodeId, parseU8(results[nodes.length * 3 + index]));
  });

  return nodes.map(({ nodeId }, index) => {
    const base = index * 3;
    const active = parseBool(results[base]);
    const endpoint = parseUtf8Vector(results[base + 1]);
    const updatedAtMs = Number(parseU64(results[base + 2]));
    const role = roleByNodeId.get(nodeId) ?? ROLE_NONE;
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
  const nodes = await fetchExistingNodeIds(config, nextNodeId);
  const records = await fetchWorkerRecords(
    config,
    nodes.filter((n) => n.hasRole),
  );
  const now = Date.now();
  return records
    .filter(
      (r) =>
        r.role === ROLE_ROUTER &&
        r.active &&
        now - r.updatedAtMs <= STALE_THRESHOLD_MS,
    )
    .map((r) => ({
      nodeId: r.nodeId,
      endpoint: r.endpoint,
      updatedAtMs: r.updatedAtMs,
    }));
}

export async function fetchAllWorkers(): Promise<WorkerRecord[]> {
  const config = loadChainConfig();
  const nextNodeId = await fetchNextNodeId(config);
  const nodes = await fetchExistingNodeIds(config, nextNodeId);
  return fetchWorkerRecords(config, nodes);
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
  const reachable = probes.filter(
    (p): p is { candidate: RouteCandidate; latencyMs: number } =>
      p.latencyMs !== null,
  );
  if (reachable.length === 0) return null;
  reachable.sort((a, b) => a.latencyMs - b.latencyMs);
  return reachable[0];
}

let _candidatesCache: {
  candidates: RouteCandidate[];
  fetchedAtMs: number;
} | null = null;

async function cachedCandidates(): Promise<RouteCandidate[]> {
  const now = Date.now();
  if (
    _candidatesCache &&
    now - _candidatesCache.fetchedAtMs < CANDIDATES_CACHE_TTL_MS
  ) {
    return _candidatesCache.candidates;
  }
  const candidates = await fetchActiveRouters();
  _candidatesCache = { candidates, fetchedAtMs: now };
  return candidates;
}

export async function getWorkingRoute(
  exclude: Set<string> = new Set(),
): Promise<string> {
  const override = process.env.NEXT_PUBLIC_ROUTES_URL;
  if (override && !exclude.has(override)) return override;

  let onChainCandidates: RouteCandidate[] = [];
  try {
    onChainCandidates = await cachedCandidates();
  } catch {
    onChainCandidates = [];
  }
  const candidates = onChainCandidates.filter((c) => !exclude.has(c.endpoint));
  const best = await pickBestRoute(candidates);
  if (!best)
    throw new Error("No reachable routes are currently registered on-chain");
  return best.candidate.endpoint;
}

export type SelectedRoute = {
  nodeId: string;
  endpoint: string;
  latencyMs: number;
};

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
  return {
    nodeId: best.candidate.nodeId,
    endpoint: best.candidate.endpoint,
    latencyMs: Math.round(best.latencyMs),
  };
}
