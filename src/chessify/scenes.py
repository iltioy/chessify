"""Автовыбор сцены-дуэли из целой серии.

Модель видит расшифровку построчно (строка — реплика между паузами) с таймкодами и предлагает
кандидатов. Длинная серия режется на перекрывающиеся окна, чтобы поместиться в контекст даже
небольшой модели; кандидаты всех окон сводятся вместе. Границы сцены затем подтягиваются
к ближайшим монтажным склейкам, чтобы ролик не начинался посреди плана.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from chessify.analysis import template
from chessify.llm import LLMRouter
from chessify.schema import Word

MAX_WINDOW_CHARS = 36_000  # ≈ 13–15 тыс. токенов: влезает в контекст 32k с запасом под ответ
OVERLAP_LINES = 25
LINE_GAP = 0.8  # пауза, начинающая новую строку расшифровки
CUT_SNAP = 2.0  # насколько далеко искать монтажную склейку от границы реплики, секунды
PAD = 0.6  # запас вокруг реплик, если склейки рядом нет


class Line(BaseModel):
    t0: float
    t1: float
    spk: str | None
    text: str


class Candidate(BaseModel):
    first_line: int
    last_line: int
    title: str
    why: str
    sides: str = Field(description="Кто белые, кто чёрные")
    score: int = Field(ge=1, le=10)


class CandidateList(BaseModel):
    candidates: list[Candidate]


class SceneCandidate(BaseModel):
    """Итоговый кандидат — уже во времени исходного видео."""
    start: float
    end: float
    title: str
    why: str
    sides: str
    score: int
    excerpt: str
    speakers: list[str] = []


def to_lines(words: list[Word]) -> list[Line]:
    lines: list[Line] = []
    cur: list[Word] = []
    for w in words:
        if cur and (w.t0 - cur[-1].t1 > LINE_GAP or w.spk != cur[-1].spk):
            lines.append(Line(t0=cur[0].t0, t1=cur[-1].t1, spk=cur[0].spk, text=" ".join(x.w for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        lines.append(Line(t0=cur[0].t0, t1=cur[-1].t1, spk=cur[0].spk, text=" ".join(x.w for x in cur)))
    return lines


def _ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def _format(lines: list[Line], offset: int) -> str:
    return "\n".join(f"[{offset + i}] {_ts(x.t0)}–{_ts(x.t1)}, {x.spk or '?'}: {x.text}" for i, x in enumerate(lines))


def windows(lines: list[Line]) -> list[tuple[int, int]]:
    """Окна [начало, конец) по строкам: не длиннее MAX_WINDOW_CHARS, с перекрытием."""
    out: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (size + len(lines[end].text) + 40 <= MAX_WINDOW_CHARS or end == start):
            size += len(lines[end].text) + 40
            end += 1
        out.append((start, end))
        if end >= len(lines):
            break
        start = max(end - OVERLAP_LINES, start + 1)
    return out


def detect_cuts(video: Path, around: list[float]) -> list[float]:
    """Монтажные склейки (секунды) — только в окнах вокруг заданных моментов: вся серия заняла бы минуты.
    Без видео или при ошибке — пустой список, тогда работает запас PAD."""
    try:
        from scenedetect import ContentDetector, detect
    except ImportError:
        return []
    cuts: list[float] = []
    for t in around:
        try:
            scenes = detect(str(video), ContentDetector(), start_time=max(0.0, t - CUT_SNAP - 1),
                            end_time=t + CUT_SNAP + 1)
        except Exception:  # noqa: BLE001 — склейки лишь уточняют границы
            continue
        cuts += [start.get_seconds() for start, _ in scenes[1:]]
    return sorted(set(cuts))


def snap(start: float, end: float, cuts: list[float], duration: float | None) -> tuple[float, float]:
    before = [c for c in cuts if start - CUT_SNAP <= c <= start]
    after = [c for c in cuts if end <= c <= end + CUT_SNAP]
    s = max(before) if before else max(0.0, start - PAD)
    e = min(after) if after else end + PAD
    if duration is not None:
        e = min(e, duration)
    return round(s, 2), round(e, 2)


def _overlaps(a: SceneCandidate, b: SceneCandidate) -> bool:
    return min(a.end, b.end) - max(a.start, b.start) > 0.3 * min(a.end - a.start, b.end - b.start)


MERGE_GAP = 90.0  # секунды между кусками одной сцены


def _same_scene(a: SceneCandidate, b: SceneCandidate, lines: list[Line]) -> bool:
    """Куски одной сцены: общие спикеры, а в зазоре между ними говорят только они же."""
    who = set(a.speakers) | set(b.speakers)
    if not set(a.speakers) & set(b.speakers):
        return False
    gap = [x.spk or "?" for x in lines if x.t0 >= a.end and x.t1 <= b.start]
    return set(gap) <= who


def merge_adjacent(cands: list[SceneCandidate], max_seconds: float, lines: list[Line] | None = None,
                   ) -> list[SceneCandidate]:
    out: list[SceneCandidate] = []
    for c in sorted(cands, key=lambda c: c.start):
        prev = out[-1] if out else None
        # Пересекающиеся куски (из перекрывающихся окон) и куски с коротким зазором — одна сцена.
        if prev and c.start - prev.end <= MERGE_GAP and max(c.end, prev.end) - prev.start <= max_seconds \
                and _same_scene(prev, c, lines or []):
            main = prev if prev.score >= c.score else c
            out[-1] = main.model_copy(update={"start": prev.start, "end": max(prev.end, c.end),
                                              "score": max(prev.score, c.score), "excerpt": prev.excerpt,
                                              "speakers": sorted(set(prev.speakers) | set(c.speakers))})
        else:
            out.append(c)
    return out


def find_scenes(router: LLMRouter, words: list[Word], series: str, hint: str = "", video: Path | None = None,
                duration: float | None = None, max_candidates: int = 3, min_seconds: int = 45,
                max_seconds: int = 600, lang: str = "ru") -> list[SceneCandidate]:
    lines = to_lines(words)
    if not lines:
        return []
    parts = windows(lines)
    system = template("system.md.j2", lang).render(examples=[])
    found: list[SceneCandidate] = []
    for k, (a, b) in enumerate(parts, 1):
        prompt = template("scene_select.md.j2", lang).render(
            series=series, hint=hint, part=k, part_total=len(parts), transcript=_format(lines[a:b], a),
            max_candidates=max_candidates, min_seconds=min_seconds, max_seconds=max_seconds)
        result = router.complete_json("scene_select", system, prompt, CandidateList)
        for c in result.candidates:
            first, last = max(a, c.first_line), min(b - 1, c.last_line)
            if first > last:
                continue
            seg = lines[first : last + 1]
            found.append(SceneCandidate(
                start=seg[0].t0, end=seg[-1].t1, title=c.title, why=c.why, sides=c.sides, score=c.score,
                excerpt=" / ".join(x.text for x in seg[:4])[:300],
                speakers=sorted({x.spk or "?" for x in seg})))

    # Сцена на стыке окон может распасться на соседние куски — склеиваем, если влезает в лимит.
    found = merge_adjacent(found, max_seconds, lines)
    # Окна перекрываются: одна и та же сцена может прийти дважды — оставляем лучшую.
    best: list[SceneCandidate] = []
    for c in sorted(found, key=lambda c: -c.score):
        if not any(_overlaps(c, x) for x in best):
            best.append(c)
    best = best[:max_candidates]

    cuts = detect_cuts(video, [t for c in best for t in (c.start, c.end)]) if video else []
    return [c.model_copy(update=dict(zip(("start", "end"), snap(c.start, c.end, cuts, duration)))) for c in best]
