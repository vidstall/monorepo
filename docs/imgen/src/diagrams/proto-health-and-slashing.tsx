import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Worker", "Validators", "Contract"];

const accent = {
  Worker: "#16a34a",
  Validators: "#0d9488",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Worker", to: "Contract", label: "report_node_degradation", detail: "level 0/1/2, advisory only, no stake touched" },
  { from: "Validators", to: "Contract", label: "cast_liveness_vote", detail: "2/3 supermajority: worker presumed dead" },
  { from: "Contract", to: "Contract", label: "execute_ejection", detail: "non-punitive, full stake returned" },
  { from: "Validators", to: "Contract", label: "slash_for_canary_divergence", detail: "2+ validators' proof, relay only, punitive" },
  { from: "Contract", to: "Contract", label: "pay_slash", detail: "escrow settlement, quality shortfall, relay only, punitive" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoHealthAndSlashing() {
  return (
    <SequenceDiagram
      title="Health reporting and slashing"
      subtitle="one advisory path, one non-punitive ejection, two punitive slashing paths"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
