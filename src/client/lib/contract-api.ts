import { getRoutesEndpoint } from "@/lib/client-utils";

export type ContractConfig = {
  network: string;
  packageId: string;
  registryObjectId: string;
  deployerAddress?: string;
  publishTxDigest?: string;
};

export type ContractTransactionAction =
  | "register-worker"
  | "hire-worker"
  | "complete-rental"
  | "cancel-rental"
  | "withdraw-stake";

export type ContractTransactionResponse = {
  network: string;
  packageId: string;
  registryObjectId: string;
  txBytes: string;
};

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  return text || `HTTP ${response.status}`;
}

export async function fetchContractConfig(): Promise<ContractConfig> {
  const response = await fetch(`${getRoutesEndpoint()}/contract/config`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function createContractTransaction(
  action: ContractTransactionAction,
  payload: Record<string, unknown>,
): Promise<ContractTransactionResponse> {
  const response = await fetch(
    `${getRoutesEndpoint()}/contract/transactions/${action}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}
