from chessify.condense import condense, estimated_seconds
from chessify.paths import RENDER_DIR
from chessify.schema import Scene

REFERENCE = RENDER_DIR / "src" / "fixtures" / "reference.scene.json"


def _scene() -> Scene:
    return Scene.model_validate_json(REFERENCE.read_text(encoding="utf-8"))


def test_condense_fits_limit_and_keeps_pairs() -> None:
    full = _scene()
    short = condense(full, 60)
    shown = [m for m in short.moves if m.show_card]
    assert estimated_seconds(short) <= 60
    assert len(shown) < len(full.moves)
    # итоги считаются по всей партии: скрытые ходы остаются в данных
    assert len(short.moves) == len(full.moves)
    # пары не разрываются: каждому номеру хода — и белые, и чёрные
    by_n: dict[int, set[str]] = {}
    for m in shown:
        by_n.setdefault(m.n, set()).add(m.side.value)
    assert all(sides == {"white", "black"} for sides in by_n.values())
    # завязка и развязка на месте
    assert shown[0].n == full.moves[0].n and shown[-1].n == full.moves[-1].n


def test_condense_prefers_brilliant_pair() -> None:
    short = condense(_scene(), 60)
    assert any(m.category == "brilliant" for m in short.moves if m.show_card)


def test_excerpts_cover_shown_moves() -> None:
    short = condense(_scene(), 60)
    assert short.meta.excerpts
    for m in short.moves:
        inside = any(a <= m.t0 and m.t1 <= b for a, b in short.meta.excerpts)
        assert inside == m.show_card


def test_card_waits_for_phrase_tail_but_not_next_speaker() -> None:
    from chessify.timing import TIMING, card_cut

    assert card_cut(5.0, [0.0, 4.0, 9.0]) == 5.0 + TIMING["cardDelay"]  # тишина после фразы — ждём хвост
    assert card_cut(5.0, [0.0, 5.3]) == 5.3 - TIMING["cardGap"]  # следующая реплика близко — встаём до неё
    assert card_cut(5.0, [0.0, 5.02]) == 5.0  # никогда раньше конца хода
