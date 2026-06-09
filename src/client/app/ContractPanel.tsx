"use client";

import { ConnectButton } from "@mysten/dapp-kit-react/ui";
import {
  DAppKitProvider,
  useCurrentAccount,
  useDAppKit,
} from "@mysten/dapp-kit-react";
import { FormEvent, useEffect, useState } from "react";
import {
  ContractConfig,
  ContractTransactionAction,
  createContractTransaction,
  fetchContractConfig,
} from "@/lib/contract-api";
import { dAppKit } from "@/lib/sui-dapp-kit";

type FormValues = Record<string, FormDataEntryValue>;

function formValues(event: FormEvent<HTMLFormElement>): FormValues {
  event.preventDefault();
  return Object.fromEntries(new FormData(event.currentTarget));
}

function Field(props: {
  name: string;
  placeholder: string;
  type?: string;
  required?: boolean;
  inputMode?: "numeric";
}) {
  return (
    <input
      name={props.name}
      placeholder={props.placeholder}
      type={props.type ?? "text"}
      inputMode={props.inputMode}
      required={props.required ?? true}
      style={{ minWidth: 0 }}
    />
  );
}

function ContractPanelInner() {
  const dAppKit = useDAppKit();
  const account = useCurrentAccount();
  const [config, setConfig] = useState<ContractConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    fetchContractConfig()
      .then(setConfig)
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load contract config",
        ),
      );
  }, []);

  async function execute(
    action: ContractTransactionAction,
    values: FormValues,
  ) {
    if (!account) {
      setError("Connect a Sui wallet first.");
      return;
    }

    setError(null);
    setStatus(`Building ${action} transaction...`);
    const transaction = await createContractTransaction(action, {
      ...values,
      sender: account.address,
    });

    setStatus(`Waiting for wallet signature on ${transaction.network}...`);
    const result = await dAppKit.signAndExecuteTransaction({
      transaction: transaction.txBytes,
    });
    if (result.FailedTransaction) {
      throw new Error(
        result.FailedTransaction.status.error?.message ?? "Transaction failed",
      );
    }
    setStatus(`Transaction submitted: ${result.Transaction.digest}`);
  }

  async function submit(
    action: ContractTransactionAction,
    event: FormEvent<HTMLFormElement>,
  ) {
    try {
      await execute(action, formValues(event));
    } catch (err) {
      setStatus(null);
      setError(
        err instanceof Error ? err.message : "Contract transaction failed",
      );
    }
  }

  return (
    <section
      style={{
        display: "grid",
        gap: 16,
        width: "min(960px, 100%)",
        margin: "32px auto 0",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 18 }}>Sui Contract</h3>
          <p style={{ margin: 0, opacity: 0.72, overflowWrap: "anywhere" }}>
            {config
              ? `${config.network} registry ${config.registryObjectId}`
              : "Loading contract configuration..."}
          </p>
        </div>
        <ConnectButton />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        <form
          onSubmit={(event) => submit("register-worker", event)}
          style={{ display: "grid", gap: 8 }}
        >
          <strong>Register worker</strong>
          <Field name="metadataUri" placeholder="Metadata URI" />
          <Field name="metadataHash" placeholder="32-byte metadata hash hex" />
          <Field
            name="pricePerRentalMist"
            placeholder="Price per rental, MIST"
            inputMode="numeric"
          />
          <Field
            name="stakeMist"
            placeholder="Stake, MIST"
            inputMode="numeric"
          />
          <button className="lk-button" type="submit">
            Register
          </button>
        </form>

        <form
          onSubmit={(event) => submit("hire-worker", event)}
          style={{ display: "grid", gap: 8 }}
        >
          <strong>Hire worker</strong>
          <Field name="nodeId" placeholder="Node ID" inputMode="numeric" />
          <Field name="roomName" placeholder="Room name" />
          <Field
            name="paymentMist"
            placeholder="Payment, MIST"
            inputMode="numeric"
          />
          <button className="lk-button" type="submit">
            Hire
          </button>
        </form>

        <form
          onSubmit={(event) => submit("complete-rental", event)}
          style={{ display: "grid", gap: 8 }}
        >
          <strong>Complete rental</strong>
          <Field name="rentalId" placeholder="Rental ID" inputMode="numeric" />
          <button className="lk-button" type="submit">
            Complete
          </button>
        </form>

        <form
          onSubmit={(event) => submit("cancel-rental", event)}
          style={{ display: "grid", gap: 8 }}
        >
          <strong>Cancel rental</strong>
          <Field name="rentalId" placeholder="Rental ID" inputMode="numeric" />
          <button className="lk-button" type="submit">
            Cancel
          </button>
        </form>

        <form
          onSubmit={(event) => submit("withdraw-stake", event)}
          style={{ display: "grid", gap: 8 }}
        >
          <strong>Withdraw stake</strong>
          <Field name="nodeId" placeholder="Node ID" inputMode="numeric" />
          <button className="lk-button" type="submit">
            Withdraw
          </button>
        </form>
      </div>

      {(status || error) && (
        <p
          style={{
            margin: 0,
            color: error ? "#ff6b6b" : undefined,
            overflowWrap: "anywhere",
          }}
        >
          {error ?? status}
        </p>
      )}
    </section>
  );
}

export default function ContractPanel() {
  return (
    <DAppKitProvider dAppKit={dAppKit}>
      <ContractPanelInner />
    </DAppKitProvider>
  );
}
