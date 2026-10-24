import json

from chessify.paths import GENERATED_DIR, RENDER_DIR
from chessify.schema import Category, Move, Scene, Side
from chessify.scoring import WEIGHTS, accuracy, counts

REFERENCE = RENDER_DIR / "src" / "fixtures" / "reference.scene.json"


def _moves(side: Side, dist: dict[Category, int]) -> list[Move]:
    return [
        Move(n=1, side=side, t0=0, t1=1, quote="", category=c, title="x", comment="x", eval_after=0)
        for c, k in dist.items()
        for _ in range(k)
    ]


def test_weights_reproduce_reference_totals() -> None:
    # Распределение ходов из итоговой таблицы референса; там точность 83.8 и 93.0.
    dea = _moves(Side.white, {Category.best: 7, Category.good: 10, Category.inaccuracy: 2, Category.mistake: 1})
    mike = _moves(Side.black, {Category.brilliant: 2, Category.best: 6, Category.excellent: 9,
                               Category.good: 2, Category.inaccuracy: 1})
    assert abs(accuracy(dea, Side.white) - 83.8) < 0.5
    assert abs(accuracy(mike, Side.black) - 93.0) < 0.5
    assert counts(mike, Side.black)[Category.excellent] == 9


def test_reference_fixture_is_valid() -> None:
    scene = Scene.model_validate_json(REFERENCE.read_text(encoding="utf-8"))
    assert len(scene.moves) == 12
    assert [m.side for m in scene.moves[:2]] == [Side.white, Side.black]
    assert all(m.t0 < m.t1 for m in scene.moves)


def test_generated_files_match_python() -> None:
    scoring = json.loads((GENERATED_DIR / "scoring.json").read_text(encoding="utf-8"))
    assert scoring["weights"] == {c.value: w for c, w in WEIGHTS.items()}
    schema = json.loads((GENERATED_DIR / "scene.schema.json").read_text(encoding="utf-8"))
    assert schema == Scene.model_json_schema(), "запустите: chessify export-schema && npm run types"


FULL_REFERENCE = RENDER_DIR.parent / "fixtures" / "reference" / "full.scene.json"
W, B = Side.white, Side.black


def _game(seq: list[tuple[Side, Category]]) -> list[Move]:
    return [Move(n=i // 2 + 1, side=s, t0=i, t1=i + 1, quote="", category=c, title="x", comment="x", eval_after=0)
            for i, (s, c) in enumerate(seq)]


def test_eval_curve_reproduces_reference() -> None:
    from chessify.scoring import eval_curve

    ref = Scene.model_validate_json(FULL_REFERENCE.read_text(encoding="utf-8"))
    curve = eval_curve(ref.moves, ref.meta.eval_start)
    assert max(abs(a - m.eval_after) for a, m in zip(curve, ref.moves)) <= 0.35


def test_one_sided_game_keeps_moving_and_never_pins() -> None:
    from chessify.scoring import EVAL_LIMIT, eval_curve

    white = [Category.inaccuracy, Category.mistake, Category.good, Category.inaccuracy, Category.mistake] * 3
    black = [Category.best, Category.brilliant, Category.excellent, Category.best, Category.best] * 3
    curve = eval_curve(_game([x for pair in zip([(W, c) for c in white], [(B, c) for c in black]) for x in pair]), 0.5)
    assert curve[-1] < -3  # явный перевес чёрных — знак верный
    assert all(abs(v) < EVAL_LIMIT - 0.5 for v in curve)  # не упирается в предел
    second_half = curve[len(curve) // 2:]
    changes = sum(a != b for a, b in zip(second_half, second_half[1:]))
    assert changes >= len(second_half) // 3  # и во второй половине продолжает двигаться


def test_mate_countdown_only_for_clear_favorite_at_the_end() -> None:
    from chessify.scoring import eval_curve, mate_countdown

    seq = [(W, Category.mistake), (B, Category.best)] * 12 + [(W, Category.good), (B, Category.best)] * 3
    moves = _game(seq)
    evals = eval_curve(moves, 0.5)
    mates = mate_countdown(moves, evals, "МАТ")
    assert mates[-1] == 0 and mates[-3] == 1 and mates[-5] == 2  # M2 → M1 → # после ходов чёрных
    assert mates[-6] == 3 and all(m is None for m in mates[:-6])  # M3 — после хода белых перед концовкой
    assert mate_countdown(moves, evals, "МАТА НЕТ") == [None] * len(moves)  # не спорим с вердиктом
    balanced = _game([(W, Category.good), (B, Category.good)] * 8)
    assert mate_countdown(balanced, eval_curve(balanced, 0.5), "МАТ") == [None] * 16  # нет фаворита — нет мата
    # фаворит неточно сыграл в концовке, но перевес сохранил — отсчёт начинается только после неточности
    slip = [(W, Category.mistake), (B, Category.best)] * 8 + [(W, Category.good), (B, Category.inaccuracy)]
    late = _game(slip + [(W, Category.mistake), (B, Category.best)] * 2)
    lm = mate_countdown(late, eval_curve(late, 0.5), "")
    assert lm[-4:] == [2, 1, 1, 0] and lm[-5] is None


def test_score_moves_sets_mate_eval_to_limit() -> None:
    from chessify.schema import Meta, Players, Summary
    from chessify.scoring import EVAL_LIMIT, score_moves

    seq = [(W, Category.mistake), (B, Category.best)] * 6
    scene = Scene(meta=Meta(series="s", title="t", clip="c.mp4", eval_start=0.5),
                  players=Players.model_validate({"white": {"name": "A"}, "black": {"name": "B"}}),
                  words=[], moves=_game(seq), summary=Summary(verdict="МАТ", line="l"))
    scored = score_moves(scene)
    assert scored.moves[-1].mate_in == 0 and scored.moves[-1].eval_after == -EVAL_LIMIT


def test_mate_only_in_the_last_part_of_a_short_scene() -> None:
    from chessify.scoring import eval_curve, mate_countdown

    short = _game([(W, Category.mistake), (B, Category.best)] * 6)  # 12 полуходов, разгром с первого хода
    mates = mate_countdown(short, eval_curve(short, 0.5), "МАТ")
    assert mates == [None] * 8 + [2, 1, 1, 0]  # только последняя четверть, а не с середины
