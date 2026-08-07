import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["New member", "Relay", "Coordinator", "Other members"];

const accent = {
  "New member": "#2563eb",
  Relay: "#16a34a",
  Coordinator: "#7c3aed",
  "Other members": "#2563eb",
};

const messages: SeqMessage[] = [
  { from: "Relay", to: "New member", label: "rosterPeer", detail: "existing members' session pubkeys" },
  { from: "Relay", to: "Other members", label: "rosterPeer", detail: "new member's session pubkey" },
  { from: "Coordinator", to: "Coordinator", label: "elected locally", detail: "smallest session pubkey in roster" },
  { from: "Coordinator", to: "Coordinator", label: "derive new room key", detail: "ratchet forward (join) -- old key can't be recovered by newcomer" },
  { from: "Coordinator", to: "Relay", label: "e2eeKeyBundle", detail: "roomId, kid, sealed copy per recipient" },
  { from: "Relay", to: "New member", label: "e2eeKeyBundle", detail: "blind re-broadcast, relay never opens it" },
  { from: "Relay", to: "Other members", label: "e2eeKeyBundle", detail: "blind re-broadcast" },
  { from: "New member", to: "New member", label: "unseal own envelope", detail: "only this member's key can open it" },
  { from: "New member", to: "New member", label: "derive per-sender content key", detail: "room key + roomId + kid + senderId" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoEndToEndEncryption() {
  return (
    <SequenceDiagram
      title="End-to-end encryption key exchange"
      subtitle="client-to-client; relay only ever forwards opaque sealed bytes"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
