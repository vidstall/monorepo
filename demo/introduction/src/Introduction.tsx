import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { script } from "./script";
import durations from "./durations.json";
import { Scene } from "./components/Scene";
import { theme } from "./theme";

const GAP_SECONDS = 0.4;

export const layoutScenes = (fps: number) => {
  let cursor = 0;
  return script.map((line) => {
    const seconds =
      (durations as Record<string, number>)[line.id] + line.holdSeconds;
    const durationInFrames = Math.round(seconds * fps);
    const from = cursor;
    cursor += durationInFrames + Math.round(GAP_SECONDS * fps);
    return { line, from, durationInFrames };
  });
};

export const totalDurationInFrames = (fps: number) => {
  const scenes = layoutScenes(fps);
  const last = scenes[scenes.length - 1];
  return last.from + last.durationInFrames;
};

export const Introduction: React.FC = () => {
  const { fps } = useVideoConfig();
  const scenes = layoutScenes(fps);

  return (
    <AbsoluteFill style={{ backgroundColor: theme.background }}>
      {scenes.map(({ line, from, durationInFrames }) => (
        <Scene
          key={line.id}
          line={line}
          from={from}
          durationInFrames={durationInFrames}
        />
      ))}
    </AbsoluteFill>
  );
};
