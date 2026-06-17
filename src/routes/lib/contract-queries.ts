import { SuiJsonRpcClient } from "@mysten/sui/jsonRpc";
import { Transaction } from "@mysten/sui/transactions";
import { bcs } from "@mysten/sui/bcs";
import { loadContractConfig } from "@/lib/contract-config";

const JSON_RPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

const SUI_COIN_TYPE = "0x2::sui::SUI";

export async function queryRentalCapacity(
  rentalId: number,
): Promise<number | null> {
  try {
    const config = loadContractConfig();
    const client = new SuiJsonRpcClient({
      network: config.network as never,
      url: JSON_RPC_URLS[config.network],
    });
    const tx = new Transaction();
    tx.moveCall({
      target: `${config.packageId}::node_registry::rental_capacity`,
      typeArguments: [SUI_COIN_TYPE],
      arguments: [
        tx.object(config.registryObjectId),
        tx.pure.u64(BigInt(rentalId)),
      ],
    });
    const result = await client.devInspectTransactionBlock({
      transactionBlock: tx,
      sender:
        "0x0000000000000000000000000000000000000000000000000000000000000000",
    });
    if (result.results?.[0]?.returnValues?.[0]) {
      const [bytes] = result.results[0].returnValues[0];
      return Number(bcs.u64().parse(new Uint8Array(bytes)));
    }
    return null;
  } catch {
    return null;
  }
}
