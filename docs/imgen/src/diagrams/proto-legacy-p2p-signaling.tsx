import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Peer A", "Signaling", "Peer B"];

const accent = {
  "Peer A": "#2563eb",
  Signaling: "#d97706",
  "Peer B": "#2563eb",
};

const messages: SeqMessage[] = [
  { from: "Signaling", to: "Peer A", label: "welcome", detail: "server-assigned peerId" },
  { from: "Peer A", to: "Signaling", label: "join", detail: "roomId, token, signature, nonce" },
  { from: "Signaling", to: "Signaling", label: "verify token", detail: "expiry, room match, signature, replay check" },
  { from: "Signaling", to: "Peer B", label: "peer-joined", detail: "broadcast to existing room members" },
  { from: "Signaling", to: "Peer A", label: "relay-assigned", detail: "primary_url, standby_url?" },
  { from: "Peer A", to: "Signaling", label: "offer", detail: "sdp, targetPeerId: Peer B" },
  { from: "Signaling", to: "Peer B", label: "offer", detail: "sdp, fromPeerId: Peer A" },
  { from: "Peer B", to: "Signaling", label: "answer", detail: "sdp, targetPeerId: Peer A" },
  { from: "Signaling", to: "Peer A", label: "answer", detail: "sdp, fromPeerId: Peer B" },
  { from: "Peer A", to: "Signaling", label: "ice-candidate", detail: "relayed by targetPeerId, both directions" },
  { from: "Peer A", to: "Signaling", label: "leave" },
  { from: "Signaling", to: "Peer B", label: "peer-left" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoLegacyP2pSignaling() {
  return (
    <SequenceDiagram
      title="Legacy protocol: Client and Signaling (P2P)"
      subtitle="not used by the shipped client -- see call-setup-relay.md for the live protocol"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
