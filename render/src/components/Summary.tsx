import React from "react";
import { Easing, Img, interpolate, staticFile, useVideoConfig } from "remotion";
import type { Move, Players, Summary as SummaryData } from "../generated/scene";
import { CATEGORY_ORDER, categories, colors } from "../theme";
import { accuracy } from "../timeline";
import { CategoryIcon } from "./CategoryIcon";

const COL_W = 90;

const Face: React.FC<{ src?: string | null }> = ({ src }) =>
  src ? (
    <Img src={staticFile(src)} style={{ width: 44, height: 44, borderRadius: "50%", objectFit: "cover" }} />
  ) : (
    <div style={{ width: 44, height: 44, borderRadius: "50%", background: colors.track }} />
  );

export const Summary: React.FC<{ moves: Move[]; players: Players; summary: SummaryData; local: number }> = ({
  moves,
  players,
  summary,
  local,
}) => {
  const { fps } = useVideoConfig();
  const appear = (delay: number) =>
    interpolate(local, [delay * fps, (delay + 0.3) * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const count = (side: "white" | "black", c: string) => moves.filter((m) => m.side === side && m.category === c).length;

  return (
    <div
      style={{
        position: "absolute",
        top: 640,
        left: 40,
        right: 40,
        borderRadius: 16,
        background: colors.panelSolid,
        padding: "26px 30px 18px",
        boxSizing: "border-box",
        opacity: appear(0.15),
        translate: interpolate(local, [0.15 * fps, 0.55 * fps], ["0px 30px", "0px 0px"], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
      }}
    >
      <div style={{ textAlign: "center", color: colors.text, fontSize: 30, fontWeight: 800 }}>Итоги партии</div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14, gap: 20 }}>
        {(["white", "black"] as const).map((side) => (
          <div key={side} style={{ width: COL_W, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
            <Face src={players[side].avatar} />
            <div style={{ color: colors.text, fontSize: 17, fontWeight: 700 }}>{players[side].name}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", marginTop: 6, opacity: appear(0.3) }}>
        <div style={{ flex: 1, color: colors.text, fontSize: 21, fontWeight: 700 }}>Точность</div>
        <div style={{ display: "flex", gap: 20 }}>
          {(["white", "black"] as const).map((side) => (
            <div
              key={side}
              style={{
                width: COL_W,
                height: 40,
                borderRadius: 6,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 22,
                fontWeight: 700,
                background: side === "white" ? "#f2f2f2" : colors.track,
                color: side === "white" ? "#1c1f26" : colors.text,
              }}
            >
              {accuracy(moves, side).toFixed(1)}
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        {CATEGORY_ORDER.map((c, i) => (
          <div key={c} style={{ display: "flex", alignItems: "center", height: 44, opacity: appear(0.5 + i * 0.12) }}>
            <div style={{ width: 190, color: colors.text, fontSize: 19, fontWeight: 500 }}>{categories[c].label}</div>
            <CategoryIcon category={c} size={30} />
            <div style={{ flex: 1 }} />
            <div style={{ display: "flex", gap: 20 }}>
              {(["white", "black"] as const).map((side) => {
                const n = count(side, c);
                return (
                  <div
                    key={side}
                    style={{
                      width: COL_W,
                      textAlign: "center",
                      fontSize: 20,
                      fontWeight: 700,
                      color: n ? categories[c].color : colors.zero,
                    }}
                  >
                    {n}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div style={{ textAlign: "center", marginTop: 10, opacity: appear(1.5) }}>
        <div style={{ color: colors.highlight, fontSize: 27, fontWeight: 800 }}>{summary.verdict}</div>
        <div style={{ color: colors.muted, fontSize: 14, marginTop: 4 }}>{summary.line}</div>
      </div>
    </div>
  );
};
