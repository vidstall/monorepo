export function roomJoinChallenge(input: {
  rentalId: string;
  participantName: string;
  nonce: string;
  expiresAtMs: number;
}): Uint8Array {
  return new TextEncoder().encode(
    [
      "xaisen-room-join-v1",
      `expiresAtMs=${input.expiresAtMs}`,
      `nonce=${input.nonce}`,
      `participantName=${input.participantName}`,
      `rentalId=${input.rentalId}`,
    ].join("\n"),
  );
}

export function walletNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(18));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}
