import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import type { ScriptLine } from "../script";
import { theme } from "../theme";
import { TitleCard } from "./TitleCard";
import { DiagramCard } from "./DiagramCard";
import { Subtitle } from "./Subtitle";

export const Scene: React.FC<{
  line: ScriptLine;
  from: number;
  durationInFrames: number;
}> = ({ line, from, durationInFrames }) => {
  return (
    <Sequence from={from} durationInFrames={durationInFrames} name={line.id}>
      <AbsoluteFill style={{ backgroundColor: theme.background }}>
        <Audio src={staticFile(`audio/${line.id}.wav`)} />
        {line.kind === "diagram" && line.diagram ? (
          <DiagramCard title={line.title} diagram={line.diagram} />
        ) : (
          <TitleCard title={line.title} subtitle={line.subtitle} />
        )}
        <Subtitle text={line.voiceover} durationInFrames={durationInFrames} />
      </AbsoluteFill>
    </Sequence>
  );
};
