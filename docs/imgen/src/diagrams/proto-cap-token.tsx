import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "CP 1", "CP 2", "CP 3", "Contract"];

const accent = {
  Client: "#2563eb",
  "CP 1": "#7c3aed",
  "CP 2": "#7c3aed",
  "CP 3": "#7c3aed",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "CP 1", label: "request admission", detail: "roomId, peerPubkey, role, expiry, nonce" },
  { from: "CP 1", to: "CP 1", label: "re-derive canonical bytes and sign" },
  { from: "CP 2", to: "CP 2", label: "re-derive canonical bytes and sign" },
  { from: "CP 3", to: "CP 3", label: "not asked this round (2 of 3 is enough)" },
  { from: "Client", to: "Contract", label: "issue_capability_token", detail: "2 signatures + both pubkeys" },
  { from: "Contract", to: "Contract", label: "check quorum >= 2, distinct signers, verify each signature" },
  { from: "Contract", to: "Client", label: "RoomCapability minted", detail: "transferred to requester" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoCapToken() {
  return (
    <SequenceDiagram
      title="Room admission tokens: quorum issuance"
      subtitle="no single control-plane operator can mint a token alone"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
