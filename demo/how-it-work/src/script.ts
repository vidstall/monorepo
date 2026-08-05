export type SceneKind = "title" | "pipeline" | "topology" | "evaluation";

export type PipelineStep = {
  label: string;
  sub?: string;
};

export type EvaluationStat = {
  label: string;
  value: string;
};

export type EvaluationImage = {
  /** Filename under public/images/evaluation/ (no path prefix) */
  src: string;
  caption: string;
};

export type EvaluationSection = {
  heading: string;
  images: EvaluationImage[];
};

export type ScriptLine = {
  id: string;
  kind: SceneKind;
  steps?: PipelineStep[];
  /** evaluation-only: headline numbers shown as a stat row */
  stats?: EvaluationStat[];
  /** evaluation-only: labeled Grafana screenshot galleries */
  imageSections?: EvaluationSection[];
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
    id: "intro",
    kind: "title",
    title: "How DVConf\nActually Works",
    subtitle: "Five moving parts, one on-chain source of truth",
    voiceover:
      "Here's how DVConf actually works under the hood — five moving parts, all coordinated by one on-chain source of truth.",
    holdSeconds: 3,
  },
  {
    id: "topology",
    kind: "topology",
    title: "Here's how it\nall connects",
    voiceover:
      "A client or a bot creates a room on-chain. The Control Plane assigns a relay, a validator secretly audits it, and proofs flow back to the chain.",
    holdSeconds: 4,
  },
  {
    id: "worker-registration",
    kind: "pipeline",
    title: "Nodes register\nbefore they work",
    voiceover:
      "Every relay, control plane, and validator node stakes SUI, registers on-chain, and starts a heartbeat before it's trusted with any work. No stake, no vote, no job.",
    steps: [
      { label: "Stake & Register", sub: "registration::register" },
      { label: "Enroll in Registry", sub: "Relay · CP · Validator" },
      { label: "Start Heartbeat", sub: "every 30s" },
      { label: "Visible On-Chain", sub: "ready for work" },
    ],
    holdSeconds: 9,
  },
  {
    id: "client-room",
    kind: "pipeline",
    title: "Clients create\nrooms on-chain",
    voiceover:
      "A client connects their wallet, creates a room on-chain, deposits escrow, and gets matched to a relay to start streaming. The room ID itself is the invite.",
    steps: [
      { label: "Connect Wallet", sub: "register_user" },
      { label: "Create Room", sub: "room_manager" },
      { label: "Deposit Escrow", sub: "economic_layer" },
      { label: "Get Relay", sub: "get_room_assignment" },
      { label: "Join & Stream", sub: "mediasoup" },
    ],
    holdSeconds: 9,
  },
  {
    id: "control-plane",
    kind: "pipeline",
    title: "Control Plane\nassigns relays",
    voiceover:
      "Control Plane nodes watch for new rooms, score candidate relays, and vote — two-thirds must agree before an assignment is final. No single node can hijack a room.",
    steps: [
      { label: "Watch Room Events", sub: "RoomCreated" },
      { label: "Score Candidates", sub: "region · load · RTT" },
      { label: "Propose & Vote", sub: "≥ 2/3 consensus" },
      { label: "Assignment Final", sub: "relay + signaling" },
    ],
    holdSeconds: 9,
  },
  {
    id: "validator",
    kind: "pipeline",
    title: "Validators secretly\ngrade relays",
    voiceover:
      "Validators register with a hidden session wallet, secretly probe relay quality, and submit signed proofs that decide rewards and slashing. The relay never learns who's grading it.",
    steps: [
      { label: "Hidden Session Wallet", sub: "dual-key" },
      { label: "Probe Relay", sub: "RTT · loss · jitter" },
      { label: "Secret Assignment", sub: "relay can't tell who" },
      { label: "Submit Proof", sub: "SessionProof" },
    ],
    holdSeconds: 9,
  },
  {
    id: "bot",
    kind: "pipeline",
    title: "Bots simulate\nreal users",
    voiceover:
      "The bot acts just like a real client — registering, joining a room, and streaming real video over WebRTC — to load-test the network. Real transport, fake camera.",
    steps: [
      { label: "Register as User", sub: "user_registry" },
      { label: "Create / Join Room", sub: "same as a client" },
      { label: "Get Relay", sub: "resolve wss:// endpoint" },
      { label: "Stream Real Media", sub: "ffmpeg + WebRTC" },
    ],
    holdSeconds: 9,
  },
  {
    id: "evaluation",
    kind: "evaluation",
    title: "Does it actually\nwork?",
    subtitle: "three-bot-call-quality — a real 9-minute run",
    voiceover:
      "To prove it actually works, three bots held a steady three-way call for over nine minutes. Average latency came in at 62 milliseconds, jitter under 15, and zero packet loss — while every host's CPU and memory stayed comfortably within capacity.",
    stats: [
      { label: "Avg Latency", value: "61.8 ms" },
      { label: "Avg Jitter", value: "14.7 ms" },
      { label: "Packet Loss", value: "0.0%" },
      { label: "Avg Bitrate", value: "1701 kbps" },
      { label: "ICE Success", value: "76.6%" },
    ],
    imageSections: [
      {
        heading: "Rooms dashboard",
        images: [
          { src: "rooms-jitter.png", caption: "Jitter (all users)" },
          { src: "rooms-packet-loss.png", caption: "Packet loss (all users)" },
          { src: "rooms-bitrate.png", caption: "Bitrate up/down (all users)" },
        ],
      },
      {
        heading: "Infrastructure dashboard",
        images: [
          { src: "infra-cpu.png", caption: "CPU usage per droplet" },
          { src: "infra-memory.png", caption: "Memory available" },
          { src: "infra-network.png", caption: "Network throughput" },
        ],
      },
    ],
    holdSeconds: 10,
  },
  {
    id: "closing",
    kind: "title",
    title: "DVConf",
    subtitle: "Every step, verifiable on-chain.",
    voiceover:
      "Registration, rooms, assignment, and audits — every step verifiable on-chain.",
    holdSeconds: 5,
  },
];
