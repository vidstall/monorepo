import "./index.css";
import { Composition } from "remotion";
import { Introduction, totalDurationInFrames } from "./Introduction";

const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Introduction"
        component={Introduction}
        durationInFrames={totalDurationInFrames(FPS)}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
