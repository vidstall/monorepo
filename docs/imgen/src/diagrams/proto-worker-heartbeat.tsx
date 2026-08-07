import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Relay", "Standby relay", "Contract"];

const accent = {
  Relay: "#16a34a",
  "Standby relay": "#0d9488",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Relay", to: "Contract", label: "relay_heartbeat + update_load", detail: "~every 30s" },
  { from: "Standby relay", to: "Contract", label: "relay_heartbeat + update_load", detail: "~every 30s" },
  { from: "Relay", to: "Standby relay", label: "HTTP GET /healthz", detail: "~every 1s, off-chain" },
  { from: "Standby relay", to: "Standby relay", label: "3 missed pings = primary flagged down locally" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoWorkerHeartbeat() {
  return (
    <SequenceDiagram
      title="Worker heartbeat"
      subtitle="on-chain liveness every ~30s, plus relay's own faster off-chain standby ping"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
