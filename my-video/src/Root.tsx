import "./index.css";
import { Composition } from "remotion";
import { MyComposition } from "./Composition";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 11s ad @ 30fps = 330 frames, 1080x1080 for Instagram/TikTok square */}
      <Composition
        id="AiCashAd"
        component={MyComposition}
        durationInFrames={330}
        fps={30}
        width={1080}
        height={1080}
      />
      {/* 16:9 widescreen version for YouTube/Twitter */}
      <Composition
        id="AiCashAdWide"
        component={MyComposition}
        durationInFrames={330}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
