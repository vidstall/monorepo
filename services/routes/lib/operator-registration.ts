import { createHash } from "crypto";
import { bcs } from "@mysten/sui/bcs";
import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import type { SuiTransactionBlockResponse } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { loadContractConfig } from "@/lib/contract-config";
import {
  JSON_RPC_URLS,
  SUI_CLOCK_OBJECT_ID,
  SUI_COIN_TYPE,
  moveTarget,
} from "@/lib/contract-move-shared";
import {
  getPersistedNodeId,
  loadOperatorKeypair,
  persistNodeId,
  operatorX25519PublicKey,
} from "@/lib/operator-keypair";

const ROLE_ROUTER = 2;

function client(): SuiJsonRpcClient {
  const config = loadContractConfig();
  return new SuiJsonRpcClient({
    network: config.network as never,
    url: JSON_RPC_URLS[config.network],
  });
}

function metadataBytes(url: string): number[] {
  return Array.from(new TextEncoder().encode(url));
}

function metadataHash(url: string): number[] {
  return Array.from(createHash("sha256").update(url).digest());
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value)
    throw new Error(`${name} is required for routes self-registration`);
  return value;
}

function assertSuccess(result: SuiTransactionBlockResponse): void {
  if (result.effects && result.effects.status.status !== "success") {
    throw new Error(
      `Transaction failed: ${result.effects.status.error ?? "unknown error"}`,
    );
  }
}

async function registerWorker(): Promise<string> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const publicUrl = requireEnv("ROUTES_PUBLIC_URL");
  const priceMist = BigInt(process.env.ROUTES_PRICE_PER_RENTAL_MIST ?? "1");
  const stakeMist = BigInt(process.env.ROUTES_STAKE_MIST ?? "1000");
  const c = client();

  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("register_worker"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.vector("u8", metadataBytes(publicUrl)),
      tx.pure.vector("u8", metadataHash(publicUrl)),
      tx.pure.u64(priceMist),
      tx.coin({ balance: stakeMist }),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });

  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEvents: true, showEffects: true },
  });

  assertSuccess(result);

  const event = result.events?.find((e) =>
    e.type.endsWith("::worker_events::WorkerRegistered"),
  );
  const nodeId = (event?.parsedJson as Record<string, unknown> | undefined)
    ?.node_id;
  if (nodeId === undefined || nodeId === null) {
    throw new Error(
      "register_worker succeeded but node_id could not be parsed from events",
    );
  }
  return String(nodeId);
}

async function proposeSelfAsRouter(nodeId: string): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();

  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("propose_role"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(nodeId)),
      tx.pure.u64(BigInt(nodeId)),
      tx.pure.u8(ROLE_ROUTER),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });

  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);
}

async function setActive(nodeId: string, active: boolean): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();

  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("set_worker_active"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(nodeId)),
      tx.pure.bool(active),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });

  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);
}

async function updateRouterProfile(nodeId: string): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const publicUrl = requireEnv("ROUTES_PUBLIC_URL");
  const brokerEndpoint = publicUrl.replace(/\/api\/?$/, "");
  const c = client();
  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("set_node_profile"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(nodeId)),
      tx.pure.vector("u8", Array.from(operatorX25519PublicKey())),
      tx.pure.vector("u8", metadataBytes(brokerEndpoint)),
      tx.pure.vector(
        "u8",
        metadataBytes(process.env.ROUTES_REGION ?? "global"),
      ),
      tx.pure.u64(0n),
    ],
  });
  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);
}

async function setRoutesEndpoint(publicUrl: string): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();
  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("set_routes_endpoint"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.vector("u8", metadataBytes(publicUrl)),
    ],
  });
  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);
}

async function currentMetadata(nodeId: string): Promise<string | null> {
  const config = loadContractConfig();
  const c = client();
  const tx = new Transaction();
  tx.moveCall({
    target: moveTarget("worker_metadata_uri"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(nodeId)),
    ],
  });
  const result = await c.devInspectTransactionBlock({
    transactionBlock: tx,
    sender:
      "0x0000000000000000000000000000000000000000000000000000000000000000",
  });
  const bytes = result.results?.[0]?.returnValues?.[0]?.[0];
  if (!bytes) return null;
  return new TextDecoder().decode(
    bcs.byteVector().parse(new Uint8Array(bytes)),
  );
}

async function updateMetadata(
  nodeId: string,
  publicUrl: string,
): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();
  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("update_worker_metadata"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(nodeId)),
      tx.pure.vector("u8", metadataBytes(publicUrl)),
      tx.pure.vector("u8", metadataHash(publicUrl)),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });
  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);
}

async function heartbeat(nodeId: string): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();

  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("heartbeat_worker"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(nodeId)),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });

  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);
}

// Places a real (if minimal) on-chain room order paid for by routes' own
// operator wallet, not the participant's. Used for free "Join a Room"
// requests: the media node's broker hard-requires an on-chain-verified paid
// assignment for every token it issues (see verifyAssignment in
// xaisen_broker.go), so there is no way to skip payment entirely - routes
// covers the discovered cluster's exact price on the participant's behalf
// so no wallet/signature is needed from them.
export async function orderRoomAsOperator(
  roomName: string,
  capacity: number,
  paymentMist: bigint,
): Promise<string> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();
  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("order_room"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.vector("u8", metadataBytes(roomName)),
      tx.pure.u64(BigInt(capacity)),
      tx.coin({ balance: paymentMist }),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });
  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEvents: true, showEffects: true },
  });
  assertSuccess(result);

  const event = result.events?.find((e) =>
    e.type.endsWith("::governance_events::RoomOrderCreated"),
  );
  const rentalId = (event?.parsedJson as Record<string, unknown> | undefined)
    ?.rental_id;
  if (rentalId === undefined || rentalId === null) {
    throw new Error(
      "order_room succeeded but rental_id could not be parsed from events",
    );
  }
  return String(rentalId);
}

export async function assignRoutedOrder(
  routerNodeId: string,
  mediaNodeId: string,
  clusterId: string,
  rentalId: string,
): Promise<{ digest: string; revision: number }> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const c = client();
  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("assign_routed_order"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.u64(BigInt(routerNodeId)),
      tx.pure.u64(BigInt(mediaNodeId)),
      tx.pure.u64(BigInt(clusterId)),
      tx.pure.u64(BigInt(rentalId)),
      tx.object(SUI_CLOCK_OBJECT_ID),
    ],
  });
  const result = await c.signAndExecuteTransaction({
    transaction: tx,
    signer: keypair,
    options: { showEffects: true },
  });
  assertSuccess(result);

  const inspectTx = new Transaction();
  inspectTx.moveCall({
    target: moveTarget("routed_assignment_revision"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      inspectTx.object(config.registryObjectId),
      inspectTx.pure.u64(BigInt(rentalId)),
    ],
  });
  const inspected = await c.devInspectTransactionBlock({
    transactionBlock: inspectTx,
    sender: keypair.toSuiAddress(),
  });
  const raw = inspected.results?.[0]?.returnValues?.[0]?.[0];
  const revision = raw ? Number(bcs.u64().parse(new Uint8Array(raw))) : 1;
  return { digest: result.digest, revision };
}

let _heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let _nodeId: string | null = null;

export async function bootstrapOperator(): Promise<void> {
  try {
    const keypair = loadOperatorKeypair();
    console.log(`[routes] operator address: ${keypair.toSuiAddress()}`);

    let nodeId = getPersistedNodeId();
    if (!nodeId) {
      console.log(
        "[routes] no persisted node_id; registering as a new worker...",
      );
      nodeId = await registerWorker();
      persistNodeId(nodeId);
      console.log(
        `[routes] registered as node_id=${nodeId}; self-nominating for ROLE_ROUTER`,
      );
      await proposeSelfAsRouter(nodeId);
    } else {
      const publicUrl = requireEnv("ROUTES_PUBLIC_URL");
      if ((await currentMetadata(nodeId)) !== publicUrl) {
        console.log(
          `[routes] public URL changed; updating metadata for node_id=${nodeId}`,
        );
        await updateMetadata(nodeId, publicUrl);
      }
      console.log(`[routes] found persisted node_id=${nodeId}; marking active`);
      await setActive(nodeId, true);
    }

    _nodeId = nodeId;
    await updateRouterProfile(nodeId);
    console.log("[routes] publishing routes_endpoint...");
    await setRoutesEndpoint(requireEnv("ROUTES_PUBLIC_URL"));
    const intervalMs = Number(
      process.env.ROUTES_HEARTBEAT_INTERVAL_MS ?? 5 * 60 * 1000,
    );
    _heartbeatTimer = setInterval(() => {
      if (!_nodeId) return;
      heartbeat(_nodeId).catch((err) =>
        console.error("[routes] heartbeat failed", err),
      );
    }, intervalMs);

    const shutdown = () => {
      if (_heartbeatTimer) clearInterval(_heartbeatTimer);
      if (_nodeId) {
        setActive(_nodeId, false)
          .catch((err) =>
            console.error("[routes] failed to mark inactive on shutdown", err),
          )
          .finally(() => process.exit(0));
      } else {
        process.exit(0);
      }
    };
    process.once("SIGTERM", shutdown);
    process.once("SIGINT", shutdown);
  } catch (error) {
    console.error(
      "[routes] operator bootstrap failed; continuing without on-chain registration",
      error,
    );
  }
}
