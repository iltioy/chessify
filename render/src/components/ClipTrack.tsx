import React from "react";
import { Video } from "@remotion/media";
import { Freeze, Sequence, staticFile, useVideoConfig } from "remotion";
import type { Timeline } from "../timeline";

// Один и тот же исходник проигрывается кусками: play — с нужного места, card/summary — стоп-кадр без звука.
// Фон рендерится той же функцией, чтобы оставаться синхронным с клипом.
export const ClipTrack: React.FC<{
  src: string;
  timeline: Timeline;
  muted?: boolean;
  style: React.CSSProperties;
}> = ({ src, timeline, muted, style }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {timeline.segments.map((seg, i) =>
        seg.kind === "play" ? (
          <Sequence key={i} from={seg.from} durationInFrames={seg.duration} layout="none">
            <Video src={staticFile(src)} trimBefore={Math.round(seg.srcStart * fps)} muted={muted} style={style} objectFit="cover" />
          </Sequence>
        ) : (
          <Sequence key={i} from={seg.from} durationInFrames={seg.duration} layout="none">
            <Freeze frame={0}>
              <Video src={staticFile(src)} trimBefore={Math.max(0, Math.round(seg.srcAt * fps) - 1)} muted style={style} objectFit="cover" />
            </Freeze>
          </Sequence>
        ),
      )}
    </>
  );
};
