from chessify.analysis import SegMove, SegPlayer, SegmentResult, _clean_moves, format_transcript, move_span, number_moves
from chessify.schema import Side, Word

W, B = Side.white, Side.black


def _words() -> list[Word]:
    # «вопрос» 0–2 с, пауза 6 с, «ответ» 8–9 с
    return [Word(t0=0, t1=1, w="Что", spk="A"), Word(t0=1, t1=2, w="выберешь?", spk="A"),
            Word(t0=8, t1=8.5, w="Не", spk="B"), Word(t0=8.5, t1=9, w="понимаю.", spk="B")]


def test_numbering_like_chess_notation() -> None:
    assert number_moves([W, B, W, B, B, W]) == [1, 1, 2, 2, 2, 3]
    assert number_moves([B, W, B]) == [1, 2, 2]


def test_transcript_marks_pauses() -> None:
    assert "[пауза 6.0 с после слова 1]" in format_transcript(_words())


def test_pause_move_span_and_ordering() -> None:
    seg = SegmentResult(
        white=SegPlayer(name="A", speakers=["A"]), black=SegPlayer(name="B", speakers=["B"]), title="t",
        moves=[SegMove(side=B, w0=2, w1=3), SegMove(side=B, w0=1, w1=1, pause_after=1), SegMove(side=W, w0=0, w1=1)],
    )
    moves = _clean_moves(seg, _words())
    assert [m.pause_after for m in moves] == [None, 1, None]
    t0, t1, quote = move_span(moves[1], _words())
    assert (t0, t1) == (2.1, 7.1) and quote.startswith("(молчание")  # пауза обрезана до 5 с


def test_clean_drops_overlaps_and_fake_pauses() -> None:
    seg = SegmentResult(
        white=SegPlayer(name="A", speakers=["A"]), black=SegPlayer(name="B", speakers=["B"]), title="t",
        moves=[SegMove(side=W, w0=0, w1=2), SegMove(side=B, w0=1, w1=3), SegMove(side=B, w0=0, w1=0, pause_after=2)],
    )
    moves = _clean_moves(seg, _words())
    assert [(m.w0, m.w1) for m in moves] == [(0, 2), (3, 3)]



def test_prompts_render_in_both_languages() -> None:
    from chessify.analysis import _examples, template

    sample = {"series": "S", "hint": "h", "transcript": "[0] a", "white": "A", "black": "B", "eval_start": 0.5,
              "moves": [{"index": 0, "side_name": "A", "quote": "q", "nonverbal": False}], "draft": "{}",
              "part": 1, "part_total": 2, "max_candidates": 3, "min_seconds": 45, "max_seconds": 600}
    for lang in ("ru", "en"):
        examples = _examples(False, lang)
        assert len(examples) == 12
        assert template("system.md.j2", lang).render(examples=examples)
        for name in ("segment", "grade", "edit", "proofread", "scene_select"):
            text = template(f"{name}.md.j2", lang).render(**sample)
            assert ("Show:" in text or "Below" in text) == (lang == "en"), name


def test_transcript_pause_marker_follows_language() -> None:
    assert "[pause 6.0 s after word 1]" in format_transcript(_words(), "en")
