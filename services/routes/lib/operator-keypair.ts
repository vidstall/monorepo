import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import path from "path";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";

type OperatorState = {
  secretKey: string;
  nodeId: string | null;
};

function statePath(): string {
  if (process.env.ROUTES_OPERATOR_KEY_PATH) {
    return process.env.ROUTES_OPERATOR_KEY_PATH;
  }
  const instanceName = process.env.ROUTES_INSTANCE_NAME ?? "default";
  return path.resolve(
    process.cwd(),
    "..",
    "..",
    "runtime",
    "routes",
    `${instanceName}.json`,
  );
}

function readState(filePath: string): OperatorState | null {
  if (!existsSync(filePath)) return null;
  const raw = JSON.parse(readFileSync(filePath, "utf-8")) as Partial<OperatorState>;
  if (!raw.secretKey) return null;
  return { secretKey: raw.secretKey, nodeId: raw.nodeId ?? null };
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
    const keypair = Ed25519Keypair.fromSecretKey(existing.secretKey);
    _cached = { keypair, path: filePath };
    return keypair;
  }

  const keypair = Ed25519Keypair.generate();
  writeState(filePath, { secretKey: keypair.getSecretKey(), nodeId: null });
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
  writeState(filePath, { secretKey: keypair.getSecretKey(), nodeId });
}
