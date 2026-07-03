import { loadContractConfig } from "./contract-config.js";

export const SUI_COIN_TYPE = "0x2::sui::SUI";
export const SUI_CLOCK_OBJECT_ID = "0x6";

export const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

// Keep in sync with services/routes/lib/contract-move-shared.ts - only the
// subset of functions the coordinator operator actually calls.
const FUNCTION_MODULES: Record<string, string> = {
  register_worker: "workers",
  update_worker_metadata: "workers",
  set_worker_active: "workers",
  heartbeat_worker: "workers",
  worker_metadata_uri: "workers",

  propose_role: "role_governance",

  set_node_profile: "media_routing",
};

export function moveTarget(functionName: string): string {
  const module = FUNCTION_MODULES[functionName];
  if (!module) {
    throw new Error(
      `moveTarget: no module mapping for function "${functionName}"`,
    );
  }
  return `${loadContractConfig().packageId}::${module}::${functionName}`;
}
