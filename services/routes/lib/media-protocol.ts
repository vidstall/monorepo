import {
  createCipheriv,
  createDecipheriv,
  diffieHellman,
  generateKeyPairSync,
  hkdfSync,
  randomBytes,
  createPublicKey,
} from "crypto";
import { loadOperatorKeypair } from "@/lib/operator-keypair";

export type MediaCandidate = {
  nodeId: string;
  clusterId: string;
  brokerEndpoint: string;
  clientUrl: string;
  region: string;
  priceMist: bigint;
  x25519PublicKey: Uint8Array;
};

export type MediaHealth = {
  ready: boolean;
  nodeId: string;
  clusterId: string;
  timestampMs: number;
};

type Session = {
  id: string;
  key: Buffer;
  endpoint: string;
  expiresAt: number;
  counter: bigint;
};

const SESSION_TTL_MS = 30 * 60 * 1000;
const REKEY_AFTER_MS = 25 * 60 * 1000;
const sessions = new Map<string, Session>();
const X25519_SPKI_PREFIX = Buffer.from("302a300506032b656e032100", "hex");

function canonical(value: Record<string, string | number>): Uint8Array {
  return new TextEncoder().encode(
    Object.keys(value)
      .sort()
      .map((key) => `${key}=${value[key]}`)
      .join("\n"),
  );
}

export async function probeMedia(
  candidate: MediaCandidate,
): Promise<number | null> {
  const started = performance.now();
  try {
    const response = await fetch(
      `${candidate.brokerEndpoint}/xaisen/v1/health`,
      {
        signal: AbortSignal.timeout(2_000),
        cache: "no-store",
      },
    );
    if (!response.ok) return null;
    const health = (await response.json()) as MediaHealth;
    if (
      !health.ready ||
      health.nodeId !== candidate.nodeId ||
      health.clusterId !== candidate.clusterId
    )
      return null;
    if (Math.abs(Date.now() - health.timestampMs) > 60_000) return null;
    return performance.now() - started;
  } catch {
    return null;
  }
}

export async function selectBestMedia(
  candidates: MediaCandidate[],
): Promise<MediaCandidate> {
  const measured = (
    await Promise.all(
      candidates.map(async (candidate) => ({
        candidate,
        latency: await probeMedia(candidate),
      })),
    )
  ).filter(
    (item): item is { candidate: MediaCandidate; latency: number } =>
      item.latency !== null,
  );
  if (measured.length === 0)
    throw new Error("No healthy media cluster is available");

  const latencies = measured.map((item) => item.latency);
  const prices = measured.map((item) => Number(item.candidate.priceMist));
  const normalize = (value: number, values: number[]) => {
    const min = Math.min(...values);
    const max = Math.max(...values);
    return max === min ? 0 : (value - min) / (max - min);
  };
  measured.sort((a, b) => {
    const aScore =
      0.5 * normalize(a.latency, latencies) +
      0.5 * normalize(Number(a.candidate.priceMist), prices);
    const bScore =
      0.5 * normalize(b.latency, latencies) +
      0.5 * normalize(Number(b.candidate.priceMist), prices);
    return (
      aScore - bScore ||
      Number(a.candidate.priceMist - b.candidate.priceMist) ||
      a.latency - b.latency ||
      a.candidate.clusterId.localeCompare(b.candidate.clusterId)
    );
  });
  return measured[0].candidate;
}

async function establishSession(
  candidate: MediaCandidate,
  routerNodeId: string,
): Promise<Session> {
  const cacheKey = `${routerNodeId}:${candidate.nodeId}`;
  const cached = sessions.get(cacheKey);
  if (cached && cached.expiresAt - Date.now() > SESSION_TTL_MS - REKEY_AFTER_MS)
    return cached;

  const ephemeral = generateKeyPairSync("x25519");
  const ephemeralPublic = ephemeral.publicKey
    .export({ format: "der", type: "spki" })
    .subarray(-32);
  const nonce = randomBytes(24).toString("base64url");
  const issuedAtMs = Date.now();
  const unsigned = {
    ephemeralPublicKey: ephemeralPublic.toString("base64"),
    issuedAtMs,
    mediaNodeId: candidate.nodeId,
    nonce,
    routerNodeId,
  };
  const operator = loadOperatorKeypair();
  const signature = await operator.sign(canonical(unsigned));
  const response = await fetch(
    `${candidate.brokerEndpoint}/xaisen/v1/session`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...unsigned,
        routerPublicKey: Buffer.from(
          operator.getPublicKey().toRawBytes(),
        ).toString("base64"),
        signature: Buffer.from(signature).toString("base64"),
      }),
      signal: AbortSignal.timeout(5_000),
    },
  );
  if (!response.ok)
    throw new Error(`Media session rejected: ${await response.text()}`);
  const body = (await response.json()) as {
    sessionId: string;
    expiresAtMs: number;
  };
  const mediaPublic = createPublicKey({
    key: Buffer.concat([
      X25519_SPKI_PREFIX,
      Buffer.from(candidate.x25519PublicKey),
    ]),
    format: "der",
    type: "spki",
  });
  const shared = diffieHellman({
    privateKey: ephemeral.privateKey,
    publicKey: mediaPublic,
  });
  const key = Buffer.from(
    hkdfSync(
      "sha256",
      shared,
      Buffer.from(body.sessionId),
      canonical(unsigned),
      32,
    ),
  );
  const session = {
    id: body.sessionId,
    key,
    endpoint: candidate.brokerEndpoint,
    expiresAt: body.expiresAtMs,
    counter: 0n,
  };
  sessions.set(cacheKey, session);
  return session;
}

function nonceFor(counter: bigint): Buffer {
  const nonce = Buffer.alloc(12);
  nonce.writeBigUInt64BE(counter, 4);
  return nonce;
}

export async function requestParticipantToken(
  candidate: MediaCandidate,
  routerNodeId: string,
  request: Record<string, unknown>,
): Promise<{ participantToken: string; serverUrl: string }> {
  const session = await establishSession(candidate, routerNodeId);
  session.counter += 1n;
  const nonce = nonceFor(session.counter);
  const cipher = createCipheriv("chacha20-poly1305", session.key, nonce, {
    authTagLength: 16,
  });
  cipher.setAAD(Buffer.from(session.id), { plaintextLength: 0 });
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(request)),
    cipher.final(),
  ]);
  const response = await fetch(`${session.endpoint}/xaisen/v1/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: session.id,
      counter: session.counter.toString(),
      ciphertext: ciphertext.toString("base64"),
      tag: cipher.getAuthTag().toString("base64"),
    }),
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok)
    throw new Error(`Media token request failed: ${await response.text()}`);
  const envelope = (await response.json()) as {
    counter: string;
    ciphertext: string;
    tag: string;
  };
  const responseCounter = BigInt(envelope.counter);
  const decipher = createDecipheriv(
    "chacha20-poly1305",
    session.key,
    nonceFor(responseCounter),
    { authTagLength: 16 },
  );
  decipher.setAAD(Buffer.from(session.id), { plaintextLength: 0 });
  decipher.setAuthTag(Buffer.from(envelope.tag, "base64"));
  return JSON.parse(
    Buffer.concat([
      decipher.update(Buffer.from(envelope.ciphertext, "base64")),
      decipher.final(),
    ]).toString("utf8"),
  );
}
