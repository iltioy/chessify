import { createContext, useContext } from "react";
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

type CategoryMeta = { color: string; icon: IconKind };
export type IconKind = "brilliant" | "best" | "excellent" | "good" | "inaccuracy" | "mistake" | "blunder";

export const categories: Record<Category, CategoryMeta> = {
  brilliant: { color: "#26c2a3", icon: "brilliant" },
  best: { color: "#81b64c", icon: "best" },
  excellent: { color: "#5fa83f", icon: "excellent" },
  good: { color: "#95b776", icon: "good" },
  inaccuracy: { color: "#f7c631", icon: "inaccuracy" },
  mistake: { color: "#ffa459", icon: "mistake" },
  blunder: { color: "#fa412d", icon: "blunder" },
};

// Надписи ролика на языке сцены (meta.language).
export type Lang = "ru" | "en";
type Labels = { label: string; card: string };
export const TEXT = {
  ru: {
    categories: {
      brilliant: { label: "Блестящий", card: "Блестящий ход" },
      best: { label: "Лучший", card: "Лучший ход" },
      excellent: { label: "Отличный", card: "Отличный ход" },
      good: { label: "Хороший", card: "Хороший ход" },
      inaccuracy: { label: "Неточность", card: "Неточность" },
      mistake: { label: "Ошибка", card: "Ошибка" },
      blunder: { label: "Зевок", card: "Зевок" },
    } as Record<Category, Labels>,
    side: { white: "белые", black: "чёрные" },
    move: "Ход",
    toMove: (who: string) => `ходит ${who}`,
    summary: "Итоги партии",
    accuracy: "Точность",
    kicker: "Разбор сцены",
  },
  en: {
    categories: {
      brilliant: { label: "Brilliant", card: "Brilliant move" },
      best: { label: "Best", card: "Best move" },
      excellent: { label: "Excellent", card: "Excellent move" },
      good: { label: "Good", card: "Good move" },
      inaccuracy: { label: "Inaccuracy", card: "Inaccuracy" },
      mistake: { label: "Mistake", card: "Mistake" },
      blunder: { label: "Blunder", card: "Blunder" },
    } as Record<Category, Labels>,
    side: { white: "White", black: "Black" },
    move: "Move",
    toMove: (who: string) => `${who} to move`,
    summary: "Game summary",
    accuracy: "Accuracy",
    kicker: "Scene breakdown",
  },
};
export const LangContext = createContext<Lang>("ru");
export const useText = () => TEXT[useContext(LangContext)];

export const CATEGORY_ORDER: Category[] = [
  "brilliant",
  "best",
  "excellent",
  "good",
  "inaccuracy",
  "mistake",
  "blunder",
];

