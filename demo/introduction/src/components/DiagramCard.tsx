import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import type { DiagramId } from "../script";

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
        borderRadius: 20,
        border: `2px solid ${color}`,
        background: "rgba(255,255,255,0.03)",
        boxShadow: `0 0 40px ${color}33`,
        gap: 6,
      }}
    >
      <div
        style={{
          fontFamily: theme.fontFamily,
          fontSize: 30,
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
            fontSize: 20,
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
          id={`arrow-${x1}-${y1}-${x2}-${y2}`}
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
          progress > 0.9 ? `url(#arrow-${x1}-${y1}-${x2}-${y2})` : undefined
        }
      />
    </svg>
  );
};

const Diagram: React.FC<{ diagram: DiagramId }> = ({ diagram }) => {
  switch (diagram) {
    case "chain-vs-relay":
      return (
        <>
          <Box
            x={280}
            y={420}
            w={420}
            h={200}
            label="Sui Blockchain"
            sub="coordination · trust · money"
            color={theme.accent}
            delay={0}
          />
          <Box
            x={980}
            y={420}
            w={420}
            h={200}
            label="Relay Nodes"
            sub="video · audio (off-chain)"
            color={theme.gold}
            delay={10}
          />
          <Arrow x1={700} y1={520} x2={980} y2={520} color={theme.textDim} delay={20} />
        </>
      );
    case "topology":
      return (
        <>
          <Box
            x={60}
            y={380}
            w={320}
            h={130}
            label="Users"
            sub="register on-chain"
            color={theme.accent}
            delay={0}
          />
          <Box
            x={800}
            y={340}
            w={320}
            h={130}
            label="Sui Chain"
            sub="rooms · registries"
            color={theme.accent}
            delay={8}
          />
          <Box
            x={1540}
            y={340}
            w={320}
            h={130}
            label="Control Plane"
            sub="assigns relays"
            color={theme.accentAlt}
            delay={16}
          />
          <Box
            x={1540}
            y={610}
            w={320}
            h={130}
            label="Relay Node"
            sub="SFU / MCU"
            color={theme.gold}
            delay={24}
          />
          <Box
            x={800}
            y={610}
            w={320}
            h={130}
            label="Validator"
            sub="secretly audits"
            color={theme.accentAlt}
            delay={32}
          />
          <Arrow x1={380} y1={445} x2={800} y2={405} color={theme.textDim} delay={12} />
          <Arrow x1={1120} y1={405} x2={1540} y2={405} color={theme.textDim} delay={20} />
          <Arrow x1={1700} y1={470} x2={1700} y2={610} color={theme.textDim} delay={28} />
          <Arrow
            x1={1120}
            y1={675}
            x2={1540}
            y2={675}
            color={theme.accentAlt}
            delay={36}
            dashed
          />
          <Arrow
            x1={1620}
            y1={610}
            x2={1140}
            y2={440}
            color="#3ddc84"
            delay={44}
            dashed
          />
        </>
      );
    case "cp-assign":
      return (
        <>
          <Box
            x={280}
            y={360}
            w={380}
            h={160}
            label="Control Plane"
            sub="votes on assignment"
            color={theme.accent}
            delay={0}
          />
          <Box
            x={280}
            y={570}
            w={380}
            h={160}
            label="Room"
            sub="shared object"
            color={theme.accentAlt}
            delay={8}
          />
          <Box
            x={960}
            y={450}
            w={420}
            h={160}
            label="Relay (SFU / MCU)"
            sub="assigned to serve room"
            color={theme.gold}
            delay={18}
          />
          <Arrow x1={660} y1={440} x2={960} y2={490} color={theme.textDim} delay={26} />
          <Arrow x1={660} y1={650} x2={960} y2={570} color={theme.textDim} delay={30} />
        </>
      );
    case "validator-audit":
      return (
        <>
          <Box
            x={980}
            y={420}
            w={420}
            h={180}
            label="Relay Node"
            sub="forwarding media"
            color={theme.gold}
            delay={0}
          />
          <Box
            x={280}
            y={420}
            w={420}
            h={180}
            label="Validator"
            sub="secretly measures quality"
            color={theme.accentAlt}
            delay={10}
          />
          <Arrow
            x1={700}
            y1={510}
            x2={980}
            y2={510}
            color={theme.accentAlt}
            delay={22}
            dashed
          />
        </>
      );
    case "rewards":
      return (
        <>
          <Box
            x={280}
            y={420}
            w={420}
            h={180}
            label="Relay Node"
            sub="honest work"
            color={theme.gold}
            delay={0}
          />
          <Box
            x={980}
            y={420}
            w={420}
            h={180}
            label="DVCONF Tokens"
            sub="work-based reward"
            color="#3ddc84"
            delay={12}
          />
          <Arrow x1={700} y1={510} x2={980} y2={510} color="#3ddc84" delay={24} />
        </>
      );
    case "slashing":
      return (
        <>
          <Box
            x={280}
            y={420}
            w={420}
            h={180}
            label="Relay Node"
            sub="quality → 0"
            color={theme.danger}
            delay={0}
          />
          <Box
            x={980}
            y={420}
            w={420}
            h={180}
            label="Stake Slashed"
            sub="cheating costs money"
            color={theme.danger}
            delay={12}
          />
          <Arrow x1={700} y1={510} x2={980} y2={510} color={theme.danger} delay={24} />
        </>
      );
    default:
      return null;
  }
};

export const DiagramCard: React.FC<{
  title: string;
  diagram: DiagramId;
}> = ({ title, diagram }) => {
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
        <Diagram diagram={diagram} />
      </div>
    </div>
  );
};
