import React from "react";
import { Audio } from "@remotion/media";
import { Sequence, staticFile, useVideoConfig } from "remotion";
import { timing, type Timeline } from "../timeline";

// Как в референсе: «пинг» при появлении карточки и щелчки клавиш, пока печатается комментарий.
// Файлы — scripts/make_sfx.py.
const PING_VOLUME = 0.35;
const TYPING_VOLUME = 0.6;

export const CardSfx: React.FC<{ timeline: Timeline }> = ({ timeline }) => {
  const { fps } = useVideoConfig();
  const typeDelay = Math.round(timing.typeDelay * fps);
  return (
    <>
      {timeline.segments.map((seg, i) =>
        seg.kind === "card" ? (
          <React.Fragment key={i}>
            <Sequence from={seg.from} durationInFrames={Math.min(seg.duration, Math.round(0.5 * fps))} layout="none">
              <Audio src={staticFile("sfx/card.wav")} volume={PING_VOLUME} />
            </Sequence>
            {seg.typingFrames > 0 ? (
              <Sequence from={seg.from + typeDelay} durationInFrames={seg.typingFrames} layout="none">
                <Audio src={staticFile("sfx/typing.wav")} volume={TYPING_VOLUME} loop />
              </Sequence>
            ) : null}
          </React.Fragment>
        ) : null,
      )}
    </>
  );
};
