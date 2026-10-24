import React from "react";
import type { Category } from "../generated/scene";
import { categories } from "../theme";

const glyph = (category: Category, size: number) => {
  const s = size * 0.5;
  switch (category) {
    case "best":
      return (
        <svg width={s} height={s} viewBox="0 0 24 24">
          <path fill="#fff" d="M12 1.8l3.1 6.6 7.1.9-5.2 4.9 1.3 7.1L12 17.8l-6.3 3.5L7 14.2 1.8 9.3l7.1-.9z" />
        </svg>
      );
    case "excellent":
      return (
        <svg width={s} height={s} viewBox="0 0 24 24">
          <path
            fill="#fff"
            d="M2 10h4v12H2zM8 21V10.4l4.6-8.2c.5-.8 1.7-.6 2 .3.2.6.2 1.2 0 1.8L13.4 9H20c1.2 0 2.1 1.1 1.9 2.3l-1.5 8.2c-.2 1-1 1.5-2 1.5z"
          />
        </svg>
      );
    case "good":
      return (
        <svg width={s} height={s} viewBox="0 0 24 24">
          <path fill="none" stroke="#fff" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" d="M4 12.5l5 5L20 6.5" />
        </svg>
      );
    default: {
      const text = { brilliant: "!!", inaccuracy: "?!", mistake: "?", blunder: "??" }[category];
      return (
        <span style={{ color: "#fff", fontWeight: 800, fontSize: size * 0.42, letterSpacing: -1, lineHeight: 1 }}>{text}</span>
      );
    }
  }
};

export const CategoryIcon: React.FC<{ category: Category; size: number }> = ({ category, size }) => (
  <div
    style={{
      width: size,
      height: size,
      borderRadius: "50%",
      background: categories[category].color,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0,
    }}
  >
    {glyph(category, size)}
  </div>
);
