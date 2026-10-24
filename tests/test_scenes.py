from chessify.scenes import SceneCandidate, merge_adjacent, snap, to_lines, windows
import chessify.scenes as sc
from chessify.schema import Word


from chessify.scenes import Line


def _c(start: float, end: float, score: int, spk: tuple[str, ...] = ("A", "B")) -> SceneCandidate:
    return SceneCandidate(start=start, end=end, title=f"{start}", why="", sides="", score=score, excerpt="",
                          speakers=list(spk))


def test_merge_adjacent_pieces_of_one_scene() -> None:
    gap = [Line(t0=410, t1=450, spk="A", text="…")]
    merged = merge_adjacent([_c(196, 407, 10), _c(456, 554, 8), _c(900, 1000, 6)], max_seconds=600, lines=gap)
    assert [(m.start, m.end, m.score) for m in merged] == [(196, 554, 10), (900, 1000, 6)]


def test_merge_overlapping_window_pieces() -> None:
    merged = merge_adjacent([_c(197, 225, 6), _c(197, 406, 9), _c(269, 554, 9), _c(457, 554, 7)], max_seconds=600)
    assert [(m.start, m.end, m.score) for m in merged] == [(197, 554, 9)]


def test_no_merge_beyond_limit_or_other_people() -> None:
    assert len(merge_adjacent([_c(0, 300, 9), _c(310, 650, 9)], max_seconds=600)) == 2
    stranger = [Line(t0=305, t1=308, spk="C", text="…")]
    assert len(merge_adjacent([_c(0, 300, 9), _c(310, 400, 9)], max_seconds=600, lines=stranger)) == 2
    assert len(merge_adjacent([_c(0, 300, 9, ("A",)), _c(310, 400, 9, ("C",))], max_seconds=600)) == 2


def test_snap_to_cuts_or_pad() -> None:
    assert snap(100.0, 200.0, [99.0, 201.5], duration=None) == (99.0, 201.5)
    assert snap(100.0, 200.0, [], duration=200.3) == (99.4, 200.3)


def test_lines_and_windows(monkeypatch) -> None:
    words = [Word(t0=i, t1=i + 0.5, w="слово", spk="A") for i in range(0, 300, 3)]
    lines = to_lines(words)
    assert len(lines) == 100  # пауза 2.5 с > LINE_GAP — каждое слово отдельной строкой
    monkeypatch.setattr(sc, "MAX_WINDOW_CHARS", 1000)
    monkeypatch.setattr(sc, "OVERLAP_LINES", 5)
    ws = windows(lines)
    assert ws[0][0] == 0 and ws[-1][1] == 100
    assert all(b > a for a, b in ws) and all(ws[i + 1][0] < ws[i][1] for i in range(len(ws) - 1))
