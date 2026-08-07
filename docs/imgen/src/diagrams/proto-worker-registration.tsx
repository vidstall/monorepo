import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Worker", "Contract", "CP"];

const accent = {
  Worker: "#16a34a",
  Contract: "#d97706",
  CP: "#7c3aed",
};

const messages: SeqMessage[] = [
  { from: "Worker", to: "Contract", label: "registration::register", detail: "stake a coin" },
  { from: "Contract", to: "Worker", label: "MinerCap (role: unassigned)", detail: "or ControlPlaneCap if stake clears CP threshold" },
  { from: "CP", to: "Contract", label: "cast_role_vote", detail: "relay / signaling / validator" },
  { from: "Worker", to: "Contract", label: "apply_voted_role" },
  { from: "Worker", to: "Contract", label: "register in matching registry", detail: "relay_registry / signaling_registry / validator_registry" },
  { from: "Worker", to: "Worker", label: "on restart: verify still registered, self-heal if ejected" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoWorkerRegistration() {
  return (
    <SequenceDiagram
      title="Worker registration"
      subtitle="stake, get a role (voted or direct for CP), then enroll in the matching registry"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
