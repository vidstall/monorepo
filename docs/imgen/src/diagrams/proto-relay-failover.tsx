import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "Primary relay", "Standby relay"];

const accent = {
  Client: "#2563eb",
  "Primary relay": "#16a34a",
  "Standby relay": "#0d9488",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "Primary relay", label: "join / consume", detail: "normal call setup, see call-setup-relay.md" },
  { from: "Client", to: "Standby relay", label: "join", detail: "no password, receive-only pre-warm" },
  { from: "Client", to: "Standby relay", label: "consume", detail: "no producerId -- standby resolves it itself" },
  { from: "Client", to: "Client", label: "pause standby stream", detail: "keep-alive only, nothing rendered" },
  { from: "Primary relay", to: "Client", label: "WebSocket closes", detail: "Layer B trigger -- primary relay is down" },
  { from: "Client", to: "Standby relay", label: "relay-down-hint (HTTP)", detail: "fire-and-forget, best-effort only" },
  { from: "Client", to: "Client", label: "resume standby stream", detail: "cutover -- render mode may change to grid" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoRelayFailover() {
  return (
    <SequenceDiagram
      title="Relay failover: standby cutover"
      subtitle="client pre-warms a standby connection so cutover is a resume, not a rejoin"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
