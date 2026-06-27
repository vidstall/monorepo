"use client";

import { ConnectButton } from "@mysten/dapp-kit-react/ui";
import { DAppKitProvider, useCurrentAccount, useDAppKit } from "@mysten/dapp-kit-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { SuiGrpcClient } from "@mysten/sui/grpc";
import { createContractTransaction, fetchContractConfig } from "@/lib/contract-api";
import { dAppKit } from "@/lib/sui-dapp-kit";
import styles from "../styles/Home.module.css";

const ContractPanel = dynamic(() => import("./ContractPanel"), { ssr: false });

const showSettings = process.env.NEXT_PUBLIC_SHOW_SETTINGS_MENU === "true";

const CONTRACT_NETWORK = (process.env.NEXT_PUBLIC_CONTRACT_NETWORK ?? "testnet") as "testnet" | "devnet" | "mainnet";

const GRPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

type RegistryStats = {
  nodeCount: bigint;
  activeWorkerCount: bigint;
  nextRentalId: bigint;
  packageId: string;
  registryObjectId: string;
  network: string;
};

async function fetchRegistryStats(): Promise<RegistryStats> {
  const config = await fetchContractConfig();
  const network = (config.network ?? CONTRACT_NETWORK) as "testnet" | "devnet" | "mainnet";
  const client = new SuiGrpcClient({
    network,
    baseUrl: GRPC_URLS[network],
  });
  const obj = await client.getObject({
    objectId: config.registryObjectId,
    include: { json: true },
  });
  const fields = obj.object.json as Record<string, string> | null;
  if (!fields) throw new Error("Registry object not found on-chain");
  return {
    nodeCount: BigInt(fields.node_count ?? 0),
    activeWorkerCount: BigInt(fields.active_worker_count ?? 0),
    nextRentalId: BigInt(fields.next_rental_id ?? 0),
    packageId: config.packageId,
    registryObjectId: config.registryObjectId,
    network,
  };
}

function truncateAddr(addr: string): string {
  if (addr.length <= 18) return addr;
  return addr.slice(0, 10) + "…" + addr.slice(-6);
}

function ContractStatusCard() {
  const [stats, setStats] = useState<RegistryStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRegistryStats()
      .then((s) => { setStats(s); setLoading(false); })
      .catch((e) => { setError(e instanceof Error ? e.message : "RPC error"); setLoading(false); });
  }, []);

  return (
    <div className={styles.card}>
      <p className={styles.cardLabel}>contract status</p>

      {loading ? (
        <div className={styles.statusRows}>
          {[45, 65, 55, 50, 40].map((w, i) => (
            <div key={i} className={styles.skeleton} style={{ width: `${w}%` }} />
          ))}
        </div>
      ) : (
        <div className={styles.statusRows}>
          <div className={styles.statusRow}>
            <span className={styles.statusKey}>status</span>
            <span className={styles.statusDotRow}>
              <span className={styles.statusDot} data-live={String(!error)} />
              <span className={styles.statusVal}>{error ? "offline" : "live"}</span>
            </span>
          </div>

          <div className={styles.statusRow}>
            <span className={styles.statusKey}>network</span>
            <span className={styles.networkBadge} data-network={stats?.network ?? CONTRACT_NETWORK}>
              {stats?.network ?? CONTRACT_NETWORK}
            </span>
          </div>

          {error ? (
            <div className={styles.statusRow}>
              <span className={styles.statusKey}>error</span>
              <span className={styles.statusVal} style={{ color: "var(--xai-error)", fontSize: "0.65rem" }}>
                {error}
              </span>
            </div>
          ) : (
            <>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>workers</span>
                <span className={styles.statusVal}>
                  {stats!.activeWorkerCount.toString()} active / {stats!.nodeCount.toString()} total
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>rentals</span>
                <span className={styles.statusVal}>{(stats!.nextRentalId - 1n < 0n ? 0n : stats!.nextRentalId - 1n).toString()} total</span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>package</span>
                <span className={styles.statusVal}>{truncateAddr(stats!.packageId)}</span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>registry</span>
                <span className={styles.statusVal}>{truncateAddr(stats!.registryObjectId)}</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function JoinRoomForm() {
  const router = useRouter();
  const [roomName, setRoomName] = useState("");

  function handleJoin(e: FormEvent) {
    e.preventDefault();
    const name = roomName.trim();
    if (name) router.push(`/rooms/${encodeURIComponent(name)}`);
  }

  return (
    <form onSubmit={handleJoin} className={styles.joinRow}>
      <input
        className={styles.field}
        value={roomName}
        onChange={(e) => setRoomName(e.target.value)}
        placeholder="room name"
        required
      />
      <button className={styles.btn} type="submit">
        Join
      </button>
    </form>
  );
}

function CreateRoomForm() {
  const router = useRouter();
  const account = useCurrentAccount();
  const dKit = useDAppKit();

  const [roomName, setRoomName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [budget, setBudget] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!account) {
      setError("Connect a Sui wallet first.");
      return;
    }
    const name = roomName.trim();
    if (!name) return;

    setError(null);
    setStatus("building transaction…");
    try {
      const tx = await createContractTransaction("order-room", {
        roomName: name,
        capacity: Number(capacity),
        paymentMist: Number(budget),
        sender: account.address,
      });

      setStatus("waiting for wallet signature…");
      const result = await dKit.signAndExecuteTransaction({ transaction: tx.txBytes });
      if (result.FailedTransaction) {
        throw new Error(result.FailedTransaction.status.error?.message ?? "Transaction failed");
      }

      setStatus("room ordered — joining…");
      router.push(`/rooms/${encodeURIComponent(name)}`);
    } catch (err) {
      setStatus(null);
      setError(err instanceof Error ? err.message : "Failed to create room");
    }
  }

  return (
    <form onSubmit={handleCreate} style={{ display: "contents" }}>
      <input
        className={styles.field}
        value={roomName}
        onChange={(e) => setRoomName(e.target.value)}
        placeholder="room name"
        required
      />
      <input
        className={styles.field}
        value={capacity}
        onChange={(e) => setCapacity(e.target.value)}
        placeholder="max participants"
        type="number"
        min={1}
        required
      />
      <div className={styles.mistRow}>
        <input
          className={styles.field}
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          placeholder="budget"
          type="number"
          min={1}
          required
        />
        <span className={styles.mistUnit}>MIST</span>
      </div>
      <div className={styles.actions}>
        <ConnectButton />
        <button className={styles.btn} type="submit" disabled={!account}>
          Order &amp; Join
        </button>
      </div>
      {(status || error) && (
        <p className={styles.statusLine} data-error={String(!!error)}>
          {error ?? status}
        </p>
      )}
    </form>
  );
}

function HomeInner() {
  return (
    <main className={styles.main} data-lk-theme="default">
      <div className={styles.header}>
        <div className={styles.wordmark}>XAISEN</div>
        <p className={styles.tagline}>decentralized video network</p>
      </div>

      <div className={styles.layout}>
        <div className={styles.leftCol}>
          <ContractStatusCard />
        </div>

        <div className={styles.rightCol}>
          <div className={styles.card}>
            <p className={styles.cardLabel}>join a room</p>
            <JoinRoomForm />
          </div>

          <div className={styles.card}>
            <p className={styles.cardLabel}>order a room</p>
            <p className={styles.description}>
              Payment held in escrow. Workers assign your SFU within seconds.
            </p>
            <CreateRoomForm />
          </div>
        </div>
      </div>

      {showSettings && <ContractPanel />}
    </main>
  );
}

export default function Page() {
  return (
    <DAppKitProvider dAppKit={dAppKit}>
      <HomeInner />
    </DAppKitProvider>
  );
}
