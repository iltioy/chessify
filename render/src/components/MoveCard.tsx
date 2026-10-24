import React from "react";
import { Easing, interpolate, useVideoConfig } from "remotion";
import type { Move } from "../generated/scene";
import { categories, colors, sideLabel } from "../theme";
import { timing } from "../timeline";
import { CategoryIcon } from "./CategoryIcon";

export const MoveCard: React.FC<{ move: Move; label: string; who: string; local: number }> = ({
  move,
  label,
  who,
  local,
}) => {
  const { fps } = useVideoConfig();
  const meta = categories[move.category];
  const t = local / fps;
  const typed = Math.max(0, Math.floor((t - timing.typeDelay) * timing.charsPerSecond));
  const typing = typed < move.comment.length;
  const cursorOn = Math.floor(local / (fps * 0.4)) % 2 === 0;

  return (
    <div
      style={{
        position: "absolute",
        top: 840,
        left: 40,
        right: 40,
        minHeight: 200,
        borderRadius: 14,
        background: colors.panel,
        borderLeft: `5px solid ${meta.color}`,
        padding: "22px 26px 22px 28px",
        boxSizing: "border-box",
        opacity: interpolate(local, [0, 0.15 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        translate: interpolate(local, [0, 0.25 * fps], ["0px 14px", "0px 0px"], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <CategoryIcon category={move.category} size={62} />
        <div>
          <div style={{ color: colors.muted, fontSize: 13, fontWeight: 500, letterSpacing: 0.8, textTransform: "uppercase" }}>
            {label} · {who} · {sideLabel[move.side]}
          </div>
          <div style={{ color: meta.color, fontSize: 29, fontWeight: 800, lineHeight: "36px" }}>{meta.cardLabel}</div>
        </div>
      </div>
      <div
        style={{
          marginTop: 14,
          color: colors.text,
          fontSize: 22,
          fontWeight: 700,
          opacity: interpolate(local, [timing.titleDelay * fps, (timing.titleDelay + 0.1) * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {move.title}
      </div>
      <div style={{ marginTop: 6, color: "#c9ccd3", fontSize: 18.5, lineHeight: "28px", minHeight: 56 }}>
        {move.comment.slice(0, typed)}
        {typing && t >= timing.typeDelay && cursorOn ? <span style={{ color: colors.text }}>|</span> : null}
      </div>
    </div>
  );
};
