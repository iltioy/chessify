import React from "react";
import { colors } from "../theme";

export const Header: React.FC<{ kicker: string; series: string; title: string }> = ({ kicker, series, title }) => (
  <div style={{ position: "absolute", top: 64, left: 24, right: 24, textAlign: "center" }}>
    <div
      style={{
        color: colors.muted,
        fontSize: 15,
        fontWeight: 600,
        letterSpacing: 3,
        textTransform: "uppercase",
      }}
    >
      {kicker} · {series}
    </div>
    <div
      style={{
        marginTop: 14,
        color: colors.text,
        fontSize: 35,
        fontWeight: 800,
        lineHeight: "48px",
        letterSpacing: -0.4,
        whiteSpace: "pre-line",
        textShadow: "0 2px 12px rgba(0,0,0,0.5)",
      }}
    >
      {title}
    </div>
  </div>
);
