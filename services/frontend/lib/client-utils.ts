export function encodePassphrase(passphrase: string) {
  return encodeURIComponent(passphrase);
}

export function decodePassphrase(base64String: string) {
  return decodeURIComponent(base64String);
}

export function generateRoomId(): string {
  return `${randomString(4)}-${randomString(4)}`;
}

export function randomString(length: number): string {
  let result = '';
  const characters = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const charactersLength = characters.length;
  for (let i = 0; i < length; i++) {
    result += characters.charAt(Math.floor(Math.random() * charactersLength));
  }
  return result;
}

export function isLowPowerDevice() {
  return navigator.hardwareConcurrency < 6;
}

export function isMeetStaging() {
  return new URL(location.origin).host === 'meet.staging.livekit.io';
}

const _GRPC_URLS: Record<string, string> = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
};

export function getRoutesEndpoint(): string {
  return process.env.NEXT_PUBLIC_ROUTES_URL ?? "";
}

let _routesEndpointCache: Promise<string> | null = null;

export async function getRoutesEndpointAsync(): Promise<string> {
  const override = process.env.NEXT_PUBLIC_ROUTES_URL;
  if (override) return override;
  if (process.env.NODE_ENV !== "production") return "http://localhost:3001/api";

  if (!_routesEndpointCache) {
    _routesEndpointCache = (async () => {
      const registryObjectId = process.env.NEXT_PUBLIC_REGISTRY_OBJECT_ID;
      const network = (process.env.NEXT_PUBLIC_SUI_NETWORK ?? "devnet") as keyof typeof _GRPC_URLS;
      if (!registryObjectId) throw new Error("NEXT_PUBLIC_REGISTRY_OBJECT_ID not set");
      const { SuiGrpcClient } = await import("@mysten/sui/grpc");
      const client = new SuiGrpcClient({ network, baseUrl: _GRPC_URLS[network] });
      const obj = await client.getObject({ objectId: registryObjectId, include: { json: true } });
      const fields = (obj.object as { json?: Record<string, string> } | null)?.json ?? null;
      const endpoint = fields?.coordinator_endpoint;
      if (!endpoint) throw new Error("coordinator_endpoint not set on-chain");
      return endpoint;
    })();
  }
  return _routesEndpointCache;
}
