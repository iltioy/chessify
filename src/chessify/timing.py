"""Ритм ролика. Экспортируется в шаблон (render/src/generated/timing.json): Python и TypeScript
считают длительность одинаково — это нужно пресетам длины."""

TIMING = {
    "titleDelay": 0.25,
    "typeDelay": 0.45,
    "charsPerSecond": 35,
    "holdAfterTyping": 1.0,
    "minFreeze": 1.8,
    "evalTween": 0.5,
    "tailAfterLastMove": 0.8,
    "summary": 7,
    # Карточка встаёт не ровно на конец последнего слова (Whisper часто срезает хвост), а чуть позже,
    # но не позже начала следующей реплики.
    "cardDelay": 0.75,
    "cardGap": 0.05,
}


def card_cut(t1: float, word_starts: list[float]) -> float:
    """Момент остановки клипа под карточку хода, закончившегося в t1. Та же формула — в render/src/timeline.ts."""
    nxt = min((t0 for t0 in word_starts if t0 > t1 + 1e-3), default=float("inf"))
    return max(t1, min(t1 + TIMING["cardDelay"], nxt - TIMING["cardGap"]))


def card_seconds(comment: str) -> float:
    t = TIMING
    return max(t["minFreeze"], t["typeDelay"] + len(comment) / t["charsPerSecond"] + t["holdAfterTyping"])
