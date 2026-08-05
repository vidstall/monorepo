import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

export const TitleCard: React.FC<{ title: string; subtitle?: string }> = ({
  title,
  subtitle,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleIn = spring({ frame, fps, config: { damping: 200 } });
  const titleOpacity = interpolate(titleIn, [0, 1], [0, 1]);
  const titleY = interpolate(titleIn, [0, 1], [24, 0]);

  const subtitleIn = spring({
    frame: frame - 8,
    fps,
    config: { damping: 200 },
  });
  const subtitleOpacity = interpolate(subtitleIn, [0, 1], [0, 1]);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
        padding: "0 160px",
        textAlign: "center",
      }}
    >
      <h1
        style={{
          fontFamily: theme.fontFamily,
          fontSize: 88,
          fontWeight: 700,
          color: theme.text,
          lineHeight: 1.15,
          whiteSpace: "pre-line",
          margin: 0,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
        }}
      >
        {title}
      </h1>
      {subtitle ? (
        <p
          style={{
            fontFamily: theme.fontFamily,
            fontSize: 36,
            color: theme.accent,
            margin: 0,
            opacity: subtitleOpacity,
          }}
        >
          {subtitle}
        </p>
      ) : null}
    </div>
  );
};
