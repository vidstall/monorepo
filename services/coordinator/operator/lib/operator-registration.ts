import { createHash } from "crypto";
import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import type { SuiTransactionBlockResponse } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { loadContractConfig } from "./contract-config.js";
import {
  JSON_RPC_URLS,
  SUI_CLOCK_OBJECT_ID,
  SUI_COIN_TYPE,
  moveTarget,
} from "./contract-move-shared.js";
import {
  getPersistedNodeId,
  loadOperatorKeypair,
  persistNodeId,
  operatorX25519PublicKey,
} from "./operator-keypair.js";

// Keep in sync with services/contract/sources/stores/role_vote_store.move.
const ROLE_COORDINATOR = 1;

function client(): SuiJsonRpcClient {
  const config = loadContractConfig();
  return new SuiJsonRpcClient({
    network: config.network as never,
    url: JSON_RPC_URLS[config.network],
  });
}

function metadataBytes(value: string): number[] {
  return Array.from(new TextEncoder().encode(value));
}

function metadataHash(value: string): number[] {
  return Array.from(createHash("sha256").update(value).digest());
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value)
    throw new Error(`${name} is required for coordinator self-registration`);
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
  const internalAddress = requireEnv("COORDINATOR_INTERNAL_ADDRESS");
  const priceMist = BigInt(
    process.env.COORDINATOR_PRICE_PER_RENTAL_MIST ?? "1",
  );
  const stakeMist = BigInt(process.env.COORDINATOR_STAKE_MIST ?? "1000");
  const c = client();

  const tx = new Transaction();
  tx.setSender(keypair.toSuiAddress());
  tx.moveCall({
    target: moveTarget("register_worker"),
    typeArguments: [SUI_COIN_TYPE],
    arguments: [
      tx.object(config.registryObjectId),
      tx.pure.vector("u8", metadataBytes(internalAddress)),
      tx.pure.vector("u8", metadataHash(internalAddress)),
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

async function proposeSelfAsCoordinator(nodeId: string): Promise<void> {
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
      tx.pure.u8(ROLE_COORDINATOR),
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

async function updateNodeProfile(nodeId: string): Promise<void> {
  const config = loadContractConfig();
  const keypair = loadOperatorKeypair();
  const internalAddress = requireEnv("COORDINATOR_INTERNAL_ADDRESS");
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
      tx.pure.vector("u8", metadataBytes(internalAddress)),
      tx.pure.vector(
        "u8",
        metadataBytes(process.env.COORDINATOR_REGION ?? "global"),
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
  const { bcs } = await import("@mysten/sui/bcs");
  return new TextDecoder().decode(
    bcs.byteVector().parse(new Uint8Array(bytes)),
  );
}

async function updateMetadata(
  nodeId: string,
  internalAddress: string,
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
      tx.pure.vector("u8", metadataBytes(internalAddress)),
      tx.pure.vector("u8", metadataHash(internalAddress)),
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

let _heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let _nodeId: string | null = null;

export async function bootstrapOperator(): Promise<void> {
  try {
    const keypair = loadOperatorKeypair();
    console.log(`[coordinator] operator address: ${keypair.toSuiAddress()}`);

    let nodeId = getPersistedNodeId();
    if (!nodeId) {
      console.log(
        "[coordinator] no persisted node_id; registering as a new worker...",
      );
      nodeId = await registerWorker();
      persistNodeId(nodeId);
      console.log(
        `[coordinator] registered as node_id=${nodeId}; self-nominating for ROLE_COORDINATOR`,
      );
      await proposeSelfAsCoordinator(nodeId);
    } else {
      const internalAddress = requireEnv("COORDINATOR_INTERNAL_ADDRESS");
      if ((await currentMetadata(nodeId)) !== internalAddress) {
        console.log(
          `[coordinator] internal address changed; updating metadata for node_id=${nodeId}`,
        );
        await updateMetadata(nodeId, internalAddress);
      }
      console.log(
        `[coordinator] found persisted node_id=${nodeId}; marking active`,
      );
      await setActive(nodeId, true);
    }

    _nodeId = nodeId;
    await updateNodeProfile(nodeId);

    const intervalMs = Number(
      process.env.COORDINATOR_HEARTBEAT_INTERVAL_MS ?? 5 * 60 * 1000,
    );
    _heartbeatTimer = setInterval(() => {
      if (!_nodeId) return;
      heartbeat(_nodeId).catch((err) =>
        console.error("[coordinator] heartbeat failed", err),
      );
    }, intervalMs);

    const shutdown = () => {
      if (_heartbeatTimer) clearInterval(_heartbeatTimer);
      if (_nodeId) {
        setActive(_nodeId, false)
          .catch((err) =>
            console.error(
              "[coordinator] failed to mark inactive on shutdown",
              err,
            ),
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
      "[coordinator] operator bootstrap failed; continuing without on-chain registration",
      error,
    );
  }
}
