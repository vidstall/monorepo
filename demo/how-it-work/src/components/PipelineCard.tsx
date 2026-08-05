import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import type { PipelineStep } from "../script";

const STEP_COLORS = [theme.accent, theme.accentAlt, theme.gold, theme.success];

const StepNode: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  index: number;
  step: PipelineStep;
  delay: number;
}> = ({ x, y, w, h, index, step, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const in_ = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(in_, [0, 1], [0, 1]);
  const translateY = interpolate(in_, [0, 1], [20, 0]);
  const color = STEP_COLORS[index % STEP_COLORS.length];

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        opacity,
        transform: `translateY(${translateY}px)`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        borderRadius: 20,
        border: `2px solid ${color}`,
        background: "#ffffff",
        boxShadow: `0 12px 28px rgba(18, 23, 43, 0.12)`,
        padding: "0 18px",
        textAlign: "center",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: -26,
          width: 52,
          height: 52,
          borderRadius: "50%",
          background: color,
          color: "#ffffff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: theme.fontFamily,
          fontSize: 24,
          fontWeight: 700,
          boxShadow: `0 6px 16px ${color}66`,
        }}
      >
        {index + 1}
      </div>
      <div
        style={{
          fontFamily: theme.fontFamily,
          fontSize: 26,
          fontWeight: 700,
          color: theme.text,
          lineHeight: 1.2,
        }}
      >
        {step.label}
      </div>
      {step.sub ? (
        <div
          style={{
            fontFamily: theme.fontFamily,
            fontSize: 18,
            color: theme.textDim,
          }}
        >
          {step.sub}
        </div>
      ) : null}
    </div>
  );
};

const StepArrow: React.FC<{ x1: number; x2: number; y: number; delay: number }> = ({
  x1,
  x2,
  y,
  delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const in_ = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const progress = interpolate(in_, [0, 1], [0, 1]);
  const cx = x1 + (x2 - x1) * progress;

  return (
    <svg
      style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}
      width={1}
      height={1}
    >
      <defs>
        <marker
          id={`step-arrow-${x1}-${x2}-${y}`}
          markerWidth="10"
          markerHeight="10"
          refX="8"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L9,3 z" fill={theme.textDim} />
        </marker>
      </defs>
      <line
        x1={x1}
        y1={y}
        x2={cx}
        y2={y}
        stroke={theme.textDim}
        strokeWidth={3}
        opacity={progress > 0.02 ? 1 : 0}
        markerEnd={
          progress > 0.9 ? `url(#step-arrow-${x1}-${x2}-${y})` : undefined
        }
      />
    </svg>
  );
};

export const PipelineCard: React.FC<{ title: string; steps: PipelineStep[] }> = ({
  title,
  steps,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const titleIn = spring({ frame, fps, config: { damping: 200 } });
  const titleOpacity = interpolate(titleIn, [0, 1], [0, 1]);

  const margin = 100;
  const gap = 40;
  const n = steps.length;
  const boxW = (1920 - 2 * margin - (n - 1) * gap) / n;
  const boxH = 200;
  const boxY = 540;
  const centerY = boxY + boxH / 2;

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
        {steps.map((step, i) => {
          const x = margin + i * (boxW + gap);
          return (
            <StepNode
              key={step.label}
              x={x}
              y={boxY}
              w={boxW}
              h={boxH}
              index={i}
              step={step}
              delay={i * 10}
            />
          );
        })}
        {steps.slice(0, -1).map((step, i) => {
          const x1 = margin + i * (boxW + gap) + boxW;
          const x2 = x1 + gap;
          return (
            <StepArrow
              key={`arrow-${step.label}`}
              x1={x1}
              x2={x2}
              y={centerY}
              delay={i * 10 + 6}
            />
          );
        })}
      </div>
    </div>
  );
};
