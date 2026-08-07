import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Standby Relay", "Primary Relay"];

const accent = {
  "Standby Relay": "#0d9488",
  "Primary Relay": "#16a34a",
};

const messages: SeqMessage[] = [
  { from: "Standby Relay", to: "Primary Relay", label: "connect", detail: "bearer token, WS upgrade" },
  { from: "Standby Relay", to: "Standby Relay", label: "mint pipe transport" },
  { from: "Standby Relay", to: "Primary Relay", label: "pipe-connect", detail: "standby's ip/port" },
  { from: "Primary Relay", to: "Primary Relay", label: "mint + connect pipe transport" },
  { from: "Primary Relay", to: "Standby Relay", label: "pipe-connect", detail: "primary's ip/port (reply)" },
  { from: "Standby Relay", to: "Standby Relay", label: "connect own transport to reply" },
  { from: "Primary Relay", to: "Standby Relay", label: "pipe-producer", detail: "announces a room stream is available" },
  { from: "Standby Relay", to: "Standby Relay", label: "consume onto pipe, then pause", detail: "keep-alive only, ~80% bandwidth saved" },
  { from: "Standby Relay", to: "Primary Relay", label: "pipe-producer", detail: "reverse: standby-homed client's own stream" },
  { from: "Primary Relay", to: "Primary Relay", label: "mint local copy, fan to room + tree" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoInterRelayWarmPipe() {
  return (
    <SequenceDiagram
      title="Inter-relay warm pipe"
      subtitle="standby pre-stages a room's media so failover is instant"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
