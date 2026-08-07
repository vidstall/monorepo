import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "Contract", "Validator", "Relay"];

const accent = {
  Client: "#2563eb",
  Contract: "#d97706",
  Validator: "#0d9488",
  Relay: "#16a34a",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "Contract", label: "create_escrow", detail: "locks payment for the room" },
  { from: "Relay", to: "Client", label: "carries the call", detail: "media flows directly, no chain involved" },
  { from: "Validator", to: "Validator", label: "measure relay performance", detail: "packets, bytes, latency, loss, jitter" },
  { from: "Validator", to: "Contract", label: "submit_session_proof", detail: "signed by identity key and session key" },
  { from: "Validator", to: "Contract", label: "submit_session_proof", detail: "a second, independent validator" },
  { from: "Contract", to: "Contract", label: "close_room", detail: "room lifecycle ends, see room-lifecycle.md" },
  { from: "Contract", to: "Contract", label: "distribute_rewards", detail: "median of proofs times quality multiplier" },
  { from: "Contract", to: "Relay", label: "reward paid", detail: "healthy relay's share of the escrow" },
  { from: "Contract", to: "Contract", label: "pay_slash", detail: "only if a relay was proven to misbehave" },
  { from: "Contract", to: "Client", label: "RewardsDistributed event", detail: "read-only, dashboard display" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoRewardsAndEscrow() {
  return (
    <SequenceDiagram
      title="Rewards and escrow"
      subtitle="funding a room, measuring relays, paying out or slashing"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
