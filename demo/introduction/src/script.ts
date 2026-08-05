export type SceneKind = "title" | "diagram";

export type DiagramId =
  | "chain-vs-relay"
  | "topology"
  | "cp-assign"
  | "validator-audit"
  | "rewards"
  | "slashing";

export type ScriptLine = {
  id: string;
  kind: SceneKind;
  diagram?: DiagramId;
  /** Big on-screen heading */
  title: string;
  /** Smaller supporting on-screen line (optional) */
  subtitle?: string;
  /** Text sent to kokoro-tts and shown as the burned-in caption */
  voiceover: string;
  /** Extra seconds to hold the visual after the voiceover ends, for animation breathing room */
  holdSeconds: number;
};

export const script: ScriptLine[] = [
  {
    id: "hook",
    kind: "title",
    title: "Every call runs\nthrough someone else's server.",
    voiceover:
      "Every video call today runs through someone else's server — a company that can see your data, log your calls, or shut you down at any time.",
    holdSeconds: 1.5,
  },
  {
    id: "intro",
    kind: "title",
    title: "DVConf",
    subtitle: "Decentralized Video Conferencing",
    voiceover:
      "Meet DVConf — a decentralized video conferencing system built on the Sui blockchain.",
    holdSeconds: 2,
  },
  {
    id: "core-idea",
    kind: "diagram",
    diagram: "chain-vs-relay",
    title: "Chain for trust.\nOff-chain for media.",
    voiceover:
      "The blockchain handles coordination, trust, and money. Real-time video and audio never touch the chain — instead, they flow through staked, off-chain relay nodes.",
    holdSeconds: 2.5,
  },
  {
    id: "topology",
    kind: "diagram",
    diagram: "topology",
    title: "Here's how it\nall connects.",
    voiceover:
      "Users and rooms live on the Sui chain. The chain's Control Plane assigns a relay to each room, hidden validators audit that relay, and rewards flow back on-chain.",
    holdSeconds: 2.8,
  },
  {
    id: "users-rooms",
    kind: "title",
    title: "Users and rooms\nlive on-chain.",
    voiceover:
      "Users register on-chain, and every room is created as a shared object that anyone can verify.",
    holdSeconds: 1.8,
  },
  {
    id: "control-plane",
    kind: "diagram",
    diagram: "cp-assign",
    title: "Control Plane nodes\nassign relays.",
    voiceover:
      "Control Plane nodes vote on which relay serves each room, choosing between SFU mode for small calls and MCU mode for large ones.",
    holdSeconds: 2.2,
  },
  {
    id: "validators",
    kind: "diagram",
    diagram: "validator-audit",
    title: "Validators secretly\naudit quality.",
    voiceover:
      "Hidden validator nodes independently measure relay performance — packet loss, bandwidth, real quality — without the relay ever knowing who is watching.",
    holdSeconds: 2.2,
  },
  {
    id: "rewards",
    kind: "diagram",
    diagram: "rewards",
    title: "Honest work earns\nDVCONF tokens.",
    voiceover:
      "Relays get paid for the bytes they actually forward, verified by validator proofs — not by trusting a self-reported number.",
    holdSeconds: 2,
  },
  {
    id: "slashing",
    kind: "diagram",
    diagram: "slashing",
    title: "Dishonest relays\nget slashed.",
    voiceover:
      "If quality drops to zero, the relay's staked tokens are slashed. Cheating the network costs real money.",
    holdSeconds: 2,
  },
  {
    id: "no-central-server",
    kind: "title",
    title: "No company controls\nthe network.",
    voiceover:
      "There is no central server to trust, to seize, or to shut down — every incentive is enforced on-chain, in the open.",
    holdSeconds: 2,
  },
  {
    id: "status",
    kind: "title",
    title: "v1.0 is live\non Sui testnet.",
    subtitle: "Token · 5 registries · 3 off-chain daemons",
    voiceover:
      "Version one point zero is already live on the Sui testnet: the token contract, five on-chain registries, and three off-chain daemons — control plane, validator, and signaling.",
    holdSeconds: 2.2,
  },
  {
    id: "building",
    kind: "title",
    title: "Now building\nthe client app.",
    voiceover:
      "We're now building the web client — wallet connect, room creation, and real WebRTC video sessions through the assigned relay.",
    holdSeconds: 2,
  },
  {
    id: "closing",
    kind: "title",
    title: "DVConf",
    subtitle: "Video, coordinated by code — not a company.",
    voiceover:
      "DVConf: real-time video conferencing, coordinated by code, not by a company.",
    holdSeconds: 3.5,
  },
];
