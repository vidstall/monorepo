import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Relay", "cp-daemon", "Contract"];

const accent = {
  Relay: "#16a34a",
  "cp-daemon": "#7c3aed",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Relay", to: "cp-daemon", label: "POST /turn/issue", detail: "bearer token, target user id" },
  { from: "cp-daemon", to: "cp-daemon", label: "compute HMAC credential", detail: "username:timestamp, password:HMAC" },
  { from: "cp-daemon", to: "Contract", label: "issue_turn_credential", detail: "credential hash only, not the secret" },
  { from: "cp-daemon", to: "Relay", label: "username, password, expiry", detail: "or skipped if relay is slashed" },
  { from: "cp-daemon", to: "cp-daemon", label: "rotate shared secret", detail: "~daily, plus emergency kill-switch on slash" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoTurnCredentials() {
  return (
    <SequenceDiagram
      title="TURN credential issuance"
      subtitle="cp-daemon mints short-lived coturn credentials, not the relay itself"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
