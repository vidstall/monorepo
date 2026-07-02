import { verifyPersonalMessageSignature } from "@mysten/sui/verify";

export type WalletChallenge = {
  rentalId: string;
  participantName: string;
  nonce: string;
  expiresAtMs: number;
};

export function walletChallengeMessage(challenge: WalletChallenge): Uint8Array {
  return new TextEncoder().encode(
    [
      "xaisen-room-join-v1",
      `expiresAtMs=${challenge.expiresAtMs}`,
      `nonce=${challenge.nonce}`,
      `participantName=${challenge.participantName}`,
      `rentalId=${challenge.rentalId}`,
    ].join("\n"),
  );
}

export async function verifyWalletChallenge(
  challenge: WalletChallenge,
  signature: string,
  expectedAddress: string,
): Promise<void> {
  if (
    challenge.expiresAtMs < Date.now() ||
    challenge.expiresAtMs > Date.now() + 2 * 60_000
  ) {
    throw new Error("Wallet challenge is expired or too far in the future");
  }
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(challenge.nonce))
    throw new Error("Invalid wallet challenge nonce");
  await verifyPersonalMessageSignature(
    walletChallengeMessage(challenge),
    signature,
    { address: expectedAddress },
  );
}
