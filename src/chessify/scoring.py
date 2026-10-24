"""Подсчёт итогов партии.

Точность, счётчики и шкала считаются кодом из категорий ходов, а не моделью, чтобы итоговая
таблица и шкала не противоречили карточкам. Веса экспортируются в шаблон Remotion, поэтому
правило одно для Python и TypeScript.
"""

import math
import re
from collections import Counter

from chessify.schema import Category, Move, Scene, Side

# Подобраны по итогам референса: при его распределении ходов дают 83.5 и 92.9 (в ролике 83.8 и 93.0).
WEIGHTS: dict[Category, float] = {
    Category.brilliant: 100,
    Category.best: 100,
    Category.excellent: 93,
    Category.good: 83,
    Category.inaccuracy: 55,
    Category.mistake: 30,
    Category.blunder: 0,
}

EVAL_LIMIT = 5.0

# Сдвиг шкалы за ход в пользу сходившей стороны. Сняты с эталона (fixtures/reference/full.scene.json):
# там сдвиги строго зависят от категории. Зевка в эталоне нет — взят вдвое больше ошибки.
EVAL_SHIFT: dict[Category, float] = {
    Category.brilliant: 0.5,
    Category.best: 0.3,
    Category.excellent: 0.2,
    Category.good: 0.2,
    Category.inaccuracy: -0.4,
    Category.mistake: -0.9,
    Category.blunder: -1.8,
}
EVAL_KNEE = 2.0  # до ±2 сдвиги копятся как есть — так устроен эталон
EVAL_PULLBACK = 0.85  # перекос сверх ±2 с каждым ходом частично гаснет: шкала не залипает у края
EVAL_SOFTNESS = 3.0  # к пределу ±5 шкала подходит плавно и не упирается в него

# Мат в концовке: только при явном фаворите и только в хвосте партии, где он играет сильно,
# а соперник не отвечает сильными ходами. Не больше MATE_MAX ходов фаворита до мата.
MATE_MIN_EVAL = 3.0
MATE_TAIL_EVAL = 2.5
MATE_MAX = 3
MATE_TAIL_SHARE = 0.25  # мат ставится ходами из последней четверти партии
STRONG = {Category.brilliant, Category.best, Category.excellent}
COUNTER = {Category.brilliant, Category.best}
NO_MATE_VERDICT = re.compile(r"НЕТ|НИЧ|ПАТ|\bNO\b|DRAW|STALEMATE", re.IGNORECASE)


def accuracy(moves: list[Move], side: Side) -> float:
    own = [WEIGHTS[m.category] for m in moves if m.side == side]
    return round(sum(own) / len(own), 1) if own else 0.0


def counts(moves: list[Move], side: Side) -> dict[Category, int]:
    c = Counter(m.category for m in moves if m.side == side)
    return {cat: c.get(cat, 0) for cat in Category}


def clamp_eval(value: float) -> float:
    return max(-EVAL_LIMIT, min(EVAL_LIMIT, value))


def eval_curve(moves: list[Move], start: float) -> list[float]:
    """Шкала после каждого хода (в порядке партии) по категориям ходов."""
    raw, out = start, []
    for m in moves:
        if abs(raw) > EVAL_KNEE:
            raw = math.copysign(EVAL_KNEE + (abs(raw) - EVAL_KNEE) * EVAL_PULLBACK, raw)
        raw += EVAL_SHIFT[m.category] * (1 if m.side == Side.white else -1)
        shown = raw if abs(raw) <= EVAL_KNEE else math.copysign(
            EVAL_KNEE + (EVAL_LIMIT - EVAL_KNEE) * math.tanh((abs(raw) - EVAL_KNEE) / EVAL_SOFTNESS), raw)
        out.append(round(shown, 1))
    return out


def mate_countdown(moves: list[Move], evals: list[float], verdict: str = "") -> list[int | None]:
    """Отсчёт до мата для концовки: после каждого хода — сколько ходов фавориту осталось до мата."""
    out: list[int | None] = [None] * len(moves)
    if not moves or abs(evals[-1]) < MATE_MIN_EVAL or NO_MATE_VERDICT.search(verdict):
        return out
    fav = Side.white if evals[-1] > 0 else Side.black
    if moves[-1].side != fav:
        return out  # мат ставит фаворит последним ходом
    start = len(moves)
    while start > 0:
        m, e = moves[start - 1], evals[start - 1]
        strong = m.category in STRONG if m.side == fav else m.category not in COUNTER
        if not strong or abs(e) < MATE_TAIL_EVAL or (e > 0) != (fav == Side.white):
            break
        start -= 1
    last_part = max(start, math.ceil(len(moves) * (1 - MATE_TAIL_SHARE)))
    finishers = [i for i in range(last_part, len(moves)) if moves[i].side == fav][-MATE_MAX:]
    if not finishers:
        return out
    for j in range(max(start, finishers[0] - 1), len(moves)):
        out[j] = sum(k > j for k in finishers)
    return out


def score_moves(scene: Scene) -> Scene:
    """Шкала и отсчёт до мата из категорий ходов. Ходы в сцене идут в порядке партии."""
    evals = eval_curve(scene.moves, scene.meta.eval_start)
    mates = mate_countdown(scene.moves, evals, scene.summary.verdict)
    moves = [m.model_copy(update={
        "eval_after": e if mate is None else math.copysign(EVAL_LIMIT, e), "mate_in": mate,
    }) for m, e, mate in zip(scene.moves, evals, mates)]
    return scene.model_copy(update={"moves": moves})
