import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "Contract"];

const accent = {
  Client: "#2563eb",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "Client", label: "every 60s", detail: "poll timer fires" },
  {
    from: "Client",
    to: "Contract",
    label: "devInspect: relay_registry.get_active_relays",
    detail: "free simulation, no signature, no fee",
  },
  {
    from: "Contract",
    to: "Client",
    label: "active relay list",
    detail: "region, reputation, endpoint_url per relay",
  },
  { from: "Client", to: "Client", label: "score and rank", detail: "same-region bonus + reputation" },
  { from: "Client", to: "Client", label: "pick top two", detail: "primary and standby" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoClientChainDiscovery() {
  return (
    <SequenceDiagram
      title="Client and Contract: Discovery"
      subtitle="one representative devInspect round trip -- relay discovery. Signaling discovery, room assignment, room status, and network stats all follow the same shape."
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
