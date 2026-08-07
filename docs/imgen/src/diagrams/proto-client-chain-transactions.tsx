import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "Contract"];

const accent = {
  Client: "#2563eb",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "Client", label: "sign with wallet", detail: "extension key or manual session key" },
  {
    from: "Client",
    to: "Contract",
    label: "create_room",
    detail: "expected_participants, room_class_hint",
  },
  { from: "Contract", to: "Client", label: "RoomCreated event", detail: "room_id read from the event" },
  {
    from: "Client",
    to: "Contract",
    label: "create_escrow",
    detail: "room_id, Coin split from gas",
  },
  {
    from: "Contract",
    to: "Contract",
    label: "checks",
    detail: "caller is room creator, room still pending, amount > 0",
  },
  { from: "Contract", to: "Client", label: "EscrowCreated event", detail: "escrow_id, amount" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoClientChainTransactions() {
  return (
    <SequenceDiagram
      title="Client and Contract: Transactions"
      subtitle="room creation and escrow funding -- the transactions a client signs directly"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
