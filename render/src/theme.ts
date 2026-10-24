import { loadFont } from "@remotion/google-fonts/Inter";
import type { Category } from "./generated/scene";

export const { fontFamily } = loadFont("normal", {
  weights: ["400", "500", "600", "700", "800"],
  subsets: ["latin", "cyrillic"],
});

// Все размеры в шаблоне заданы в координатах референса 720×1280 и масштабируются под кадр.
export const BASE_WIDTH = 720;
export const BASE_HEIGHT = 1280;

export const colors = {
  text: "#ffffff",
  muted: "#9aa0a8",
  dim: "#6b7079",
  panel: "rgba(28, 31, 38, 0.92)",
  panelSolid: "#1c1f26",
  pill: "rgba(32, 35, 42, 0.85)",
  track: "#3a3d45",
  highlight: "#ffd21f",
  zero: "#4a4e57",
} as const;

type CategoryMeta = { label: string; cardLabel: string; color: string; icon: IconKind };
export type IconKind = "brilliant" | "best" | "excellent" | "good" | "inaccuracy" | "mistake" | "blunder";

export const categories: Record<Category, CategoryMeta> = {
  brilliant: { label: "Блестящий", cardLabel: "Блестящий ход", color: "#26c2a3", icon: "brilliant" },
  best: { label: "Лучший", cardLabel: "Лучший ход", color: "#81b64c", icon: "best" },
  excellent: { label: "Отличный", cardLabel: "Отличный ход", color: "#5fa83f", icon: "excellent" },
  good: { label: "Хороший", cardLabel: "Хороший ход", color: "#95b776", icon: "good" },
  inaccuracy: { label: "Неточность", cardLabel: "Неточность", color: "#f7c631", icon: "inaccuracy" },
  mistake: { label: "Ошибка", cardLabel: "Ошибка", color: "#ffa459", icon: "mistake" },
  blunder: { label: "Зевок", cardLabel: "Зевок", color: "#fa412d", icon: "blunder" },
};

export const CATEGORY_ORDER: Category[] = [
  "brilliant",
  "best",
  "excellent",
  "good",
  "inaccuracy",
  "mistake",
  "blunder",
];

export const sideLabel = { white: "белые", black: "чёрные" } as const;
