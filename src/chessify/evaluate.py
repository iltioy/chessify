"""Сравнение разбора модели с эталонной разметкой референса."""

from dataclasses import dataclass

from chessify.schema import Category, Move, Scene
from chessify.scoring import accuracy

ORDER = list(Category)


@dataclass
class MovePair:
    ref: Move
    got: Move | None

    @property
    def distance(self) -> int | None:
        """Насколько далеко категории на шкале (0 — совпали)."""
        return None if self.got is None else abs(ORDER.index(self.ref.category) - ORDER.index(self.got.category))


def _overlap(a: Move, b: Move) -> float:
    return max(0.0, min(a.t1, b.t1) - max(a.t0, b.t0))


def match_moves(reference: Scene, generated: Scene) -> list[MovePair]:
    """Каждому эталонному ходу — ход модели той же стороны с наибольшим пересечением по времени."""
    pairs = []
    for r in reference.moves:
        same_side = [g for g in generated.moves if g.side == r.side]
        best = max(same_side, key=lambda g: _overlap(r, g), default=None)
        pairs.append(MovePair(r, best if best is not None and _overlap(r, best) > 0 else None))
    return pairs


def report(reference: Scene, generated: Scene, from_move: int = 1) -> str:
    """from_move: оценивать только ходы с этого номера — ходы до него модель видела как примеры."""
    pairs = [p for p in match_moves(reference, generated) if p.ref.n >= from_move]
    matched = [p for p in pairs if p.got is not None]
    exact = sum(p.distance == 0 for p in matched)
    near = sum((p.distance or 0) <= 1 for p in matched)
    lines = [
        f"Ходов (с {from_move}-го): эталон {len(pairs)}, модель {sum(m.n >= from_move for m in generated.moves)}, "
        f"сопоставлено {len(matched)}",
        f"Категория совпала: {exact}/{len(matched)}; в пределах соседней: {near}/{len(matched)}",
    ]
    for side in ("white", "black"):
        lines.append(f"Точность {side}: эталон {accuracy(reference.moves, side)}, модель {accuracy(generated.moves, side)}")  # type: ignore[arg-type]
    r_end = reference.moves[-1].eval_after
    g_end = generated.moves[-1].eval_after if generated.moves else 0.0
    lines.append(f"Шкала в конце: эталон {r_end:+.1f}, модель {g_end:+.1f}")
    lines.append("")
    for p in pairs:
        got = f"{p.got.category.value:<10} {p.got.title}" if p.got else "—"
        mark = "=" if p.distance == 0 else ("~" if p.distance == 1 else "≠")
        lines.append(f"{mark} {p.ref.side.value:<5} «{p.ref.quote[:40]}»: эталон {p.ref.category.value:<10} {p.ref.title} | модель {got}")
    return "\n".join(lines)
