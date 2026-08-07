import React from "react";
import { SequenceDiagram, sequenceDiagramSize, type SeqMessage } from "../shared";

const actors = ["Client", "Relay"];

const accent = {
  Client: "#2563eb",
  Relay: "#16a34a",
};

const messages: SeqMessage[] = [
  { from: "Client", to: "Relay", label: "join", detail: "roomId, peerId, peerPubkey, roomPassword?" },
  { from: "Relay", to: "Client", label: "routerRtpCapabilities" },
  { from: "Relay", to: "Client", label: "roomMode", detail: "e2ee, SFU-E2EE | MCU-floor" },
  { from: "Relay", to: "Client", label: "newProducer", detail: "one per existing publisher" },
  { from: "Relay", to: "Client", label: "rosterPeer", detail: "peerId to sessionPubkey, if password/E2EE room" },
  { from: "Client", to: "Relay", label: "createTransport", detail: "direction: send" },
  { from: "Relay", to: "Client", label: "transportCreated", detail: "ICE + DTLS params" },
  { from: "Client", to: "Relay", label: "connectTransport" },
  { from: "Client", to: "Relay", label: "produce", detail: "kind, rtpParameters" },
  { from: "Relay", to: "Client", label: "produced", detail: "producerId" },
  { from: "Client", to: "Relay", label: "createTransport", detail: "direction: recv" },
  { from: "Client", to: "Relay", label: "consume", detail: "producerId, rtpCapabilities" },
  { from: "Relay", to: "Client", label: "consumed", detail: "consumerId, producerPeerId?" },
];

export const { width, height } = sequenceDiagramSize(actors, messages);

export default function ProtoCallSetupRelay() {
  return (
    <SequenceDiagram
      title="Call setup: Client and Relay"
      subtitle="mediasoup signaling — admission, transport negotiation, produce/consume"
      actors={actors}
      accent={accent}
      messages={messages}
    />
  );
}
