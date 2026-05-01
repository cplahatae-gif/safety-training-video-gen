import { Composition } from "remotion";
import { MyVideo } from "./MyVideo.jsx";

export const RemotionRoot = () => {
  return (
    <Composition
      id="MyVideo"
      component={MyVideo}
      durationInFrames={180}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
