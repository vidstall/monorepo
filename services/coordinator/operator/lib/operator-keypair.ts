import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import path from "path";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { createPrivateKey, createPublicKey, generateKeyPairSync } from "crypto";

type OperatorState = {
  secretKey: string;
  nodeId: string | null;
  x25519Secret?: string;
};

function statePath(): string {
  if (process.env.COORDINATOR_OPERATOR_KEY_PATH) {
    return process.env.COORDINATOR_OPERATOR_KEY_PATH;
  }
  const instanceName = process.env.COORDINATOR_INSTANCE_NAME ?? "default";
  return path.resolve(
    process.cwd(),
    "..",
    "..",
    "..",
    "runtime",
    "coordinator",
    `${instanceName}.json`,
  );
}

function readState(filePath: string): OperatorState | null {
  if (!existsSync(filePath)) return null;
  const raw = JSON.parse(
    readFileSync(filePath, "utf-8"),
  ) as Partial<OperatorState>;
  if (!raw.secretKey) return null;
  return {
    secretKey: raw.secretKey,
    nodeId: raw.nodeId ?? null,
    x25519Secret: raw.x25519Secret,
  };
}

function writeState(filePath: string, state: OperatorState): void {
  mkdirSync(path.dirname(filePath), { recursive: true });
  writeFileSync(filePath, JSON.stringify(state, null, 2), { mode: 0o600 });
}

let _cached: { keypair: Ed25519Keypair; path: string } | null = null;

export function loadOperatorKeypair(): Ed25519Keypair {
  const filePath = statePath();
  if (_cached && _cached.path === filePath) return _cached.keypair;

  const existing = readState(filePath);
  if (existing) {
    if (!existing.x25519Secret) {
      const generated = generateKeyPairSync("x25519");
      existing.x25519Secret = generated.privateKey
        .export({ format: "der", type: "pkcs8" })
        .subarray(-32)
        .toString("base64");
      writeState(filePath, existing);
    }
    const keypair = Ed25519Keypair.fromSecretKey(existing.secretKey);
    _cached = { keypair, path: filePath };
    return keypair;
  }

  const keypair = Ed25519Keypair.generate();
  const generated = generateKeyPairSync("x25519");
  writeState(filePath, {
    secretKey: keypair.getSecretKey(),
    nodeId: null,
    x25519Secret: generated.privateKey
      .export({ format: "der", type: "pkcs8" })
      .subarray(-32)
      .toString("base64"),
  });
  _cached = { keypair, path: filePath };
  return keypair;
}

export function getPersistedNodeId(): string | null {
  const existing = readState(statePath());
  return existing?.nodeId ?? null;
}

export function persistNodeId(nodeId: string): void {
  const filePath = statePath();
  const keypair = loadOperatorKeypair();
  const existing = readState(filePath);
  writeState(filePath, {
    secretKey: keypair.getSecretKey(),
    nodeId,
    x25519Secret: existing?.x25519Secret,
  });
}

const X25519_PKCS8_PREFIX = Buffer.from(
  "302e020100300506032b656e04220420",
  "hex",
);

export function operatorX25519PublicKey(): Uint8Array {
  loadOperatorKeypair();
  const existing = readState(statePath());
  if (!existing?.x25519Secret)
    throw new Error("Missing operator X25519 secret");
  const privateKey = createPrivateKey({
    key: Buffer.concat([
      X25519_PKCS8_PREFIX,
      Buffer.from(existing.x25519Secret, "base64"),
    ]),
    format: "der",
    type: "pkcs8",
  });
  return createPublicKey(privateKey)
    .export({ format: "der", type: "spki" })
    .subarray(-32);
}
