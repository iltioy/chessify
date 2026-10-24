"""Пресеты длины: короткая версия партии из самых сильных пар ходов.

Ход белых и ответ чёрных с тем же номером — одна пара («вопрос — ответ»): так сохраняется
смысл реплик. Пары ранжируются по яркости, лучшие берутся в хронологическом порядке,
пока ролик укладывается в лимит. Первая и последняя пары остаются всегда: завязка и развязка.
"""

from itertools import groupby

from chessify.schema import Category, Move, Scene
from chessify.timing import TIMING, card_cut, card_seconds

SALIENCE = {
    Category.brilliant: 5, Category.blunder: 5, Category.mistake: 4, Category.best: 3,
    Category.inaccuracy: 3, Category.excellent: 2, Category.good: 1,
}
LEAD_IN = 0.3  # секунды перед первой репликой пары, чтобы фраза не обрывалась на вдохе

PRESETS = {"shorts": 60.0, "reels": 90.0, "short3": 180.0}


def _pairs(moves: list[Move]) -> list[list[Move]]:
    return [list(g) for _, g in groupby(sorted(moves, key=lambda m: m.t0), key=lambda m: m.n)]


def _pair_seconds(pair: list[Move], starts: list[float]) -> float:
    span = card_cut(pair[-1].t1, starts) - max(0.0, pair[0].t0 - LEAD_IN)
    return span + sum(card_seconds(m.comment) for m in pair if m.show_card)


def _salience(pair: list[Move], prev_eval: float) -> float:
    swing = abs(pair[-1].eval_after - prev_eval)
    return max(SALIENCE[m.category] for m in pair) + 2 * swing


def condense(scene: Scene, max_seconds: float) -> Scene:
    pairs = _pairs(scene.moves)
    starts = [w.t0 for w in scene.words]
    budget = max_seconds - TIMING["summary"] - TIMING["tailAfterLastMove"]
    evals = [scene.meta.eval_start] + [p[-1].eval_after for p in pairs]
    must = {0, len(pairs) - 1}
    ranked = sorted(range(len(pairs)), key=lambda i: (i not in must, -_salience(pairs[i], evals[i])))

    chosen: set[int] = set()
    used = 0.0
    for i in ranked:
        cost = _pair_seconds(pairs[i], starts)
        if used + cost <= budget or i in must:
            chosen.add(i)
            used += cost

    kept = [pairs[i] for i in sorted(chosen)]
    excerpts = [(round(max(0.0, p[0].t0 - LEAD_IN), 3), round(card_cut(p[-1].t1, starts), 3)) for p in kept]
    excerpts[-1] = (excerpts[-1][0], max(excerpts[-1][1], kept[-1][-1].t1 + TIMING["tailAfterLastMove"]))
    # Пропущенные ходы остаются без карточки: шкала и итоги партии считаются по всей партии.
    shown = {id(m) for p in kept for m in p}
    moves = [m if id(m) in shown else m.model_copy(update={"show_card": False}) for p in pairs for m in p]
    words = [w for w in scene.words if any(a - 0.05 <= w.t0 and w.t1 <= b + 0.05 for a, b in excerpts)]
    return scene.model_copy(update={
        "moves": moves,
        "words": words,
        "meta": scene.meta.model_copy(update={"excerpts": excerpts}),
    })


def estimated_seconds(scene: Scene) -> float:
    if scene.meta.excerpts:
        speech = sum(b - a for a, b in scene.meta.excerpts)
    else:
        speech = max(m.t1 for m in scene.moves) + TIMING["tailAfterLastMove"]
    cards = sum(card_seconds(m.comment) for m in scene.moves if m.show_card)
    return speech + cards + TIMING["summary"]
