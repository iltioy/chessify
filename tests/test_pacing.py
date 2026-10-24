from pathlib import Path

from chessify.analysis import SegMove, snap_to_phrases
from chessify.pacing import MIN_GAP, pace_cards
from chessify.paths import RENDER_DIR
from chessify.schema import Scene, Side, Word
from chessify.timing import card_cut

FULL = RENDER_DIR.parent / "fixtures" / "reference" / "full.scene.json"
W, B = Side.white, Side.black


def test_cards_hook_first_then_spaced_out() -> None:
    scene = pace_cards(Scene.model_validate_json(FULL.read_text(encoding="utf-8")))
    moves = sorted(scene.moves, key=lambda m: m.t1)
    starts = [w.t0 for w in scene.words]
    cuts = [card_cut(m.t1, starts) for m in moves if m.show_card]
    assert moves[0].show_card and moves[-1].show_card  # крючок и развязка
    gaps = [b - a for a, b in zip(cuts, cuts[1:])]
    assert min(gaps[:-1]) >= MIN_GAP  # без остановок каждые 3–5 секунд (развязка может быть ближе)
    assert 9 <= sum(gaps) / len(gaps) <= 18  # в среднем 12–16 секунд: в эталоне есть длинные монологи без ходов
    assert len(cuts) < len(moves)  # часть ходов идёт без остановки, но остаётся в партии


def test_brightest_move_in_the_window_gets_the_card() -> None:
    scene = Scene.model_validate_json(FULL.read_text(encoding="utf-8"))
    paced = pace_cards(scene)
    shown = [m for m in paced.moves if m.show_card]
    hidden = [m for m in paced.moves if not m.show_card]
    assert any(m.category == "brilliant" for m in shown)
    assert not any(m.category == "brilliant" for m in hidden) or len(hidden) > len(shown)


def _words(*items: tuple[str, float, float, str]) -> list[Word]:
    return [Word(w=w, t0=a, t1=b, spk=s) for w, a, b, s in items]


def test_move_ends_with_the_phrase_and_one_phrase_is_one_move() -> None:
    words = _words(("Где", 0, 0.3, "A"), ("цистерна,", 0.35, 0.8, "A"), ("Майк?", 0.9, 1.3, "A"),
                   ("Майк", 1.4, 1.7, "A"), ("не", 1.75, 1.9, "A"), ("знает.", 1.95, 2.4, "A"),
                   ("Ну", 3.5, 3.7, "B"), ("и", 3.75, 3.8, "B"), ("ладно.", 3.85, 4.2, "B"))
    moves = [SegMove(side=W, w0=0, w1=2), SegMove(side=W, w0=3, w1=4), SegMove(side=B, w0=6, w1=7)]
    snapped = snap_to_phrases(moves, words)
    assert [(m.side, m.w0, m.w1) for m in snapped] == [(W, 0, 5), (B, 6, 8)]  # одна фраза — один ход, до конца


def test_other_side_or_pause_keeps_moves_apart() -> None:
    words = _words(("Да.", 0, 0.3, "A"), ("Нет.", 0.4, 0.7, "B"), ("Точно?", 2.0, 2.4, "A"))
    moves = [SegMove(side=W, w0=0, w1=0), SegMove(side=B, w0=1, w1=1), SegMove(side=W, w0=2, w1=2)]
    assert [(m.w0, m.w1) for m in snap_to_phrases(moves, words)] == [(0, 0), (1, 1), (2, 2)]
