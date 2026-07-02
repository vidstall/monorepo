import { loadContractConfig } from "@/lib/contract-config";

export const SUI_COIN_TYPE = "0x2::sui::SUI";
export const SUI_CLOCK_OBJECT_ID = "0x6";

export const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

// Maps each Move function name to the module that owns it post-modularization
// (the contract used to be a single `node_registry` module; it was split into
// per-domain modules and this map keeps the client in sync with that layout).
const FUNCTION_MODULES: Record<string, string> = {
  create_registry: "registry",
  set_coordinator_endpoint: "registry",
  coordinator_endpoint: "registry",

  register_worker: "workers",
  update_worker_metadata: "workers",
  set_worker_active: "workers",
  heartbeat_worker: "workers",
  update_worker_price: "workers",
  unregister_worker: "workers",
  withdraw_worker_stake: "workers",

  node_exists: "workers",
  node_count: "workers",
  next_node_id: "workers",
  active_worker_count: "workers",
  worker_owner: "workers",
  worker_active: "workers",
  worker_rentable: "workers",
  worker_price_per_rental: "workers",
  worker_stake_value: "workers",
  worker_active_rental_id: "workers",
  worker_metadata_uri: "workers",
  worker_metadata_hash: "workers",
  worker_created_at_ms: "workers",
  worker_updated_at_ms: "workers",

  propose_role: "role_governance",
  cast_role_vote: "role_governance",
  next_role_proposal_id: "role_governance",
  has_worker_role: "role_governance",
  worker_role: "role_governance",
  role_proposal_exists: "role_governance",
  role_proposal_role: "role_governance",
  role_proposal_nominee_node_id: "role_governance",
  role_proposal_deadline_ms: "role_governance",
  role_proposal_finalized: "role_governance",

  set_node_profile: "media_routing",
  register_media_cluster: "media_routing",
  add_media_cluster_member: "media_routing",
  set_media_cluster_active: "media_routing",
  assign_routed_order: "media_routing",
  has_node_profile: "media_routing",
  node_x25519_public_key: "media_routing",
  node_broker_endpoint: "media_routing",
  node_region: "media_routing",
  node_cluster_id: "media_routing",
  media_cluster_exists: "media_routing",
  media_cluster_client_url: "media_routing",
  media_cluster_price: "media_routing",
  media_cluster_active: "media_routing",
  routed_assignment_exists: "media_routing",
  routed_assignment_router: "media_routing",
  routed_assignment_cluster: "media_routing",
  routed_assignment_media: "media_routing",
  routed_assignment_revision: "media_routing",

  hire_worker: "rentals",
  complete_rental: "rentals",
  cancel_rental: "rentals",
  rental_capacity: "rentals",
  rental_payment_amount: "rentals",
  rental_client: "rentals",

  order_room: "room_governance",
  cast_room_vote: "room_governance",
  cancel_expired_order: "room_governance",
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
