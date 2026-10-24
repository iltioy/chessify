import type { Move, Scene, Word } from "./generated/scene";
import scoring from "./generated/scoring.json";
// Ритм карточки (общий с Python, см. src/chessify/timing.py): заголовок сразу,
// комментарий печатается посимвольно, затем пауза на чтение.
import timingJson from "./generated/timing.json";

export const timing = timingJson;

export type Segment =
  | { kind: "play"; from: number; duration: number; srcStart: number }
  | { kind: "card"; from: number; duration: number; srcAt: number; moveIndex: number; typingFrames: number }
  | { kind: "summary"; from: number; duration: number; srcAt: number };

export type SubtitleLine = { t0: number; t1: number; words: Word[] };

export type Timeline = {
  fps: number;
  segments: Segment[];
  durationInFrames: number;
  lines: SubtitleLine[];
  cuts: number[]; // момент остановки под карточку для каждого хода (по порядку t1)
};

export const cardSeconds = (move: Move) =>
  Math.max(timing.minFreeze, timing.typeDelay + move.comment.length / timing.charsPerSecond + timing.holdAfterTyping);

const sortedMoves = (scene: Scene) => [...scene.moves].sort((a, b) => a.t1 - b.t1);

// Карточка встаёт чуть позже конца последнего слова, но не позже начала следующей реплики.
// Та же формула — card_cut в src/chessify/timing.py.
export const cardCut = (t1: number, words: Word[]) => {
  const next = Math.min(...words.filter((w) => w.t0 > t1 + 1e-3).map((w) => w.t0), Infinity);
  return Math.max(t1, Math.min(t1 + timing.cardDelay, next - timing.cardGap));
};

export const buildTimeline = (scene: Scene, fps: number): Timeline => {
  const moves = sortedMoves(scene);
  const segments: Segment[] = [];
  let out = 0;
  let src = 0;
  const push = (seg: Segment) => {
    if (seg.duration > 0) segments.push(seg);
    out += seg.duration;
  };

  // Полная версия — один отрезок от начала клипа; короткая — только выбранные пары ходов.
  const lastT1 = moves.length ? moves[moves.length - 1].t1 : 0;
  // json2ts не выводит типы элементов кортежа из prefixItems — приводим явно.
  const ranges = scene.meta.excerpts as [number, number][] | null | undefined;
  const excerpts: [number, number][] = ranges?.length ? ranges : [[0, lastT1 + timing.tailAfterLastMove]];

  const cuts = moves.map((m) => cardCut(m.t1, scene.words));
  for (const [a, b] of excerpts) {
    src = a;
    moves.forEach((move, i) => {
      if (move.t1 <= a || move.t1 > b) return;
      const cut = Math.max(src, Math.min(cuts[i], b));
      push({ kind: "play", from: out, duration: Math.round((cut - src) * fps), srcStart: src });
      src = cut;
      if (move.show_card !== false) {
        push({
          kind: "card", from: out, duration: Math.round(cardSeconds(move) * fps), srcAt: src, moveIndex: i,
          typingFrames: Math.round((move.comment.length / timing.charsPerSecond) * fps),
        });
      }
    });
    push({ kind: "play", from: out, duration: Math.round(Math.max(0, b - src) * fps), srcStart: src });
    src = Math.max(src, b);
  }
  push({ kind: "summary", from: out, duration: Math.round(timing.summary * fps), srcAt: src });

  return { fps, segments, durationInFrames: out, lines: groupLines(scene.words), cuts };
};

// Строки субтитров: разрыв по паузе, смене спикера, длине и концу фразы.
export const groupLines = (words: Word[]): SubtitleLine[] => {
  const lines: SubtitleLine[] = [];
  let cur: Word[] = [];
  const flush = () => {
    if (cur.length) lines.push({ t0: cur[0].t0, t1: cur[cur.length - 1].t1, words: cur });
    cur = [];
  };
  for (const w of words) {
    const prev = cur[cur.length - 1];
    const len = cur.reduce((n, x) => n + x.w.length + 1, 0);
    // До ~70 символов строка переносится внутри окна на две; дальше — новая строка.
    if (prev && (w.t0 - prev.t1 > 0.7 || (w.spk ?? null) !== (prev.spk ?? null) || len + w.w.length > 70)) flush();
    cur.push(w);
    if (/[.?!…]$/.test(w.w) && len > 24) flush();
  }
  flush();
  return lines;
};

// Распознавание отдаёт «по-твоему» как «по» + «-твоему»: перед таким словом пробел не нужен.
export const joinsPrevious = (w: string) => /^-\p{L}/u.test(w);

export type FrameState = {
  segment: Segment;
  local: number; // кадр внутри сегмента
  src: number; // время исходного клипа, секунды
  moves: Move[];
  playedCount: number; // сколько ходов уже сыграно (карточка показана или пропущена)
  speakingIndex: number | null; // ход, реплика которого звучит или чья карточка на экране
  evalValue: number;
  mateIn: number | null; // концовка: мат через N ходов фаворита (0 — мат на доске)
};

export const frameState = (scene: Scene, tl: Timeline, frame: number): FrameState => {
  const moves = sortedMoves(scene);
  const segment =
    tl.segments.find((s) => frame >= s.from && frame < s.from + s.duration) ?? tl.segments[tl.segments.length - 1];
  const local = frame - segment.from;
  const src = segment.kind === "play" ? segment.srcStart + local / tl.fps : segment.srcAt;

  const playedCount =
    segment.kind === "card" ? segment.moveIndex : tl.cuts.filter((c) => c <= src + 1e-6).length;
  const speakingIndex =
    segment.kind === "summary" ? null : segment.kind === "card" ? segment.moveIndex : playedCount < moves.length ? playedCount : null;

  const evalBefore = playedCount > 0 ? moves[playedCount - 1].eval_after : (scene.meta.eval_start ?? 0);
  let evalValue = evalBefore;
  if (segment.kind === "card") {
    const p = Math.min(1, local / (timing.evalTween * tl.fps));
    const eased = 1 - Math.pow(1 - p, 3);
    evalValue = evalBefore + (moves[segment.moveIndex].eval_after - evalBefore) * eased;
  }
  const limit = scoring.evalLimit;
  evalValue = Math.max(-limit, Math.min(limit, evalValue));
  // Отсчёт до мата появляется вместе с карточкой хода, после которого он начался.
  const shownMove = segment.kind === "card" ? moves[segment.moveIndex] : playedCount > 0 ? moves[playedCount - 1] : null;
  const mateIn = shownMove?.mate_in ?? null;

  return { segment, local, src, moves, playedCount, speakingIndex, evalValue, mateIn };
};

export const accuracy = (moves: Move[], side: Move["side"]) => {
  const own = moves.filter((m) => m.side === side);
  if (!own.length) return 0;
  const weights = scoring.weights as Record<string, number>;
  return Math.round((own.reduce((s, m) => s + weights[m.category], 0) / own.length) * 10) / 10;
};

export const moveLabel = (moves: Move[], index: number, word = "Ход") => {
  const m = moves[index];
  return m.side === "white" ? `${word} ${m.n}.` : `${word} ${m.n}…`;
};
