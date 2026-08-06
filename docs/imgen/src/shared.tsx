import React from "react";

export const theme = {
  bg: "#ffffff",
  panel: "#f8fafc",
  text: "#0f172a",
  subtext: "#475569",
  line: "#94a3b8",
};

export type Point = { x: number; y: number };

export function Box(props: {
  title: string;
  subtitle?: string;
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
        justifyContent: "center",
        alignItems: "center",
        position: "absolute",
        left: props.center.x - props.width / 2,
        top: props.center.y - props.height / 2,
        width: props.width,
        height: props.height,
        padding: "18px 16px",
        borderRadius: 14,
        background: theme.panel,
        border: `2px solid ${props.accent}`,
        color: theme.text,
        textAlign: "center",
      }}
    >
      <div style={{ display: "flex", fontSize: 22, fontWeight: 700 }}>{props.title}</div>
      {props.subtitle && (
        <div style={{ display: "flex", fontSize: 14, color: theme.subtext, marginTop: 6 }}>
          {props.subtitle}
        </div>
      )}
    </div>
  );
}

// Straight connecting line drawn as a rotated rectangle between two points --
// satori has no <line>/<svg> primitive, so this is a div sized to the
// distance between the points and rotated to the angle between them.
export function Line(props: { a: Point; b: Point; color?: string; thickness?: number }) {
  const thickness = props.thickness ?? 3;
  const dx = props.b.x - props.a.x;
  const dy = props.b.y - props.a.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  // satori rotates around the element's own center regardless of
  // transform-origin, so size/position the div centered on the midpoint of
  // a/b (its default center pivot) rather than anchoring at point a.
  const midX = (props.a.x + props.b.x) / 2;
  const midY = (props.a.y + props.b.y) / 2;
  return (
    <div
      style={{
        display: "flex",
        position: "absolute",
        left: midX - length / 2,
        top: midY - thickness / 2,
        width: length,
        height: thickness,
        background: props.color ?? theme.line,
        transform: `rotate(${angle}deg)`,
      }}
    />
  );
}

export function Label(props: { at: Point; label: string; width?: number }) {
  return (
    <div
      style={{
        display: "flex",
        position: "absolute",
        left: props.at.x - (props.width ?? 240) / 2,
        top: props.at.y - 20,
        width: props.width ?? 240,
        justifyContent: "center",
        textAlign: "center",
        fontSize: 14,
        color: theme.subtext,
        background: theme.bg,
        padding: "4px 8px",
        borderRadius: 6,
      }}
    >
      {props.label}
    </div>
  );
}
