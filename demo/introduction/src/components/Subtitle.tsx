import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

export const Subtitle: React.FC<{ text: string; durationInFrames: number }> = ({
  text,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fadeFrames = Math.round(fps * 0.25);

  const opacity = interpolate(
    frame,
    [0, fadeFrames, durationInFrames - fadeFrames, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 90,
        display: "flex",
        justifyContent: "center",
        padding: "0 220px",
        opacity,
      }}
    >
      <div
        style={{
          background: "rgba(0,0,0,0.55)",
          borderRadius: 12,
          padding: "16px 32px",
          fontFamily: theme.fontFamily,
          fontSize: 30,
          lineHeight: 1.35,
          color: theme.text,
          textAlign: "center",
        }}
      >
        {text}
      </div>
    </div>
  );
};
