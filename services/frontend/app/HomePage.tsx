"use client";

import { ConnectButton } from "@mysten/dapp-kit-react/ui";
import {
  DAppKitProvider,
  useCurrentAccount,
  useDAppKit,
} from "@mysten/dapp-kit-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { SuiGrpcClient } from "@mysten/sui/grpc";
import { createContractTransaction } from "@/lib/contract-api";
import { dAppKit } from "@/lib/sui-dapp-kit";
import {
  fetchAllWorkers,
  selectOnChainRoute,
  SelectedRoute,
  WorkerRecord,
} from "@/lib/route-discovery";
import styles from "../styles/Home.module.css";

const ContractPanel = dynamic(() => import("./ContractPanel"), { ssr: false });

const showSettings = process.env.NEXT_PUBLIC_SHOW_SETTINGS_MENU === "true";

const GRPC_URLS = {
  devnet: "https://fullnode.devnet.sui.io:443",
  testnet: "https://fullnode.testnet.sui.io:443",
  mainnet: "https://fullnode.mainnet.sui.io:443",
} as const;

type ContractNetwork = keyof typeof GRPC_URLS;

type RegistryStats = {
  nodeCount: bigint;
  activeWorkerCount: bigint;
  nextRentalId: bigint;
  packageId: string;
  registryObjectId: string;
  network: string;
};

async function fetchRegistryStats(): Promise<RegistryStats> {
  const network = (process.env.NEXT_PUBLIC_SUI_NETWORK ??
    "devnet") as ContractNetwork;
  const registryObjectId = process.env.NEXT_PUBLIC_REGISTRY_OBJECT_ID ?? "";
  if (!registryObjectId)
    throw new Error("NEXT_PUBLIC_REGISTRY_OBJECT_ID not set");
  if (!(network in GRPC_URLS))
    throw new Error(`Unsupported contract network: ${network}`);
  const client = new SuiGrpcClient({ network, baseUrl: GRPC_URLS[network] });
  const obj = await client.getObject({
    objectId: registryObjectId,
    include: { json: true },
  });
  const fields =
    (
      obj.object as {
        json?: {
          workers?: Record<string, string>;
          rentals?: Record<string, string>;
        };
      } | null
    )?.json ?? null;
  if (!fields) throw new Error("Registry object not found on-chain");
  return {
    nodeCount: BigInt(fields.workers?.node_count ?? 0),
    activeWorkerCount: BigInt(fields.workers?.active_worker_count ?? 0),
    nextRentalId: BigInt(fields.rentals?.next_rental_id ?? 0),
    packageId: process.env.NEXT_PUBLIC_PACKAGE_ID ?? "",
    registryObjectId,
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
      .then((s) => {
        setStats(s);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "RPC error");
        setLoading(false);
      });
  }, []);

  return (
    <div className={styles.card}>
      <p className={styles.cardLabel}>contract status</p>

      {loading ? (
        <div className={styles.statusRows}>
          {[45, 65, 55, 50, 40].map((w, i) => (
            <div
              key={i}
              className={styles.skeleton}
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
      ) : (
        <div className={styles.statusRows}>
          <div className={styles.statusRow}>
            <span className={styles.statusKey}>status</span>
            <span className={styles.statusDotRow}>
              <span className={styles.statusDot} data-live={String(!error)} />
              <span className={styles.statusVal}>
                {error ? "offline" : "live"}
              </span>
            </span>
          </div>

          <div className={styles.statusRow}>
            <span className={styles.statusKey}>network</span>
            <span
              className={styles.networkBadge}
              data-network={stats?.network ?? "unknown"}
            >
              {stats?.network ?? (loading ? "loading" : "unavailable")}
            </span>
          </div>

          {error ? (
            <div className={styles.statusRow}>
              <span className={styles.statusKey}>error</span>
              <span
                className={styles.statusVal}
                style={{ color: "var(--xai-error)", fontSize: "0.65rem" }}
              >
                {error}
              </span>
            </div>
          ) : (
            <>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>workers</span>
                <span className={styles.statusVal}>
                  {stats!.activeWorkerCount.toString()} active /{" "}
                  {stats!.nodeCount.toString()} total
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>rentals</span>
                <span className={styles.statusVal}>
                  {(stats!.nextRentalId - 1n < 0n
                    ? 0n
                    : stats!.nextRentalId - 1n
                  ).toString()}{" "}
                  total
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>package</span>
                <span className={styles.statusVal}>
                  {truncateAddr(stats!.packageId)}
                </span>
              </div>
              <div className={styles.statusRow}>
                <span className={styles.statusKey}>registry</span>
                <span className={styles.statusVal}>
                  {truncateAddr(stats!.registryObjectId)}
                </span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function CurrentRouteCard() {
  const [route, setRoute] = useState<SelectedRoute | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    selectOnChainRoute()
      .then((r) => {
        setRoute(r);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "RPC error");
        setLoading(false);
      });
  }, []);

  return (
    <div className={styles.card}>
      <p className={styles.cardLabel}>current route</p>

      {loading ? (
        <div className={styles.statusRows}>
          {[60, 75].map((w, i) => (
            <div
              key={i}
              className={styles.skeleton}
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
      ) : error ? (
        <div className={styles.statusRow}>
          <span className={styles.statusKey}>error</span>
          <span
            className={styles.statusVal}
            style={{ color: "var(--xai-error)", fontSize: "0.65rem" }}
          >
            {error}
          </span>
        </div>
      ) : !route ? (
        <p className={styles.description}>no reachable router right now</p>
      ) : (
        <div className={styles.statusRows}>
          <div className={styles.statusRow}>
            <span className={styles.statusKey}>node</span>
            <span className={styles.statusVal}>#{route.nodeId}</span>
          </div>
          <div className={styles.statusRow}>
            <span className={styles.statusKey}>endpoint</span>
            <span className={styles.statusVal}>{route.endpoint}</span>
          </div>
          <div className={styles.statusRow}>
            <span className={styles.statusKey}>latency</span>
            <span className={styles.statusVal}>{route.latencyMs} ms</span>
          </div>
        </div>
      )}
    </div>
  );
}

function WorkerListCard() {
  const [workers, setWorkers] = useState<WorkerRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAllWorkers()
      .then((w) => {
        setWorkers(w);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "RPC error");
        setLoading(false);
      });
  }, []);

  return (
    <div className={styles.card}>
      <p className={styles.cardLabel}>workers</p>

      {loading ? (
        <div className={styles.statusRows}>
          {[70, 55, 60].map((w, i) => (
            <div
              key={i}
              className={styles.skeleton}
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
      ) : error ? (
        <div className={styles.statusRow}>
          <span className={styles.statusKey}>error</span>
          <span
            className={styles.statusVal}
            style={{ color: "var(--xai-error)", fontSize: "0.65rem" }}
          >
            {error}
          </span>
        </div>
      ) : workers!.length === 0 ? (
        <p className={styles.description}>no workers registered yet</p>
      ) : (
        <div className={styles.workerRows}>
          {workers!.map((w) => (
            <div key={w.nodeId} className={styles.workerRow}>
              <span className={styles.statusDot} data-live={String(w.active)} />
              <span className={styles.workerRole}>{w.roleLabel}</span>
              <span className={styles.workerUrl} title={w.endpoint}>
                {w.endpoint || "—"}
              </span>
            </div>
          ))}
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
    if (name) router.push(`/rooms?roomName=${encodeURIComponent(name)}`);
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
      const result = await dKit.signAndExecuteTransaction({
        transaction: tx.txBytes,
      });
      if (result.FailedTransaction) {
        throw new Error(
          result.FailedTransaction.status.error?.message ??
            "Transaction failed",
        );
      }

      setStatus("room ordered — joining…");
      router.push(`/rooms?roomName=${encodeURIComponent(name)}`);
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
          <CurrentRouteCard />
          <WorkerListCard />
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
