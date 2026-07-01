import { existsSync, readFileSync } from "fs";
import path from "path";

export type ContractNetwork = "devnet" | "testnet" | "mainnet";

export type ContractConfig = {
  network: ContractNetwork;
  packageId: string;
  registryObjectId: string;
  upgradeCapId?: string;
  deployerAddress?: string;
  publishTxDigest?: string;
};

const CONTRACT_NETWORKS = new Set(["devnet", "testnet", "mainnet"]);

function parseEnvFile(filePath: string): Record<string, string> {
  if (!existsSync(filePath)) return {};

  const values: Record<string, string> = {};
  for (const rawLine of readFileSync(filePath, "utf-8").split(/\r?\n/)) {
    let line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.startsWith("export ")) line = line.slice("export ".length).trim();

    const separator = line.indexOf("=");
    if (separator === -1) continue;

    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if (
      value.length >= 2 &&
      ((value[0] === '"' && value[value.length - 1] === '"') ||
        (value[0] === "'" && value[value.length - 1] === "'"))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

function selectedNetwork(): ContractNetwork {
  const network =
    process.env.CONTRACT_NETWORK ?? process.env.SUI_NETWORK ?? "testnet";
  if (!CONTRACT_NETWORKS.has(network)) {
    throw new Error(`Unsupported contract network: ${network}`);
  }
  return network as ContractNetwork;
}

function contractEnvPath(network: ContractNetwork): string {
  if (process.env.CONTRACT_ENV_PATH) return process.env.CONTRACT_ENV_PATH;
  return path.resolve(
    process.cwd(),
    "..",
    "..",
    "secrets",
    "contract",
    `${network}.env`,
  );
}

export function loadContractConfig(): ContractConfig {
  const network = selectedNetwork();
  const fileValues = parseEnvFile(contractEnvPath(network));
  const values = { ...fileValues, ...process.env };

  const packageId = values.CONTRACT_PACKAGE_ID;
  const registryObjectId = values.CONTRACT_REGISTRY_OBJECT_ID;

  if (!packageId) {
    throw new Error(`Missing CONTRACT_PACKAGE_ID for ${network}`);
  }
  if (!registryObjectId) {
    throw new Error(
      `Missing CONTRACT_REGISTRY_OBJECT_ID for ${network}; run ./vidctl contract publish --env ${network} --yes`,
    );
  }

  return {
    network,
    packageId,
    registryObjectId,
    upgradeCapId: values.CONTRACT_UPGRADE_CAP_ID,
    deployerAddress: values.CONTRACT_DEPLOYER_ADDRESS,
    publishTxDigest: values.CONTRACT_PUBLISH_TX_DIGEST,
  };
}

export function getPublicContractConfig() {
  const config = loadContractConfig();
  return {
    network: config.network,
    packageId: config.packageId,
    registryObjectId: config.registryObjectId,
    deployerAddress: config.deployerAddress,
    publishTxDigest: config.publishTxDigest,
  };
}
