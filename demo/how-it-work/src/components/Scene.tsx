import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import type { ScriptLine } from "../script";
import { theme } from "../theme";
import { TitleCard } from "./TitleCard";
import { PipelineCard } from "./PipelineCard";
import { TopologyCard } from "./TopologyCard";
import { EvaluationCard } from "./EvaluationCard";
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
        {line.kind === "pipeline" && line.steps ? (
          <PipelineCard title={line.title} steps={line.steps} />
        ) : line.kind === "topology" ? (
          <TopologyCard title={line.title} />
        ) : line.kind === "evaluation" ? (
          <EvaluationCard
            title={line.title}
            stats={line.stats ?? []}
            imageSections={line.imageSections ?? []}
          />
        ) : (
          <TitleCard title={line.title} subtitle={line.subtitle} />
        )}
        <Subtitle text={line.voiceover} durationInFrames={durationInFrames} />
      </AbsoluteFill>
    </Sequence>
  );
};
