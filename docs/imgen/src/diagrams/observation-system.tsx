import React from "react";
import { Box, Label, Line, Point, theme } from "../shared";

export const width = 1850;
export const height = 980;

const colors = {
  contract: "#d97706",
  worker: "#16a34a",
  client: "#db2777",
  metrics: "#2563eb",
  logs: "#4f46e5",
  traces: "#0d9488",
  grafana: "#ea580c",
};

function lerp(a: Point, b: Point, t: number): Point {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

export default function ObservationSystem() {
  // Column 1 -- data sources
  const contract: Point = { x: 230, y: 150 };
  const worker: Point = { x: 230, y: 500 };
  const client: Point = { x: 230, y: 850 };

  // Column 2 -- observation nodes
  const metrics: Point = { x: 900, y: 150 };
  const logs: Point = { x: 900, y: 500 };
  const traces: Point = { x: 900, y: 850 };

  // Column 3 -- final dashboard
  const grafana: Point = { x: 1600, y: 500 };

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
      {/* Column headers */}
      <div
        style={{
          display: "flex",
          position: "absolute",
          left: 230 - 160,
          top: 20,
          width: 320,
          justifyContent: "center",
          fontSize: 15,
          fontWeight: 700,
          letterSpacing: 1,
          textTransform: "uppercase",
          color: theme.subtext,
        }}
      >
        1. Data sources
      </div>
      <div
        style={{
          display: "flex",
          position: "absolute",
          left: 900 - 160,
          top: 20,
          width: 320,
          justifyContent: "center",
          fontSize: 15,
          fontWeight: 700,
          letterSpacing: 1,
          textTransform: "uppercase",
          color: theme.subtext,
        }}
      >
        2. Observation nodes
      </div>
      <div
        style={{
          display: "flex",
          position: "absolute",
          left: 1600 - 170,
          top: 20,
          width: 340,
          justifyContent: "center",
          fontSize: 15,
          fontWeight: 700,
          letterSpacing: 1,
          textTransform: "uppercase",
          color: theme.subtext,
        }}
      >
        3. Dashboard
      </div>

      {/* Edges -- drawn first so the boxes and labels sit on top */}
      {/* column 1 -> column 2 */}
      <Line a={contract} b={metrics} />

      <Line a={worker} b={metrics} />
      <Line a={worker} b={logs} />
      <Line a={worker} b={traces} />

      <Line a={client} b={metrics} />
      <Line a={client} b={logs} />
      <Line a={client} b={traces} />

      {/* column 2 -> column 3 */}
      <Line a={metrics} b={grafana} />
      <Line a={logs} b={grafana} />
      <Line a={traces} b={grafana} />

      <Label at={{ x: 565, y: 150 }} label="on-chain metrics" />

      <Label at={lerp(worker, metrics, 0.3)} label="metric scrape" width={200} />
      <Label at={{ x: 565, y: 500 }} label="log shipment" width={200} />
      <Label at={lerp(worker, traces, 0.7)} label="trace export" width={200} />

      <Label at={lerp(client, metrics, 0.75)} label="metrics" width={160} />
      <Label at={lerp(client, logs, 0.3)} label="logs" width={160} />
      <Label at={{ x: 565, y: 850 }} label="traces" width={160} />

      {/* Column 1 -- data sources */}
      <Box
        title="Smart contract"
        subtitle="on-chain ledger"
        accent={colors.contract}
        center={contract}
        width={300}
        height={110}
      />
      <Box
        title="Worker"
        subtitle="relay · signaling · control-plane · validator · synthetic load agents"
        accent={colors.worker}
        center={worker}
        width={320}
        height={140}
      />
      <Box
        title="End-user client"
        subtitle="browser"
        accent={colors.client}
        center={client}
        width={280}
        height={100}
      />

      {/* Column 2 -- observation nodes */}
      <Box
        title="Metrics database"
        subtitle="Prometheus"
        accent={colors.metrics}
        center={metrics}
        width={300}
        height={110}
      />
      <Box
        title="Log aggregation store"
        subtitle="Loki"
        accent={colors.logs}
        center={logs}
        width={300}
        height={110}
      />
      <Box
        title="Trace aggregation store"
        subtitle="Tempo"
        accent={colors.traces}
        center={traces}
        width={300}
        height={110}
      />

      {/* Column 3 -- final dashboard */}
      <Box
        title="Grafana dashboard"
        subtitle="unified query & visualization layer"
        accent={colors.grafana}
        center={grafana}
        width={340}
        height={220}
      />
    </div>
  );
}
