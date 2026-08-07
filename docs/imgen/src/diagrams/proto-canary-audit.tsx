import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Validator", "Relay"];

const accent = {
  Validator: "#0d9488",
  Relay: "#16a34a",
};

const messages: SeqMessage[] = [
  { from: "Validator", to: "Relay", label: "join", detail: "no password, no session pubkey, no roster broadcast" },
  { from: "Relay", to: "Validator", label: "routerRtpCapabilities, transportCreated" },
  { from: "Validator", to: "Validator", label: "derive canary key", detail: "known only within the auditing cell" },
  { from: "Validator", to: "Relay", label: "produce", detail: "synthetic encrypted canary media" },
  { from: "Relay", to: "Relay", label: "forwards it like any other stream" },
  { from: "Validator", to: "Validator", label: "capture forwarded bytes", detail: "raw, undecoded" },
  { from: "Validator", to: "Validator", label: "recompute expected ciphertext locally" },
  { from: "Validator", to: "Validator", label: "compare byte-for-byte", detail: "intact | tampered | dropped" },
  { from: "Validator", to: "Validator", label: "sign evidence", detail: "rotating session key, not main identity" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoCanaryAudit() {
  return (
    <SequenceDiagram
      title="Canary audit"
      subtitle="a validator covertly checks whether a relay forwards media honestly"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
