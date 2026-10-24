from chessify.proofread import Fix, apply_fixes
from chessify.schema import Word


def _w(*texts: str) -> list[Word]:
    return [Word(t0=i, t1=i + 0.5, w=t) for i, t in enumerate(texts)]


def test_fixes_names_but_keeps_timing_and_count() -> None:
    words = _w("такой,", "как", "Гусфринк,", "решил", "Гомен")
    fixed, applied = apply_fixes(words, [Fix(i=2, w="Гус Фринг,"), Fix(i=4, w="Гомес")])
    assert [w.w for w in fixed] == ["такой,", "как", "Гус Фринг,", "решил", "Гомес"]
    assert [(w.t0, w.t1) for w in fixed] == [(w.t0, w.t1) for w in words]
    assert applied == [("Гусфринк,", "Гус Фринг,"), ("Гомен", "Гомес")]


def test_rejects_rewrites_and_bad_indices() -> None:
    words = _w("Фишетленда,", "капец")
    fixed, applied = apply_fixes(words, [
        Fix(i=1, w="всё очень плохо"),  # непохоже — модель переписывает, а не исправляет
        Fix(i=1, w="капец полный и окончательный"),  # больше трёх слов
        Fix(i=7, w="что-то"),  # нет такого слова
        Fix(i=1, w="—"),  # не слово
    ])
    assert fixed == words and applied == []
    # а созвучная ослышка — исправляется
    assert apply_fixes(words, [Fix(i=0, w="Впечатлён, да.")])[1] == [("Фишетленда,", "Впечатлён, да.")]
