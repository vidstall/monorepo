import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { loadContractConfig } from "@/lib/contract-config";

const SUI_COIN_TYPE = "0x2::sui::SUI";
const SUI_CLOCK_OBJECT_ID = "0x6";
const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

type TransactionAction =
  | "register-worker"
  | "hire-worker"
  | "complete-rental"
  | "cancel-rental"
  | "withdraw-stake";

type BuildResult = {
  network: string;
  packageId: string;
  registryObjectId: string;
  txBytes: string;
};

function requireString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Missing ${name}`);
  }
  return value.trim();
}

function requireU64(value: unknown, name: string): bigint {
  if (typeof value !== "string" && typeof value !== "number") {
    throw new Error(`Missing ${name}`);
  }

  const normalized = String(value);
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`${name} must be an unsigned integer string`);
  }
  return BigInt(normalized);
}

function metadataBytes(value: string): number[] {
  return Array.from(new TextEncoder().encode(value));
}

function hashBytes(value: unknown): number[] {
  const hash = requireString(value, "metadataHash");
  const normalized = hash.startsWith("0x") ? hash.slice(2) : hash;
  if (!/^[0-9a-fA-F]{64}$/.test(normalized)) {
    throw new Error("metadataHash must be a 32-byte hex string");
  }

  return Array.from(Buffer.from(normalized, "hex"));
}

function moveTarget(functionName: string): string {
  return `${loadContractConfig().packageId}::node_registry::${functionName}`;
}

function addMoveCall(
  tx: Transaction,
  action: TransactionAction,
  body: Record<string, unknown>,
) {
  const config = loadContractConfig();
  const registry = tx.object(config.registryObjectId);
  const clock = tx.object(SUI_CLOCK_OBJECT_ID);

  if (action === "register-worker") {
    tx.moveCall({
      target: moveTarget("register_worker"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.vector(
          "u8",
          metadataBytes(requireString(body.metadataUri, "metadataUri")),
        ),
        tx.pure.vector("u8", hashBytes(body.metadataHash)),
        tx.pure.u64(requireU64(body.pricePerRentalMist, "pricePerRentalMist")),
        tx.coin({ balance: requireU64(body.stakeMist, "stakeMist") }),
        clock,
      ],
    });
    return;
  }

  if (action === "hire-worker") {
    tx.moveCall({
      target: moveTarget("hire_worker"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.nodeId, "nodeId")),
        tx.pure.vector(
          "u8",
          metadataBytes(requireString(body.roomName, "roomName")),
        ),
        tx.coin({ balance: requireU64(body.paymentMist, "paymentMist") }),
        clock,
      ],
    });
    return;
  }

  if (action === "complete-rental") {
    tx.moveCall({
      target: moveTarget("complete_rental"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.rentalId, "rentalId")),
        clock,
      ],
    });
    return;
  }

  if (action === "cancel-rental") {
    tx.moveCall({
      target: moveTarget("cancel_rental"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [registry, tx.pure.u64(requireU64(body.rentalId, "rentalId"))],
    });
    return;
  }

  if (action === "withdraw-stake") {
    tx.moveCall({
      target: moveTarget("withdraw_worker_stake"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [registry, tx.pure.u64(requireU64(body.nodeId, "nodeId"))],
    });
  }
}

export async function buildContractTransaction(
  action: TransactionAction,
  body: Record<string, unknown>,
): Promise<BuildResult> {
  const config = loadContractConfig();
  const sender = requireString(body.sender, "sender");
  const client = new SuiJsonRpcClient({
    network: config.network as never,
    url: JSON_RPC_URLS[config.network],
  });
  const tx = new Transaction();

  tx.setSender(sender);
  addMoveCall(tx, action, body);

  const txBytes = await tx.build({ client });
  return {
    network: config.network,
    packageId: config.packageId,
    registryObjectId: config.registryObjectId,
    txBytes: Buffer.from(txBytes).toString("base64"),
  };
}
