"""Вычитка расшифровки: модель, знающая сериал, исправляет имена и явные ослышки.

Меняется только текст слов: их число, порядок и таймкоды остаются, поэтому караоке-подсветка
и разбивка на ходы не сдвигаются. Правка, слишком непохожая на распознанное слово, отбрасывается:
модель не должна переписывать реплики.
"""

import difflib
import re

from pydantic import BaseModel

from chessify.analysis import PROMPTS, format_transcript
from chessify.llm import LLMRouter
from chessify.schema import Word

MIN_SIMILARITY = 0.5  # «Гусфринк» → «Гус Фринг» проходит, «Фишетленда» → «Впечатлён, да» — нет
SYSTEM = "Ты корректор субтитров к сериалам. Отвечаешь только JSON."


class Fix(BaseModel):
    i: int
    w: str


class ProofreadResult(BaseModel):
    fixes: list[Fix]


def _bare(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower()).replace("ё", "е")


def apply_fixes(words: list[Word], fixes: list[Fix]) -> tuple[list[Word], list[tuple[str, str]]]:
    out, applied = list(words), []
    for f in fixes:
        new = f.w.strip()
        if not 0 <= f.i < len(out) or not _bare(new) or len(new.split()) > 3 or len(new) > 40:
            continue
        old = out[f.i].w
        if _bare(old) == _bare(new) and old == new:
            continue
        if difflib.SequenceMatcher(a=_bare(old), b=_bare(new)).ratio() < MIN_SIMILARITY:
            continue
        out[f.i] = out[f.i].model_copy(update={"w": new})
        applied.append((old, new))
    return out, applied


def proofread(router: LLMRouter, words: list[Word], series: str, hint: str = "") -> tuple[list[Word], list[tuple[str, str]]]:
    user = PROMPTS.get_template("proofread.md.j2").render(series=series, hint=hint, transcript=format_transcript(words))
    result = router.complete_json("segment", SYSTEM, user, ProofreadResult)
    return apply_fixes(words, result.fixes)
