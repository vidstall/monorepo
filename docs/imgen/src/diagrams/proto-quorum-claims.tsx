import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Validator A", "Validator B", "Claim Board"];

const accent = {
  "Validator A": "#0d9488",
  "Validator B": "#0891b2",
  "Claim Board": "#7c3aed",
};

const messages: SeqMessage[] = [
  { from: "Validator A", to: "Validator A", label: "independently observes a divergence" },
  { from: "Validator A", to: "Claim Board", label: "POST /claims", detail: "own evidence only, allow-listed fields" },
  { from: "Validator B", to: "Validator B", label: "independently observes the same divergence" },
  { from: "Validator B", to: "Claim Board", label: "POST /claims", detail: "own evidence only" },
  { from: "Claim Board", to: "Claim Board", label: "quorum reached", detail: "2 independent, distinct signers" },
  { from: "Validator A", to: "Claim Board", label: "GET /claims/open" },
  { from: "Validator A", to: "Validator A", label: "assemble combined proof" },
  { from: "Validator A", to: "Claim Board", label: "POST /claims/mark-submitted" },
  { from: "Claim Board", to: "Claim Board", label: "unclaimed rows garbage-collected over time" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoQuorumClaims() {
  return (
    <SequenceDiagram
      title="Quorum claims"
      subtitle="combining independent evidence before an on-chain submission"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
