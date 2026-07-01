import { loadContractConfig } from "@/lib/contract-config";

export const SUI_COIN_TYPE = "0x2::sui::SUI";
export const SUI_CLOCK_OBJECT_ID = "0x6";

export const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

export function moveTarget(functionName: string): string {
  return `${loadContractConfig().packageId}::node_registry::${functionName}`;
}
