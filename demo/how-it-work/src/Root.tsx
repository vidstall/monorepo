import "./index.css";
import { Composition } from "remotion";
import { HowItWorks, totalDurationInFrames } from "./HowItWorks";

const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="HowItWorks"
        component={HowItWorks}
        durationInFrames={totalDurationInFrames(FPS)}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
