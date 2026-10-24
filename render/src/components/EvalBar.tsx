import React from "react";
import { colors } from "../theme";

// Шкала оценки как в шахматном движке: белая заливка слева — преимущество белых.
// Заливка по сигмоиде, как у Chess.com: при +0.8 ~62% (как в референсе), а к ±4 она подходит
// плавно и не упирается в край — большой перевес продолжает читаться.
const SPREAD = 3;

const format = (v: number, mateIn: number | null) => {
  if (mateIn !== null) return mateIn === 0 ? "#" : `M${mateIn}`;
  const r = Math.round(v * 10) / 10;
  if (r === 0) return "0.0";
  return (r > 0 ? "+" : "−") + Math.abs(r).toFixed(1);
};

export const EvalBar: React.FC<{ value: number; mateIn?: number | null }> = ({ value, mateIn = null }) => {
  const share = 0.5 + 0.47 * Math.tanh(value / SPREAD);
  const positive = value >= 0;
  return (
    <div style={{ position: "absolute", top: 778, left: 40, right: 40 }}>
      <div
        style={{
          height: 22,
          color: colors.text,
          fontSize: 16,
          fontWeight: 700,
          textAlign: positive ? "left" : "right",
        }}
      >
        {format(value, mateIn)}
      </div>
      <div style={{ position: "relative", height: 14, borderRadius: 7, background: colors.track, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${share * 100}%`, background: "#f2f2f2" }} />
        <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 2, background: "rgba(90,94,102,0.9)" }} />
      </div>
    </div>
  );
};
