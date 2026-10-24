import React from "react";
import { Img, staticFile } from "remotion";
import type { Player } from "../generated/scene";
import { colors, useText } from "../theme";

const Avatar: React.FC<{ player: Player; ring: string | null }> = ({ player, ring }) => (
  <div
    style={{
      width: 60,
      height: 60,
      borderRadius: "50%",
      padding: 3,
      boxSizing: "border-box",
      border: `3px solid ${ring ?? "transparent"}`,
      flexShrink: 0,
    }}
  >
    {player.avatar ? (
      <Img
        src={staticFile(player.avatar)}
        style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover", opacity: ring ? 1 : 0.75 }}
      />
    ) : (
      <div style={{ width: "100%", height: "100%", borderRadius: "50%", background: colors.track }} />
    )}
  </div>
);

const Names: React.FC<{ player: Player; side: "white" | "black" }> = ({ player, side }) => (
  <div style={{ textAlign: side === "white" ? "left" : "right" }}>
    <div style={{ color: colors.text, fontSize: 21, fontWeight: 700, lineHeight: "26px" }}>{player.name}</div>
    <div style={{ color: colors.muted, fontSize: 15, lineHeight: "20px" }}>{useText().side[side]}</div>
  </div>
);

export const PlayersRow: React.FC<{
  white: Player;
  black: Player;
  activeSide: "white" | "black" | null;
  ringColor: string | null;
}> = ({ white, black, activeSide, ringColor }) => (
  <div
    style={{
      position: "absolute",
      top: 692,
      left: 40,
      right: 40,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Avatar player={white} ring={activeSide === "white" ? ringColor : null} />
      <Names player={white} side="white" />
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Names player={black} side="black" />
      <Avatar player={black} ring={activeSide === "black" ? ringColor : null} />
    </div>
  </div>
);
