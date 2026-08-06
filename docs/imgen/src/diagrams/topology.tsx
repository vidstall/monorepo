import React from "react";
import { Box, Label, Line, Point, theme } from "../shared";

const colors = {
  user: "#2563eb",
  worker: "#16a34a",
  contract: "#d97706",
  mon: "#7c3aed",
};

export default function SystemArchitecture() {
  const W = 1200;
  const H = 900;

  const contract: Point = { x: W / 2, y: 100 };
  const client: Point = { x: 210, y: 615 };
  const worker: Point = { x: 990, y: 615 };
  const monitoring: Point = { x: W / 2, y: 855 };

  return (
    <div
      style={{
        display: "flex",
        width: W,
        height: H,
        padding: 48,
        background: theme.bg,
        fontFamily: "Inter",
        position: "relative",
      }}
    >
      {/* Triangle edges -- drawn first so the boxes and labels sit on top */}
      <Line a={contract} b={client} color={colors.user} />
      <Line a={contract} b={worker} color={colors.worker} />
      <Line a={client} b={worker} color={colors.contract} />

      <Label at={{ x: 405, y: 358 }} label="client looks up available workers" />
      <Label at={{ x: 795, y: 358 }} label="worker looks up clients & other workers" />
      <Label at={{ x: 600, y: 660 }} label="call audio/video flows directly" />

      <Box
        title="Contract"
        subtitle="shared directory both sides read & write"
        accent={colors.contract}
        center={contract}
        width={340}
        height={120}
      />
      <Box
        title="Client"
        subtitle="joins a call via the website"
        accent={colors.user}
        center={client}
        width={300}
        height={110}
      />
      <Box
        title="Worker"
        subtitle="carries calls, checks other workers"
        accent={colors.worker}
        center={worker}
        width={300}
        height={110}
      />

      {/* Monitoring -- separate observer, not part of the triangle, no line drawn to it */}
      <Box
        title="Monitoring"
        subtitle="watches call quality across clients & workers"
        accent={colors.mon}
        center={monitoring}
        width={520}
        height={110}
      />
    </div>
  );
}
