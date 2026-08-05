import React from "react";
import { Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import type { EvaluationImage, EvaluationSection, EvaluationStat } from "../script";

const STAT_COLORS = [theme.accent, theme.accentAlt, theme.success, theme.gold, theme.accent];

const StatBox: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  index: number;
  stat: EvaluationStat;
  delay: number;
}> = ({ x, y, w, h, index, stat, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const in_ = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(in_, [0, 1], [0, 1]);
  const translateY = interpolate(in_, [0, 1], [20, 0]);
  const color = STAT_COLORS[index % STAT_COLORS.length];

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
        gap: 8,
        borderRadius: 20,
        border: `2px solid ${color}`,
        background: "#ffffff",
        boxShadow: `0 12px 28px rgba(18, 23, 43, 0.12)`,
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontFamily: theme.fontFamily,
          fontSize: 34,
          fontWeight: 700,
          color,
          lineHeight: 1,
        }}
      >
        {stat.value}
      </div>
      <div
        style={{
          fontFamily: theme.fontFamily,
          fontSize: 16,
          color: theme.textDim,
        }}
      >
        {stat.label}
      </div>
    </div>
  );
};

const ImageTile: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  image: EvaluationImage;
  delay: number;
}> = ({ x, y, w, h, image, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const in_ = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(in_, [0, 1], [0, 1]);
  const scale = interpolate(in_, [0, 1], [0.96, 1]);
  const captionH = 32;

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
        borderRadius: 14,
        overflow: "hidden",
        border: `2px solid ${theme.backgroundAlt}`,
        boxShadow: `0 10px 24px rgba(18, 23, 43, 0.14)`,
        background: "#ffffff",
      }}
    >
      <Img
        src={staticFile(`images/evaluation/${image.src}`)}
        style={{
          width: "100%",
          height: h - captionH,
          objectFit: "cover",
          objectPosition: "top",
          display: "block",
        }}
      />
      <div
        style={{
          height: captionH,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: theme.fontFamily,
          fontSize: 15,
          fontWeight: 600,
          color: theme.textDim,
          background: theme.backgroundAlt,
        }}
      >
        {image.caption}
      </div>
    </div>
  );
};

const SectionRow: React.FC<{
  section: EvaluationSection;
  y: number;
  rowH: number;
  delayBase: number;
}> = ({ section, y, rowH, delayBase }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const headingIn = spring({ frame: frame - delayBase, fps, config: { damping: 200 } });
  const headingOpacity = interpolate(headingIn, [0, 1], [0, 1]);

  const margin = 100;
  const gap = 30;
  const headingH = 44;
  const n = section.images.length;
  const tileW = (1920 - 2 * margin - (n - 1) * gap) / n;
  // Relative to this row's own container, which already sits at `top: y`
  // (an absolute page coordinate) -- using an absolute y here too would
  // double-apply the row's offset and push tiles off-canvas.
  const tileY = headingH;
  const tileH = rowH - headingH;

  return (
    <div style={{ position: "absolute", left: 0, top: y, width: 1920, height: rowH }}>
      <div
        style={{
          position: "absolute",
          left: margin,
          top: 0,
          height: headingH,
          display: "flex",
          alignItems: "center",
          fontFamily: theme.fontFamily,
          fontSize: 26,
          fontWeight: 700,
          color: theme.text,
          opacity: headingOpacity,
        }}
      >
        {section.heading}
      </div>
      {section.images.map((image, i) => (
        <ImageTile
          key={image.src}
          x={margin + i * (tileW + gap)}
          y={tileY}
          w={tileW}
          h={tileH}
          image={image}
          delay={delayBase + 6 + i * 6}
        />
      ))}
    </div>
  );
};

export const EvaluationCard: React.FC<{
  title: string;
  stats: EvaluationStat[];
  imageSections: EvaluationSection[];
}> = ({ title, stats, imageSections }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const titleIn = spring({ frame, fps, config: { damping: 200 } });
  const titleOpacity = interpolate(titleIn, [0, 1], [0, 1]);

  const margin = 100;
  const statGap = 24;
  const statY = 260;
  const statH = 130;
  const n = Math.max(stats.length, 1);
  const statW = (1920 - 2 * margin - (n - 1) * statGap) / n;

  const rowsTop = statY + statH + 40;
  // Subtitle.tsx overlays a caption box anchored to `bottom: 90`, tall
  // enough for a multi-line voiceover -- stop well above it (matches
  // PipelineCard's boxY+boxH=740 precedent) instead of using the full
  // canvas height, or the image rows collide with the burned-in caption.
  const contentBottom = 800;
  const rowH = (contentBottom - rowsTop) / Math.max(imageSections.length, 1);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <h1
        style={{
          position: "absolute",
          top: 60,
          left: 0,
          right: 0,
          height: 180,
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
      {stats.map((stat, i) => (
        <StatBox
          key={stat.label}
          x={margin + i * (statW + statGap)}
          y={statY}
          w={statW}
          h={statH}
          index={i}
          stat={stat}
          delay={i * 6}
        />
      ))}
      {imageSections.map((section, i) => (
        <SectionRow
          key={section.heading}
          section={section}
          y={rowsTop + i * rowH}
          rowH={rowH}
          delayBase={stats.length * 6 + 10 + i * 20}
        />
      ))}
    </div>
  );
};
