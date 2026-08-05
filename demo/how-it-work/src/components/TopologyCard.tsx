import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

const Box: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub?: string;
  color: string;
  delay: number;
}> = ({ x, y, w, h, label, sub, color, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const in_ = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(in_, [0, 1], [0, 1]);
  const scale = interpolate(in_, [0, 1], [0.85, 1]);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        opacity,
        transform: `scale(${scale})`,
        transformOrigin: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        borderRadius: 20,
        border: `2px solid ${color}`,
        background: "#ffffff",
        boxShadow: "0 12px 28px rgba(18, 23, 43, 0.12)",
      }}
    >
      <div
        style={{
          fontFamily: theme.fontFamily,
          fontSize: 28,
          fontWeight: 700,
          color: theme.text,
        }}
      >
        {label}
      </div>
      {sub ? (
        <div
          style={{
            fontFamily: theme.fontFamily,
            fontSize: 18,
            color: theme.textDim,
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
};

const Arrow: React.FC<{
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  delay: number;
  dashed?: boolean;
}> = ({ x1, y1, x2, y2, color, delay, dashed }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const in_ = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const progress = interpolate(in_, [0, 1], [0, 1]);
  const cx = x1 + (x2 - x1) * progress;
  const cy = y1 + (y2 - y1) * progress;

  return (
    <svg
      style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}
      width={1}
      height={1}
    >
      <defs>
        <marker
          id={`topo-arrow-${x1}-${y1}-${x2}-${y2}`}
          markerWidth="10"
          markerHeight="10"
          refX="8"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L9,3 z" fill={color} />
        </marker>
      </defs>
      <line
        x1={x1}
        y1={y1}
        x2={cx}
        y2={cy}
        stroke={color}
        strokeWidth={3}
        strokeDasharray={dashed ? "8 8" : undefined}
        opacity={progress > 0.02 ? 1 : 0}
        markerEnd={
          progress > 0.9 ? `url(#topo-arrow-${x1}-${y1}-${x2}-${y2})` : undefined
        }
      />
    </svg>
  );
};

export const TopologyCard: React.FC<{ title: string }> = ({ title }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const titleIn = spring({ frame, fps, config: { damping: 200 } });
  const titleOpacity = interpolate(titleIn, [0, 1], [0, 1]);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <h1
        style={{
          position: "absolute",
          top: 70,
          left: 0,
          right: 0,
          height: 260,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          fontFamily: theme.fontFamily,
          fontSize: 52,
          lineHeight: 1.25,
          fontWeight: 700,
          color: theme.text,
          whiteSpace: "pre-line",
          margin: 0,
          opacity: titleOpacity,
        }}
      >
        {title}
      </h1>
      <div style={{ position: "absolute", inset: 0 }}>
        <Box
          x={60}
          y={340}
          w={300}
          h={120}
          label="Client"
          sub="creates a room"
          color={theme.accent}
          delay={0}
        />
        <Box
          x={60}
          y={610}
          w={300}
          h={120}
          label="Bot"
          sub="same as a client"
          color={theme.accent}
          delay={6}
        />
        <Box
          x={800}
          y={340}
          w={320}
          h={130}
          label="Sui Chain"
          sub="rooms · registries"
          color={theme.accent}
          delay={14}
        />
        <Box
          x={1540}
          y={310}
          w={320}
          h={120}
          label="Control Plane"
          sub="assigns relays"
          color={theme.accentAlt}
          delay={22}
        />
        <Box
          x={1540}
          y={600}
          w={320}
          h={120}
          label="Relay Node"
          sub="SFU / MCU"
          color={theme.gold}
          delay={30}
        />
        <Box
          x={800}
          y={610}
          w={320}
          h={120}
          label="Validator"
          sub="secretly audits"
          color={theme.accentAlt}
          delay={38}
        />

        <Arrow x1={360} y1={400} x2={800} y2={400} color={theme.textDim} delay={18} />
        <Arrow x1={360} y1={670} x2={800} y2={445} color={theme.textDim} delay={22} />
        <Arrow x1={1120} y1={390} x2={1540} y2={370} color={theme.textDim} delay={26} />
        <Arrow x1={1700} y1={430} x2={1700} y2={600} color={theme.textDim} delay={34} />
        <Arrow
          x1={1120}
          y1={670}
          x2={1540}
          y2={660}
          color={theme.accentAlt}
          delay={42}
          dashed
        />
        <Arrow
          x1={1620}
          y1={600}
          x2={1140}
          y2={430}
          color={theme.success}
          delay={48}
          dashed
        />
      </div>
    </div>
  );
};
