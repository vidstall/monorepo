import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Worker", "CP 1", "CP 2", "Contract"];

const accent = {
  Worker: "#16a34a",
  "CP 1": "#7c3aed",
  "CP 2": "#7c3aed",
  Contract: "#d97706",
};

const messages: SeqMessage[] = [
  { from: "Contract", to: "CP 1", label: "MinerRegistered", detail: "role: unassigned" },
  { from: "CP 1", to: "CP 1", label: "infer likely role, compute scarcest role" },
  { from: "CP 1", to: "Contract", label: "cast_role_vote" },
  { from: "CP 2", to: "Contract", label: "cast_role_vote", detail: "2/3 of active CPs reached" },
  { from: "Worker", to: "Contract", label: "apply_voted_role", detail: "consumes the completed vote" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoRoleVoting() {
  return (
    <SequenceDiagram
      title="Role voting"
      subtitle="a two-thirds CP supermajority assigns each unassigned worker's role"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
