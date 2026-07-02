import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { bcs } from "@mysten/sui/bcs";
import { loadContractConfig } from "@/lib/contract-config";
import {
  JSON_RPC_URLS,
  SUI_COIN_TYPE,
  moveTarget,
} from "@/lib/contract-move-shared";

export async function queryRentalCapacity(
  rentalId: number,
): Promise<number | null> {
  try {
    const config = loadContractConfig();
    const client = new SuiJsonRpcClient({
      network: config.network as never,
      url: JSON_RPC_URLS[config.network],
    });
    const tx = new Transaction();
    tx.moveCall({
      target: moveTarget("rental_capacity"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        tx.object(config.registryObjectId),
        tx.pure.u64(BigInt(rentalId)),
      ],
    });
    const result = await client.devInspectTransactionBlock({
      transactionBlock: tx,
      sender:
        "0x0000000000000000000000000000000000000000000000000000000000000000",
    });
    if (result.results?.[0]?.returnValues?.[0]) {
      const [bytes] = result.results[0].returnValues[0];
      return Number(bcs.u64().parse(new Uint8Array(bytes)));
    }
    return null;
  } catch {
    return null;
  }
}

export async function queryRentalPayment(
  rentalId: bigint,
): Promise<bigint | null> {
  try {
    const config = loadContractConfig();
    const client = new SuiJsonRpcClient({
      network: config.network as never,
      url: JSON_RPC_URLS[config.network],
    });
    const tx = new Transaction();
    tx.moveCall({
      target: moveTarget("rental_payment_amount"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [tx.object(config.registryObjectId), tx.pure.u64(rentalId)],
    });
    const result = await client.devInspectTransactionBlock({
      transactionBlock: tx,
      sender:
        "0x0000000000000000000000000000000000000000000000000000000000000000",
    });
    const raw = result.results?.[0]?.returnValues?.[0]?.[0];
    return raw ? BigInt(bcs.u64().parse(new Uint8Array(raw))) : null;
  } catch {
    return null;
  }
}

export async function queryRentalClient(
  rentalId: bigint,
): Promise<string | null> {
  try {
    const config = loadContractConfig();
    const client = new SuiJsonRpcClient({
      network: config.network as never,
      url: JSON_RPC_URLS[config.network],
    });
    const tx = new Transaction();
    tx.moveCall({
      target: moveTarget("rental_client"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [tx.object(config.registryObjectId), tx.pure.u64(rentalId)],
    });
    const result = await client.devInspectTransactionBlock({
      transactionBlock: tx,
      sender:
        "0x0000000000000000000000000000000000000000000000000000000000000000",
    });
    const raw = result.results?.[0]?.returnValues?.[0]?.[0];
    return raw ? bcs.Address.parse(new Uint8Array(raw)) : null;
  } catch {
    return null;
  }
}

export async function queryRoutedAssignment(rentalId: bigint): Promise<{
  routerNodeId: string;
  mediaNodeId: string;
  clusterId: string;
  revision: number;
} | null> {
  try {
    const config = loadContractConfig();
    const client = new SuiJsonRpcClient({
      network: config.network as never,
      url: JSON_RPC_URLS[config.network],
    });
    const existsTx = new Transaction();
    existsTx.moveCall({
      target: moveTarget("routed_assignment_exists"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        existsTx.object(config.registryObjectId),
        existsTx.pure.u64(rentalId),
      ],
    });
    const existsResult = await client.devInspectTransactionBlock({
      transactionBlock: existsTx,
      sender: "0x0",
    });
    const existsRaw = existsResult.results?.[0]?.returnValues?.[0]?.[0];
    if (!existsRaw || !bcs.bool().parse(new Uint8Array(existsRaw))) return null;

    const tx = new Transaction();
    for (const name of [
      "routed_assignment_router",
      "routed_assignment_media",
      "routed_assignment_cluster",
      "routed_assignment_revision",
    ]) {
      tx.moveCall({
        target: moveTarget(name),
        typeArguments: [SUI_COIN_TYPE],
        arguments: [tx.object(config.registryObjectId), tx.pure.u64(rentalId)],
      });
    }
    const result = await client.devInspectTransactionBlock({
      transactionBlock: tx,
      sender: "0x0",
    });
    const values = result.results?.map((item) => item.returnValues?.[0]?.[0]);
    if (!values || values.some((value) => !value)) return null;
    const parsed = values.map((value) =>
      BigInt(bcs.u64().parse(new Uint8Array(value!))),
    );
    return {
      routerNodeId: String(parsed[0]),
      mediaNodeId: String(parsed[1]),
      clusterId: String(parsed[2]),
      revision: Number(parsed[3]),
    };
  } catch {
    return null;
  }
}
