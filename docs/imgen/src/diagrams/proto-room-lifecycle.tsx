import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "Contract", "cp-daemon"];

const accent = {
  Client: "#2563eb",
  Contract: "#d97706",
  "cp-daemon": "#7c3aed",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "Contract", label: "create_room" },
  { from: "cp-daemon", to: "cp-daemon", label: "score candidates", detail: "relays, signaling, validators" },
  { from: "cp-daemon", to: "Contract", label: "submit_pairing_proposal", detail: "ballot: relays, signaling, validators, top-3 health watchers" },
  { from: "Contract", to: "Contract", label: "tally CP quorum", detail: "assignment written once 2/3 agree" },
  { from: "cp-daemon", to: "Contract", label: "periodic expiry sweep", detail: "pending ~15min, active ~12h" },
  { from: "cp-daemon", to: "Contract", label: "close_expired_room", detail: "guarded by expected status" },
  { from: "cp-daemon", to: "Contract", label: "watch relay heartbeat" },
  { from: "cp-daemon", to: "Contract", label: "promote_relay", detail: "primary heartbeat went stale" },
  { from: "cp-daemon", to: "Contract", label: "propose_relay_replacement", detail: "standby went stale, quorum-voted" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoRoomLifecycle() {
  return (
    <SequenceDiagram
      title="Room lifecycle on-chain"
      subtitle="creation, CP-scored assignment by quorum, expiry sweep, and heartbeat-driven relay promotion"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
