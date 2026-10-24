import React, { useMemo } from "react";
import { AbsoluteFill, CalculateMetadataFunction, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Scene } from "./generated/scene";
import { BASE_HEIGHT, BASE_WIDTH, categories, fontFamily } from "./theme";
import { buildTimeline, frameState, moveLabel, type Timeline } from "./timeline";
import { ClipTrack } from "./components/ClipTrack";
import { Header } from "./components/Header";
import { Subtitles } from "./components/Subtitles";
import { PlayersRow } from "./components/PlayersRow";
import { EvalBar } from "./components/EvalBar";
import { MoveStatus } from "./components/MoveStatus";
import { MoveCard } from "./components/MoveCard";
import { Summary } from "./components/Summary";
import { MusicTrack } from "./components/MusicTrack";
import { CardSfx } from "./components/CardSfx";

export type ChessSceneProps = { scene: Scene; preset?: "final" | "draft" };

export const FPS = 30;

const PRESETS = { final: { width: 1080, height: 1920 }, draft: { width: 720, height: 1280 } };

export const calculateChessSceneMetadata: CalculateMetadataFunction<ChessSceneProps> = ({ props }) => ({
  durationInFrames: buildTimeline(props.scene, FPS).durationInFrames,
  ...PRESETS[props.preset ?? "final"],
});

// Окно клипа в координатах референса 720×1280.
const CLIP = { left: 20, top: 256, width: 680, height: 382 };

const Overlay: React.FC<{ scene: Scene; timeline: Timeline }> = ({ scene, timeline }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const st = frameState(scene, timeline, frame);
  const { players } = scene;
  const speaking = st.speakingIndex !== null ? st.moves[st.speakingIndex] : null;
  const who = (side: "white" | "black") => players[side].name;

  return (
    <>
      <div style={{ position: "absolute", ...CLIP, borderRadius: 14, overflow: "hidden" }}>
        {/* На стоп-кадре под карточкой — строка сыгранного хода: карточка встаёт почти вплотную
            к следующей реплике, и по времени исходника на экран попала бы её ещё не сказанная строка. */}
        <Subtitles lines={timeline.lines} src={st.segment.kind === "card" && speaking ? Math.min(st.src, speaking.t1) : st.src} />
      </div>
      {/* На стыке с итогами плашки и шкала гаснут, а панель итогов проявляется следом — без пустого кадра. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity:
            st.segment.kind === "summary"
              ? interpolate(st.local, [0, 0.2 * fps], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
              : 1,
        }}
      >
        <PlayersRow
          white={players.white}
          black={players.black}
          activeSide={speaking?.side ?? null}
          ringColor={speaking ? categories[speaking.category].color : null}
        />
        <EvalBar value={st.evalValue} mateIn={st.mateIn} />
      </div>
      {st.segment.kind === "summary" ? (
        <Summary moves={st.moves} players={players} summary={scene.summary} local={st.local} />
      ) : st.segment.kind === "card" && speaking ? (
        <MoveCard move={speaking} label={moveLabel(st.moves, st.speakingIndex!)} who={who(speaking.side)} local={st.local} />
      ) : speaking ? (
        <MoveStatus label={moveLabel(st.moves, st.speakingIndex!)} who={who(speaking.side)} />
      ) : null}
    </>
  );
};

export const ChessScene: React.FC<ChessSceneProps> = ({ scene }) => {
  const { width, height, fps } = useVideoConfig();
  const timeline = useMemo(() => buildTimeline(scene, fps), [scene, fps]);
  const scale = width / BASE_WIDTH;

  return (
    <AbsoluteFill style={{ background: "#0d0f13", fontFamily }}>
      <div
        style={{
          position: "absolute",
          width: BASE_WIDTH,
          height: BASE_HEIGHT,
          left: 0,
          top: (height - BASE_HEIGHT * scale) / 2,
          scale: String(scale),
          transformOrigin: "top left",
          overflow: "hidden",
        }}
      >
        <ClipTrack
          src={scene.meta.background ?? scene.meta.clip}
          timeline={timeline}
          muted
          style={{
            position: "absolute",
            inset: 0,
            width: BASE_WIDTH,
            height: BASE_HEIGHT,
            filter: scene.meta.background ? undefined : "blur(28px) brightness(0.55)",
          }}
        />
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(rgba(10,12,16,0.45), rgba(10,12,16,0.15) 45%, rgba(10,12,16,0.35))" }} />
        <Header kicker={scene.meta.kicker ?? "Разбор сцены"} series={scene.meta.series} title={scene.meta.title} />
        <div
          style={{
            position: "absolute",
            ...CLIP,
            borderRadius: 14,
            overflow: "hidden",
            background: "#000",
            boxShadow: "0 10px 40px rgba(0,0,0,0.5)",
          }}
        >
          <ClipTrack src={scene.meta.clip} timeline={timeline} style={{ width: "100%", height: "100%" }} />
          {scene.meta.watermark ? (
            <div style={{ position: "absolute", top: 10, right: 14, color: "rgba(255,255,255,0.55)", fontSize: 14, fontWeight: 500 }}>
              {scene.meta.watermark}
            </div>
          ) : null}
        </div>
        <Overlay scene={scene} timeline={timeline} />
      </div>
      <CardSfx timeline={timeline} />
      {scene.meta.music ? (
        <MusicTrack src={scene.meta.music} volume={scene.meta.music_volume ?? 0.12} timeline={timeline} />
      ) : null}
    </AbsoluteFill>
  );
};
