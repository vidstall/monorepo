import { bcs } from "@mysten/sui/bcs";
import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { loadContractConfig } from "@/lib/contract-config";
import {
  JSON_RPC_URLS,
  SUI_COIN_TYPE,
  moveTarget,
} from "@/lib/contract-move-shared";
import type { MediaCandidate } from "@/lib/media-protocol";

const ROLE_SFU = 0;

function client() {
  const config = loadContractConfig();
  return new SuiJsonRpcClient({
    network: config.network as never,
    url: JSON_RPC_URLS[config.network],
  });
}

async function inspect(calls: (tx: Transaction) => void) {
  const tx = new Transaction();
  calls(tx);
  const result = await client().devInspectTransactionBlock({
    transactionBlock: tx,
    sender:
      "0x0000000000000000000000000000000000000000000000000000000000000000",
  });
  if (result.effects.status.status !== "success")
    throw new Error(result.effects.status.error ?? "Media discovery failed");
  return result.results ?? [];
}

function bytes(
  result: Awaited<ReturnType<typeof inspect>>[number],
): Uint8Array {
  const value = result.returnValues?.[0]?.[0];
  if (!value) throw new Error("Missing contract return value");
  return new Uint8Array(value);
}

function parseU64(result: Awaited<ReturnType<typeof inspect>>[number]): bigint {
  return BigInt(bcs.u64().parse(bytes(result)));
}

function parseU8(result: Awaited<ReturnType<typeof inspect>>[number]): number {
  return bcs.u8().parse(bytes(result));
}

function parseBool(
  result: Awaited<ReturnType<typeof inspect>>[number],
): boolean {
  return bcs.bool().parse(bytes(result));
}

function parseVector(
  result: Awaited<ReturnType<typeof inspect>>[number],
): Uint8Array {
  return new Uint8Array(bcs.vector(bcs.u8()).parse(bytes(result)));
}

function text(result: Awaited<ReturnType<typeof inspect>>[number]): string {
  return new TextDecoder().decode(parseVector(result));
}

export async function discoverMediaCandidates(): Promise<MediaCandidate[]> {
  const config = loadContractConfig();
  const registry = config.registryObjectId;
  const [nextResult] = await inspect((tx) => {
    tx.moveCall({
      target: moveTarget("next_node_id"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [tx.object(registry)],
    });
  });
  const nextNodeId = Number(parseU64(nextResult));
  const candidates: MediaCandidate[] = [];

  for (let nodeId = 1; nodeId < nextNodeId; nodeId += 1) {
    try {
      const first = await inspect((tx) => {
        const id = tx.pure.u64(BigInt(nodeId));
        for (const name of [
          "worker_role",
          "worker_active",
          "has_node_profile",
        ] as const) {
          tx.moveCall({
            target: moveTarget(name),
            typeArguments: [SUI_COIN_TYPE],
            arguments: [tx.object(registry), id],
          });
        }
      });
      if (
        parseU8(first[0]) !== ROLE_SFU ||
        !parseBool(first[1]) ||
        !parseBool(first[2])
      )
        continue;

      const profile = await inspect((tx) => {
        const id = tx.pure.u64(BigInt(nodeId));
        for (const name of [
          "node_x25519_public_key",
          "node_broker_endpoint",
          "node_region",
          "node_cluster_id",
        ] as const) {
          tx.moveCall({
            target: moveTarget(name),
            typeArguments: [SUI_COIN_TYPE],
            arguments: [tx.object(registry), id],
          });
        }
      });
      const clusterId = parseU64(profile[3]);
      const cluster = await inspect((tx) => {
        const id = tx.pure.u64(clusterId);
        for (const name of [
          "media_cluster_active",
          "media_cluster_client_url",
          "media_cluster_price",
        ] as const) {
          tx.moveCall({
            target: moveTarget(name),
            typeArguments: [SUI_COIN_TYPE],
            arguments: [tx.object(registry), id],
          });
        }
      });
      if (!parseBool(cluster[0])) continue;
      candidates.push({
        nodeId: String(nodeId),
        clusterId: String(clusterId),
        x25519PublicKey: parseVector(profile[0]),
        brokerEndpoint: text(profile[1]).replace(/\/$/, ""),
        region: text(profile[2]),
        clientUrl: text(cluster[1]),
        priceMist: parseU64(cluster[2]),
      });
    } catch {
      // Sparse IDs and nodes without approved roles are expected.
    }
  }
  return candidates;
}
