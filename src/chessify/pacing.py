"""Темп карточек: хук в первые секунды, дальше — примерно раз в TARGET секунд сцены.

Ходы не переносятся и не режутся: темп задаётся тем, у каких ходов показывать карточку. Из ходов,
что подходят по времени, карточку получает самый яркий. Ходы без карточки остаются в партии —
двигают шкалу и учитываются в итогах, их реплики просто звучат без остановки кадра.
"""

from chessify.condense import SALIENCE
from chessify.schema import Scene
from chessify.timing import card_cut

MIN_GAP = 7.0  # секунд сцены между карточками — меньше зритель воспринимает как «стоп каждые пять секунд»
TARGET = 12.0  # обычный шаг между карточками
SLACK = 5.0  # насколько позже шага можно ждать более яркий ход


def pace_cards(scene: Scene) -> Scene:
    moves = sorted(scene.moves, key=lambda m: m.t1)
    if not moves:
        return scene
    starts = [w.t0 for w in scene.words]
    cuts = [card_cut(m.t1, starts) for m in moves]
    shown = {0}  # хук: первый ход сцены всегда с карточкой
    last, i = cuts[0], 1
    while i < len(moves):
        window = [k for k in range(i, len(moves)) if last + MIN_GAP <= cuts[k] <= last + TARGET + SLACK]
        if window:
            pick = max(window, key=lambda k: (SALIENCE[moves[k].category], -k))
        else:
            later = [k for k in range(i, len(moves)) if cuts[k] >= last + MIN_GAP]
            if not later:
                break
            pick = later[0]
        shown.add(pick)
        last, i = cuts[pick], pick + 1
    final = len(moves) - 1  # развязка всегда с карточкой; слишком близкий к ней предыдущий ход — без
    if final not in shown:
        prev = max(shown)
        if prev != 0 and cuts[final] - cuts[prev] < MIN_GAP:
            shown.discard(prev)
        shown.add(final)
    keep = {id(moves[k]) for k in shown}
    return scene.model_copy(update={"moves": [m.model_copy(update={"show_card": id(m) in keep}) for m in scene.moves]})
