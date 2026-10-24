import { Composition } from "remotion";
import { ChessScene, FPS, calculateChessSceneMetadata } from "./ChessScene";
import type { Scene } from "./generated/scene";
import referenceScene from "./fixtures/reference.scene.json";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ChessScene"
        component={ChessScene}
        durationInFrames={300}
        fps={FPS}
        width={1080}
        height={1920}
        defaultProps={{ scene: referenceScene as Scene }}
        calculateMetadata={calculateChessSceneMetadata}
      />
    </>
  );
};
