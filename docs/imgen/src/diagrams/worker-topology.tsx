import React from "react";
import { Box, Label, Line, Point, theme } from "../shared";

export const width = 2260;
export const height = 1550;

const colors = {
  chain: "#d97706",
  relay: "#16a34a",
  validator: "#0d9488",
  cp: "#7c3aed",
  signaling: "#2563eb",
};

function GroupBox(props: {
  title: string;
  subtitle: string;
  accent: string;
  center: Point;
  width: number;
  height: number;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        position: "absolute",
        left: props.center.x - props.width / 2,
        top: props.center.y - props.height / 2,
        width: props.width,
        height: props.height,
        borderRadius: 20,
        border: `3px solid ${props.accent}`,
        background: theme.panel,
        paddingTop: 24,
      }}
    >
      <div style={{ display: "flex", fontSize: 24, fontWeight: 700, color: theme.text }}>
        {props.title}
      </div>
      <div style={{ display: "flex", fontSize: 14, color: theme.subtext, marginTop: 4 }}>
        {props.subtitle}
      </div>
    </div>
  );
}

function Chip(props: { label: string; accent: string; center: Point }) {
  const w = 150;
  const h = 64;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        position: "absolute",
        left: props.center.x - w / 2,
        top: props.center.y - h / 2,
        width: w,
        height: h,
        borderRadius: 12,
        border: `2px solid ${props.accent}`,
        background: theme.bg,
        color: theme.text,
        fontSize: 16,
        fontWeight: 600,
      }}
    >
      {props.label}
    </div>
  );
}

function chipPair(center: Point, dx = 100, dy = 75): [Point, Point] {
  return [
    { x: center.x - dx, y: center.y + dy },
    { x: center.x + dx, y: center.y + dy },
  ];
}

export default function WorkerTopology() {
  const gw = 500;
  const gh = 300;

  const relay: Point = { x: 500, y: 400 };
  const signaling: Point = { x: 1900, y: 400 };
  const validator: Point = { x: 500, y: 1300 };
  const cp: Point = { x: 1900, y: 1300 };
  const chain: Point = { x: 1200, y: 850 };

  const [relayA, relayB] = chipPair(relay);
  const [sigA, sigB] = chipPair(signaling);
  const [valA, valB] = chipPair(validator);
  const [cpA, cpB] = chipPair(cp);

  // Relay -> control-plane is a real direct link, but a straight line between
  // their centers would cut through the chain box sitting at the diagram's
  // center -- route it around instead (down from relay on a column offset
  // from the relay<->validator line, across above the chain box, then down
  // into control-plane).
  const turnBend1: Point = { x: 650, y: 700 };
  const turnBend2: Point = { x: 1900, y: 700 };

  return (
    <div
      style={{
        display: "flex",
        width,
        height,
        padding: 48,
        background: theme.bg,
        fontFamily: "Inter",
        position: "relative",
      }}
    >
      {/* Legend */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          position: "absolute",
          left: 48,
          top: 16,
          fontSize: 14,
          color: theme.subtext,
          gap: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ display: "flex", width: 28, height: 3, background: theme.line }} />
          <div style={{ display: "flex", marginLeft: 8 }}>
            reads/writes shared chain state
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ display: "flex", width: 28, height: 4, background: theme.text }} />
          <div style={{ display: "flex", marginLeft: 8 }}>
            direct communication between groups
          </div>
        </div>
      </div>

      {/* Chain spokes -- thin, neutral */}
      <Line a={relay} b={chain} color={theme.line} thickness={2} />
      <Line a={signaling} b={chain} color={theme.line} thickness={2} />
      <Line a={validator} b={chain} color={theme.line} thickness={2} />
      <Line a={cp} b={chain} color={theme.line} thickness={2} />

      {/* Inter-group links -- only where a direct connection actually exists */}
      <Line a={relay} b={validator} color={theme.text} thickness={3} />
      <Line a={relay} b={turnBend1} color={theme.text} thickness={3} />
      <Line a={turnBend1} b={turnBend2} color={theme.text} thickness={3} />
      <Line a={turnBend2} b={cp} color={theme.text} thickness={3} />
      {/* No line: relay<->signaling, validator<->cp, validator<->signaling,
          cp<->signaling -- none of these communicate directly. */}

      <Label at={{ x: 500, y: 850 }} label="covert canary join (WS)" width={220} />
      <Label at={{ x: 1275, y: 700 }} label="TURN credential (HTTP)" width={220} />

      {/* Center -- chain */}
      <Box
        title="Smart contract"
        subtitle="room_manager · relay_registry · role_voting · cp_quorum_sig"
        accent={colors.chain}
        center={chain}
        width={340}
        height={140}
      />

      {/* Group rectangles, counter-clockwise from top-left: relay, validator, cp, signaling */}
      <GroupBox
        title="Relay"
        subtitle="SFU -- terminates & forwards client media"
        accent={colors.relay}
        center={relay}
        width={gw}
        height={gh}
      />
      <GroupBox
        title="Validator"
        subtitle="canary probes + fraud/QoE co-auditing"
        accent={colors.validator}
        center={validator}
        width={gw}
        height={gh}
      />
      <GroupBox
        title="Control plane"
        subtitle="chain-driven assignment & quorum attestation"
        accent={colors.cp}
        center={cp}
        width={gw}
        height={gh}
      />
      <GroupBox
        title="Signaling"
        subtitle="client admission gate"
        accent={colors.signaling}
        center={signaling}
        width={gw}
        height={gh}
      />

      {/* Intra-group links -- direct peer communication within a role */}
      <Line a={relayA} b={relayB} color={colors.relay} thickness={3} />
      <Line a={cpA} b={cpB} color={colors.cp} thickness={3} />
      <Line a={valA} b={valB} color={colors.validator} thickness={3} />
      {/* No line between the two signaling chips -- no peer protocol exists between signaling instances. */}

      <Label at={{ x: relay.x, y: relayA.y + 45 }} label="inter-relay pipe (WS)" width={200} />
      <Label at={{ x: cp.x, y: cpA.y + 45 }} label="quorum cosign (HTTP)" width={200} />
      <Label
        at={{ x: validator.x, y: valA.y + 45 }}
        label="divergence attestation (HTTP)"
        width={230}
      />

      {/* Worker symbols -- one chip per instance, inside its group */}
      <Chip label="primary" accent={colors.relay} center={relayA} />
      <Chip label="standby" accent={colors.relay} center={relayB} />

      <Chip label="instance A" accent={colors.signaling} center={sigA} />
      <Chip label="instance B" accent={colors.signaling} center={sigB} />

      <Chip label="co-auditor A" accent={colors.validator} center={valA} />
      <Chip label="co-auditor B" accent={colors.validator} center={valB} />

      <Chip label="leader" accent={colors.cp} center={cpA} />
      <Chip label="follower" accent={colors.cp} center={cpB} />
    </div>
  );
}
