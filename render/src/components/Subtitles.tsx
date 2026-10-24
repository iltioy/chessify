import React from "react";
import type { SubtitleLine } from "../timeline";
import { colors } from "../theme";
import { joinsPrevious, timing } from "../timeline";

// Строка видна чуть дольше последнего слова, чтобы не мигать между словами, и остаётся
// на стоп-кадре под карточкой (карточка встаёт через cardDelay после конца фразы).
const HOLD_AFTER = timing.cardDelay + 0.1;
const LEAD = 0.03; // слово загорается чуть раньше звука — так глаз успевает за речью

export const Subtitles: React.FC<{ lines: SubtitleLine[]; src: number }> = ({ lines, src }) => {
  // Последняя начавшаяся строка: новая реплика сразу сменяет удерживаемую старую.
  const visible = lines.filter((l) => src >= l.t0 - 0.05 && src <= l.t1 + HOLD_AFTER);
  const line = visible[visible.length - 1];
  if (!line) return null;
  // Караоке: подсвечено ровно одно слово — то, что звучит. В паузах между словами горит последнее
  // начавшееся, поэтому каждое слово загорается один раз и подсветка не мигает.
  let active = -1;
  line.words.forEach((w, i) => {
    if (src >= w.t0 - LEAD) active = i;
  });
  return (
    <div
      style={{
        position: "absolute",
        left: 24,
        right: 24,
        bottom: 10,
        textAlign: "center",
        fontSize: 20,
        fontWeight: 700,
        lineHeight: "26px",
        color: colors.text,
        textShadow: "0 0 3px #000, 0 0 3px #000, 0 2px 6px rgba(0,0,0,0.8)",
      }}
    >
      {line.words.map((w, i) => (
        <span key={i} style={{ color: i === active ? colors.highlight : colors.text }}>
          {i > 0 && !joinsPrevious(w.w) ? " " : ""}
          {w.w}
        </span>
      ))}
    </div>
  );
};
