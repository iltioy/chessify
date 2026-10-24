"""Анализ партии: разбивка на ходы → оценки → редактура.

Модели возвращают только смысл (стороны, диапазоны слов, категории, тексты). Всё, что можно
посчитать, считает код: таймкоды ходов из слов, номера ходов, шкалу.
"""

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field

from chessify.llm import LLMRouter
from chessify.paths import ROOT
from chessify.schema import Category, Meta, Move, Players, Scene, Side, Summary, Word
from chessify.pacing import pace_cards
from chessify.scoring import score_moves

PROMPTS = Environment(loader=FileSystemLoader(ROOT / "prompts"), undefined=StrictUndefined, keep_trailing_newline=True)
REFERENCE_SCENE = ROOT / "render" / "src" / "fixtures" / "reference.scene.json"
EXAMPLES_EN = ROOT / "prompts" / "en" / "examples.json"  # те же ходы эталона в переводе


def template(name: str, lang: str = "ru"):
    """Промпт на языке ролика: русские — в prompts/, английские — в prompts/en/."""
    return PROMPTS.get_template(name if lang == "ru" else f"en/{name}")


class SegPlayer(BaseModel):
    name: str = Field(description="Короткое имя стороны для экрана, 1–2 слова")
    speakers: list[str] = Field(description="Метки спикеров этой стороны")


class SegMove(BaseModel):
    side: Side
    w0: int = Field(description="Номер первого слова хода")
    w1: int = Field(description="Номер последнего слова хода, включительно")
    nonverbal: bool = False
    pause_after: int | None = Field(
        default=None, description="Ход-молчание: номер слова, после которого идёт пауза (тогда w0 и w1 не важны)")


class SegmentResult(BaseModel):
    white: SegPlayer
    black: SegPlayer
    title: str = Field(description="Заголовок ролика, две строки через \\n")
    moves: list[SegMove]


class GradedMove(BaseModel):
    index: int
    category: Category
    title: str
    comment: str
    eval_after: float | None = None  # не используется: шкалу считает код из категорий (scoring.score_moves)


class GradeResult(BaseModel):
    moves: list[GradedMove]
    verdict: str
    line: str


def _examples(exclude_reference: bool, lang: str = "ru") -> list[dict]:
    if exclude_reference or not REFERENCE_SCENE.exists():
        return []
    if lang == "en":
        return json.loads(EXAMPLES_EN.read_text(encoding="utf-8"))
    ref = Scene.model_validate_json(REFERENCE_SCENE.read_text(encoding="utf-8"))
    names = {Side.white: ref.players.white.name, Side.black: ref.players.black.name}
    return [{**m.model_dump(), "side_name": names[m.side]} for m in ref.moves]


PAUSE_MIN = 1.5  # секунды тишины, которые показываем модели как возможный ход-молчание
PAUSE_MAX_MOVE = 5.0  # дольше молчание на экране не держим


def format_transcript(words: list[Word], lang: str = "ru") -> str:
    lines: list[str] = []
    cur_spk: str | None = None
    buf: list[str] = []
    for i, w in enumerate(words):
        spk = w.spk or "?"
        if spk != cur_spk and buf:
            lines.append(f"{cur_spk}: " + " ".join(buf))
            buf = []
        cur_spk = spk
        buf.append(f"[{i}] {w.w}")
        if i + 1 < len(words) and (gap := words[i + 1].t0 - w.t1) >= PAUSE_MIN:
            lines.append(f"{cur_spk}: " + " ".join(buf))
            lines.append(f"[pause {gap:.1f} s after word {i}]" if lang == "en" else f"[пауза {gap:.1f} с после слова {i}]")
            buf = []
    if buf:
        lines.append(f"{cur_spk}: " + " ".join(buf))
    return "\n".join(lines)


def _pause_span(words: list[Word], i: int) -> tuple[float, float] | None:
    if not 0 <= i < len(words) - 1 or words[i + 1].t0 - words[i].t1 < PAUSE_MIN:
        return None
    t0 = words[i].t1 + 0.1
    return t0, min(words[i + 1].t0 - 0.1, t0 + PAUSE_MAX_MOVE)


def move_span(m: SegMove, words: list[Word], lang: str = "ru") -> tuple[float, float, str]:
    if m.pause_after is not None:
        t0, t1 = _pause_span(words, m.pause_after)  # type: ignore[misc]  # проверено в _clean_moves
        return t0, t1, f"(silence {t1 - t0:.0f} s)" if lang == "en" else f"(молчание {t1 - t0:.0f} с)"
    return words[m.w0].t0, words[m.w1].t1, " ".join(w.w for w in words[m.w0 : m.w1 + 1])


def _clean_moves(seg: SegmentResult, words: list[Word]) -> list[SegMove]:
    """Отбрасываем выход за границы, пересечения и «паузы», которых нет: модель могла ошибиться в номерах."""
    spoken: list[SegMove] = []
    last = -1
    for m in sorted((m for m in seg.moves if m.pause_after is None), key=lambda m: m.w0):
        w0, w1 = max(m.w0, last + 1), min(m.w1, len(words) - 1)
        if w0 <= w1:
            spoken.append(m.model_copy(update={"w0": w0, "w1": w1}))
            last = w1
    pauses = [m.model_copy(update={"nonverbal": True}) for m in seg.moves
              if m.pause_after is not None and _pause_span(words, m.pause_after)]
    return sorted(spoken + pauses, key=lambda m: move_span(m, words)[0])


PHRASE_GAP = 0.8  # слова одного говорящего с паузой меньше этой — одна фраза


def _same_phrase(words: list[Word], i: int) -> bool:
    """Слово i+1 продолжает фразу слова i: тот же говорящий (или разметки нет) и без паузы."""
    a, b = words[i], words[i + 1]
    return b.t0 - a.t1 < PHRASE_GAP and (a.spk is None or b.spk is None or a.spk == b.spk)


def snap_to_phrases(moves: list[SegMove], words: list[Word]) -> list[SegMove]:
    """Ход кончается только с концом фразы: карточка не должна оборвать персонажа на полуслове.

    Конец хода дотягивается до конца фразы, а два хода одной стороны внутри одной фразы склеиваются.
    """
    taken = {i for m in moves if m.pause_after is None for i in range(m.w0, m.w1 + 1)}
    out: list[SegMove] = []
    for m in moves:
        if m.pause_after is not None:
            out.append(m)
            continue
        w1 = m.w1
        while w1 + 1 < len(words) and w1 + 1 not in taken and _same_phrase(words, w1):
            w1 += 1
        prev = next((x for x in reversed(out) if x.pause_after is None), None)
        if prev is not None and prev is out[-1] and prev.side == m.side and prev.w1 + 1 == m.w0 \
                and _same_phrase(words, prev.w1):
            out[-1] = prev.model_copy(update={"w1": w1, "nonverbal": prev.nonverbal or m.nonverbal})
        else:
            out.append(m.model_copy(update={"w1": w1}))
    return out


def number_moves(sides: list[Side]) -> list[int]:
    """Нумерация как в шахматной нотации: номер растёт с ходом белых, чёрные делят номер с предыдущим ходом белых."""
    nums, n = [], 0
    for s in sides:
        if s == Side.white or n == 0:
            n += 1
        nums.append(n)
    return nums


def analyze(router: LLMRouter, words: list[Word], meta: Meta, hint: str = "", exclude_reference: bool = False,
            eval_start: float = 0.5) -> Scene:
    lang = meta.language
    system = template("system.md.j2", lang).render(examples=_examples(exclude_reference, lang))

    seg = router.complete_json(
        "segment", system,
        template("segment.md.j2", lang).render(series=meta.series, hint=hint, transcript=format_transcript(words, lang)),
        SegmentResult,
    )
    moves = snap_to_phrases(_clean_moves(seg, words), words)
    if not moves:
        raise RuntimeError("модель не выделила ни одного хода")
    names = {Side.white: seg.white.name, Side.black: seg.black.name}
    spans = [move_span(m, words, lang) for m in moves]
    listed = [{"index": i, "side_name": names[m.side], "w0": m.w0, "w1": m.w1, "nonverbal": m.nonverbal,
               "quote": spans[i][2]} for i, m in enumerate(moves)]

    grade_prompt = template("grade.md.j2", lang).render(
        series=meta.series, white=seg.white.name, black=seg.black.name, eval_start=eval_start, moves=listed)
    graded = router.complete_json("grade", system, grade_prompt, GradeResult)

    draft = json.dumps({"moves_context": listed, **graded.model_dump(mode="json")}, ensure_ascii=False, indent=1)
    edited = router.complete_json("edit", system, template("edit.md.j2", lang).render(draft=draft), GradeResult)

    by_index = {g.index: g for g in edited.moves}
    missing = [i for i in range(len(moves)) if i not in by_index]
    if missing:
        raise RuntimeError(f"нет оценок для ходов {missing}")

    numbers = number_moves([m.side for m in moves])
    scene_moves = []
    for i, m in enumerate(moves):
        g = by_index[i]
        scene_moves.append(Move(
            n=numbers[i], side=m.side, t0=spans[i][0], t1=spans[i][1], quote=spans[i][2],
            category=g.category, title=g.title[:40], comment=g.comment[:220],
            eval_after=0.0, nonverbal=m.nonverbal,
        ))

    return pace_cards(score_moves(Scene(
        meta=meta.model_copy(update={"title": seg.title.replace("\\n", "\n"), "eval_start": eval_start}),
        players=Players.model_validate({"white": seg.white.model_dump(), "black": seg.black.model_dump()}),
        words=words,
        moves=scene_moves,
        summary=Summary(verdict=edited.verdict, line=edited.line),
    )))


def load_words(path: Path) -> list[Word]:
    return [Word.model_validate(w) for w in json.loads(path.read_text(encoding="utf-8"))]
