import React from "react";
import { colors, useText } from "../theme";

export const MoveStatus: React.FC<{ label: string; who: string }> = ({ label, who }) => {
  const text = useText();
  return (
    <div
      style={{
        position: "absolute",
        top: 840,
        left: 40,
        right: 40,
        height: 34,
        borderRadius: 10,
        background: colors.pill,
        display: "flex",
        alignItems: "center",
        gap: 10,
        paddingLeft: 14,
        color: colors.muted,
        fontSize: 15,
        fontWeight: 500,
      }}
    >
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: colors.dim }} />
      <span>
        {label} · {text.toMove(who)}
      </span>
    </div>
  );
};
