import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { loadContractConfig } from "@/lib/contract-config";
import {
  JSON_RPC_URLS,
  SUI_CLOCK_OBJECT_ID,
  SUI_COIN_TYPE,
  moveTarget,
} from "@/lib/contract-move-shared";

type TransactionAction =
  | "register-worker"
  | "hire-worker"
  | "complete-rental"
  | "cancel-rental"
  | "withdraw-stake"
  | "order-room"
  | "cast-room-vote"
  | "propose-role"
  | "cast-role-vote"
  | "cancel-expired-order"
  | "set-node-profile"
  | "register-media-cluster"
  | "add-media-cluster-member";

type BuildResult = {
  network: string;
  packageId: string;
  registryObjectId: string;
  txBytes: string;
};

const MIN_ROOM_PAYMENT_MIST = 10_000_000n;

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
        tx.pure.u64(requireU64(body.capacity, "capacity")),
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
    return;
  }

  if (action === "order-room") {
    const paymentMist = requireU64(body.paymentMist, "paymentMist");
    if (paymentMist < MIN_ROOM_PAYMENT_MIST) {
      throw new Error(`paymentMist must be at least ${MIN_ROOM_PAYMENT_MIST}`);
    }
    tx.moveCall({
      target: moveTarget("order_room"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.vector(
          "u8",
          metadataBytes(requireString(body.roomName, "roomName")),
        ),
        tx.pure.u64(requireU64(body.capacity, "capacity")),
        tx.coin({ balance: paymentMist }),
        clock,
      ],
    });
    return;
  }

  if (action === "cast-room-vote") {
    tx.moveCall({
      target: moveTarget("cast_room_vote"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.voterNodeId, "voterNodeId")),
        tx.pure.u64(requireU64(body.rentalId, "rentalId")),
        tx.pure.u64(requireU64(body.nomineeNodeId, "nomineeNodeId")),
        clock,
      ],
    });
    return;
  }

  if (action === "propose-role") {
    tx.moveCall({
      target: moveTarget("propose_role"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.proposerNodeId, "proposerNodeId")),
        tx.pure.u64(requireU64(body.nomineeNodeId, "nomineeNodeId")),
        tx.pure.u8(Number(requireU64(body.role, "role"))),
        clock,
      ],
    });
    return;
  }

  if (action === "cast-role-vote") {
    tx.moveCall({
      target: moveTarget("cast_role_vote"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.voterNodeId, "voterNodeId")),
        tx.pure.u64(requireU64(body.proposalId, "proposalId")),
        clock,
      ],
    });
    return;
  }

  if (action === "cancel-expired-order") {
    tx.moveCall({
      target: moveTarget("cancel_expired_order"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.rentalId, "rentalId")),
        clock,
      ],
    });
    return;
  }

  if (action === "set-node-profile") {
    const publicKey = Buffer.from(
      requireString(body.x25519PublicKey, "x25519PublicKey"),
      "base64",
    );
    if (publicKey.length !== 32)
      throw new Error("x25519PublicKey must decode to 32 bytes");
    tx.moveCall({
      target: moveTarget("set_node_profile"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.nodeId, "nodeId")),
        tx.pure.vector("u8", Array.from(publicKey)),
        tx.pure.vector(
          "u8",
          metadataBytes(requireString(body.brokerEndpoint, "brokerEndpoint")),
        ),
        tx.pure.vector(
          "u8",
          metadataBytes(requireString(body.region, "region")),
        ),
        tx.pure.u64(requireU64(body.clusterId ?? "0", "clusterId")),
      ],
    });
    return;
  }

  if (action === "register-media-cluster") {
    tx.moveCall({
      target: moveTarget("register_media_cluster"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.ownerNodeId, "ownerNodeId")),
        tx.pure.vector(
          "u8",
          metadataBytes(requireString(body.clientUrl, "clientUrl")),
        ),
        tx.pure.u64(requireU64(body.pricePerRentalMist, "pricePerRentalMist")),
      ],
    });
    return;
  }

  if (action === "add-media-cluster-member") {
    tx.moveCall({
      target: moveTarget("add_media_cluster_member"),
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        registry,
        tx.pure.u64(requireU64(body.clusterId, "clusterId")),
        tx.pure.u64(requireU64(body.nodeId, "nodeId")),
      ],
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
