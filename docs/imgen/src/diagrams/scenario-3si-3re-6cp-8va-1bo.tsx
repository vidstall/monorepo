import React from "react";
import { Box, Label, Line, Point, theme } from "../shared";

export const width = 2260;
export const height = 1340;

const colors = {
  host: "#475569",
  signaling: "#2563eb",
  relay: "#16a34a",
  cp: "#7c3aed",
  validator: "#0d9488",
  bot: "#ea580c",
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
        paddingTop: 20,
      }}
    >
      <div style={{ display: "flex", fontSize: 22, fontWeight: 700, color: theme.text }}>
        {props.title}
      </div>
      <div style={{ display: "flex", fontSize: 13, color: theme.subtext, marginTop: 4 }}>
        {props.subtitle}
      </div>
    </div>
  );
}

function Chip(props: { label: string; accent: string; center: Point }) {
  const w = 150;
  const h = 56;
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
        fontSize: 15,
        fontWeight: 600,
        textAlign: "center",
      }}
    >
      {props.label}
    </div>
  );
}

function hostChips(center: Point, labels: [string, string][], rowDy = 40): Point[] {
  // Up to 5 chips per host: 3 on a top row, 2 on a bottom row, centered.
  const rowOffsets3 = [-190, 0, 190];
  const rowOffsets2 = [-95, 95];
  const points: Point[] = [];
  const top = labels.slice(0, 3);
  const bottom = labels.slice(3);
  top.forEach((_, i) => points.push({ x: center.x + rowOffsets3[i], y: center.y - rowDy }));
  bottom.forEach((_, i) => points.push({ x: center.x + rowOffsets2[i], y: center.y + rowDy + 20 }));
  return points;
}

export default function Scenario3si3re6cp8va1bo() {
  const hostW = 620;
  const hostH = 440;

  const host1: Point = { x: 400, y: 420 };
  const host2: Point = { x: 1130, y: 420 };
  const host3: Point = { x: 1860, y: 420 };
  const host4: Point = { x: 1130, y: 1020 };
  const bot: Point = { x: 1860, y: 1020 };

  const colocatedLabels: [string, string][] = [
    ["signaling", colors.signaling],
    ["relay", colors.relay],
    ["cp-daemon #1", colors.cp],
    ["cp-daemon #2", colors.cp],
    ["validator-daemon", colors.validator],
  ];

  const host1Chips = hostChips(host1, colocatedLabels);
  const host2Chips = hostChips(host2, colocatedLabels);
  const host3Chips = hostChips(host3, colocatedLabels);

  const host4Labels: [string, string][] = [
    ["validator-daemon #1", colors.validator],
    ["validator-daemon #2", colors.validator],
    ["validator-daemon #3", colors.validator],
    ["validator-daemon #4", colors.validator],
    ["validator-daemon #5", colors.validator],
  ];
  const host4Chips = hostChips(host4, host4Labels, 60);

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
            akamai.toml worker (cloud fleet, provisioned by `vidctl scenario apply`)
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ display: "flex", width: 28, height: 4, background: colors.bot }} />
          <div style={{ display: "flex", marginLeft: 8 }}>
            local process, not in akamai.toml (`vidctl utils bot start`)
          </div>
        </div>
      </div>

      {/* Bot -> fleet: creates + joins a room via the client-facing signaling+relay protocol */}
      <Line a={bot} b={host2} color={colors.bot} thickness={3} />
      <Label
        at={{ x: (bot.x + host2.x) / 2, y: (bot.y + host2.y) / 2 - 30 }}
        label="creates room, joins via signaling -> relay (client protocol)"
        width={320}
      />

      <GroupBox
        title="Host 001"
        subtitle="akamai · g6-standard-4"
        accent={colors.host}
        center={host1}
        width={hostW}
        height={hostH}
      />
      <GroupBox
        title="Host 002"
        subtitle="akamai · g6-standard-4"
        accent={colors.host}
        center={host2}
        width={hostW}
        height={hostH}
      />
      <GroupBox
        title="Host 003"
        subtitle="akamai · g6-standard-4"
        accent={colors.host}
        center={host3}
        width={hostW}
        height={hostH}
      />
      <GroupBox
        title="Host 004"
        subtitle="akamai · g6-standard-4 · validator-only (quorum reach)"
        accent={colors.host}
        center={host4}
        width={hostW}
        height={320}
      />
      <GroupBox
        title="Local bot"
        subtitle="operator machine · services/worker/apps/bot"
        accent={colors.bot}
        center={bot}
        width={400}
        height={320}
      />

      {[host1Chips, host2Chips, host3Chips].map((chips, hostIdx) =>
        chips.map((point, i) => (
          <Chip
            key={`host${hostIdx}-${i}`}
            label={colocatedLabels[i][0]}
            accent={colocatedLabels[i][1]}
            center={point}
          />
        ))
      )}

      {host4Chips.map((point, i) => (
        <Chip
          key={`host4-${i}`}
          label={host4Labels[i][0].replace("validator-daemon ", "")}
          accent={colors.validator}
          center={point}
        />
      ))}
    </div>
  );
}
