import React from "react";
import { Audio } from "@remotion/media";
import { staticFile, useVideoConfig } from "remotion";
import type { Timeline } from "../timeline";

// Музыка тише под речью и вдвое громче на карточках и итогах; переходы плавные.
const RAMP = 0.4; // секунды на смену громкости
const FADE_IN = 1;
const FADE_OUT = 1.5;

export const MusicTrack: React.FC<{ src: string; volume: number; timeline: Timeline }> = ({ src, volume, timeline }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const ramp = RAMP * fps;
  const target = (kind: string) => (kind === "play" ? volume : Math.min(1, volume * 2));

  const at = (frame: number) => {
    const segs = timeline.segments;
    const i = Math.max(0, segs.findIndex((s) => frame >= s.from && frame < s.from + s.duration));
    const seg = segs[i];
    let v = target(seg.kind);
    // Плавный переход от громкости предыдущего сегмента.
    if (i > 0 && frame - seg.from < ramp) {
      const t = (frame - seg.from) / ramp;
      v = target(segs[i - 1].kind) * (1 - t) + v * t;
    }
    const fadeIn = Math.min(1, frame / (FADE_IN * fps));
    const fadeOut = Math.min(1, (durationInFrames - frame) / (FADE_OUT * fps));
    return v * Math.max(0, Math.min(fadeIn, fadeOut));
  };

  return <Audio src={staticFile(src)} loop volume={at} />;
};
