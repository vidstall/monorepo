import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { bcs } from "@mysten/sui/bcs";

const ROLE_ROUTER = 2;
const SUI_COIN_TYPE = "0x2::sui::SUI";
const ZERO_SENDER =
  "0x0000000000000000000000000000000000000000000000000000000000000000";

const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

type Network = keyof typeof JSON_RPC_URLS;

export type PendingRoleProposal = {
  proposalId: string;
  nomineeNodeId: string;
  deadlineMs: number;
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

async function fetchNextProposalId(config: ChainConfig): Promise<number> {
  const results = await devInspect(config, (tx) => {
    tx.moveCall({
      target: moveTarget(config, "next_role_proposal_id"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [tx.object(config.registryObjectId)],
    });
  });
  if (!results?.[0]) throw new Error("failed to read next_role_proposal_id from registry");
  return Number(parseU64(results[0]));
}

/** Same PTB-abort constraint as route-discovery: check existence first (non-asserting), then
 * fetch details only for ids confirmed to exist. */
async function fetchExistingProposalIds(config: ChainConfig, nextProposalId: number): Promise<number[]> {
  if (nextProposalId <= 1) return [];
  const results = await devInspect(config, (tx) => {
    for (let proposalId = 1; proposalId < nextProposalId; proposalId++) {
      tx.moveCall({
        target: moveTarget(config, "role_proposal_exists"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), tx.pure.u64(BigInt(proposalId))],
      });
    }
  });
  if (!results) return [];

  const existing: number[] = [];
  for (let proposalId = 1; proposalId < nextProposalId; proposalId++) {
    if (parseBool(results[proposalId - 1])) existing.push(proposalId);
  }
  return existing;
}

async function fetchProposalDetails(
  config: ChainConfig,
  proposalIds: number[],
): Promise<PendingRoleProposal[]> {
  if (proposalIds.length === 0) return [];
  const results = await devInspect(config, (tx) => {
    for (const proposalId of proposalIds) {
      const id = tx.pure.u64(BigInt(proposalId));
      tx.moveCall({
        target: moveTarget(config, "role_proposal_role"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
      tx.moveCall({
        target: moveTarget(config, "role_proposal_finalized"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
      tx.moveCall({
        target: moveTarget(config, "role_proposal_nominee_node_id"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
      tx.moveCall({
        target: moveTarget(config, "role_proposal_deadline_ms"),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), id],
      });
    }
  });
  if (!results) return [];

  const pending: PendingRoleProposal[] = [];
  proposalIds.forEach((proposalId, index) => {
    const base = index * 4;
    const role = parseU8(results[base]);
    const finalized = parseBool(results[base + 1]);
    const nomineeNodeId = parseU64(results[base + 2]);
    const deadlineMs = Number(parseU64(results[base + 3]));
    if (role !== ROLE_ROUTER || finalized) return;
    pending.push({ proposalId: String(proposalId), nomineeNodeId: String(nomineeNodeId), deadlineMs });
  });
  return pending;
}

export async function fetchPendingRouterProposals(): Promise<PendingRoleProposal[]> {
  const config = loadChainConfig();
  const nextProposalId = await fetchNextProposalId(config);
  const existingIds = await fetchExistingProposalIds(config, nextProposalId);
  return fetchProposalDetails(config, existingIds);
}
