"""Собирает эталонную сцену для шаблона из распознанных слов и ручной разметки референса.

Ходы 1–6 (12 полуходов) переписаны из `video_chess.mp4`: категории, названия, комментарии
и оценки шкалы — как в ролике. Таймкоды — из распознавания «сырой» сцены
(референс без вставленных автором пауз с карточками).

Режимы:
  по умолчанию — ходы 1–6 → render/src/fixtures/reference.scene.json (эталон шаблона и примеры для модели)
  --full       — все 40 полуходов → fixtures/reference/full.scene.json (эталон для оценки анализа)

Запуск: uv run python scripts/build_reference_fixture.py [--full]
"""

import json
import sys
from pathlib import Path

from chessify.schema import Scene, Word

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "fixtures" / "reference" / "words.raw.json"
OUT = ROOT / "render" / "src" / "fixtures" / "reference.scene.json"
FULL_RAW = ROOT / "fixtures" / "reference" / "full_words.raw.json"
FULL_OUT = ROOT / "fixtures" / "reference" / "full.scene.json"

DEA, MIKE = "SPK_0", "SPK_1"

# Исправления распознавания: индекс слова → новый текст (None — удалить слово).
FIXES: dict[int, str | None] = {
    2: "Эрмантраут,", 3: None, 6: "произнёс?",
    40: "«Братья", 41: "Цыплята»,",
    55: "есть,", 57: "как,", 58: "стережёте", 60: "соус?",
    69: "А", 70: None, 72: "фастфуда —",
}
# Диапазоны слов (включительно) и кто их говорит.
SPEAKERS = [(0, 6, DEA), (7, 8, MIKE), (9, 14, DEA), (15, 15, MIKE), (16, 20, DEA), (21, 27, MIKE),
            (28, 43, DEA), (44, 46, MIKE), (47, 48, DEA), (49, 50, MIKE), (51, 52, DEA), (53, 53, MIKE),
            (54, 60, DEA), (61, 68, MIKE), (69, 74, DEA), (75, 83, MIKE)]
LAST_WORD = 83

MOVES = [
    dict(n=1, side="white", w=(0, 6), category="good", eval_after=1.0, title="Рассадка и имя",
         comment="Агенты берут инициативу с первой секунды: приглашение сесть и проверка имени. Тон вежливый, но хозяева здесь они."),
    dict(n=1, side="black", w=(7, 8), category="excellent", eval_after=0.8, title="Примерно так",
         comment="Майк не подтверждает даже верное произношение. Первая реплика уже задаёт его линию: ни одной лишней детали."),
    dict(n=2, side="white", w=(9, 14), category="good", eval_after=0.9, title="Вопрос об адвокате",
         comment="Агенты проверяют, будет ли у Майка защита. Если нет, всё сказанное дальше пойдёт в протокол без адвоката."),
    dict(n=2, side="black", w=(15, 15), category="excellent", eval_after=0.7, title="Лаконичное «верно»",
         comment="Одно слово вместо объяснений. Майк не оправдывает отказ, а значит, не показывает, что ему есть что скрывать."),
    dict(n=3, side="white", w=(16, 20), category="best", eval_after=1.0, title="Запись отказа",
         comment="Отказ нужно повторить на видео: так он станет юридически чистым и у Майка не останется пути назад."),
    dict(n=3, side="black", w=(21, 27), category="brilliant", eval_after=0.5, title="Жертва адвоката",
         comment="Майк добровольно отдаёт главную защитную фигуру. Расчёт простой: молчание без адвоката убедительнее речи с ним."),
    dict(n=4, side="white", w=(35, 43), category="good", eval_after=0.7, title="Официальная легенда",
         comment="Протокольный вопрос закрепляет прикрытие Майка. Позже агенты сравнят его слова с фактами."),
    dict(n=4, side="black", w=(49, 50), category="good", eval_after=0.5, title="Начальник охраны",
         comment="Должность названа без подробностей. Майк даёт ровно то, что агенты и так знают, и не больше."),
    dict(n=5, side="white", w=(54, 60), category="inaccuracy", eval_after=0.1, title="Насмешка про соус",
         comment="Подкол вместо вопроса. Он не приносит информации и выдаёт раздражение, а Майк отвечает ровным тоном."),
    dict(n=5, side="black", w=(61, 68), category="best", eval_after=-0.2, title="Скучная правда",
         comment="Сухая, правдоподобная формулировка. Она снимает насмешку без спора и не даёт повода для следующего вопроса."),
    dict(n=6, side="white", w=(69, 74), category="good", eval_after=0.0, title="Единственная работа?",
         comment="Агенты ищут второй источник дохода. Если он есть, у легенды Майка появляется трещина."),
    dict(n=6, side="black", w=(75, 83), category="excellent", eval_after=-0.2, title="Четырнадцать филиалов",
         comment="Сеть из четырнадцати точек звучит солидно и скучно. Ответ закрывает вопрос так, что придраться не к чему."),
]


# ---- Ходы 7–20: только для режима --full (индексы слов — по полной расшифровке) ----
FULL_FIXES: dict[int, str | None] = {
    84: "Ну,", 98: "Нью-Мексико,", 99: None, 100: None, 129: "ношение?", 142: "её",
    204: "Гас", 205: "Фринг,", 216: "твоему", 217: "прошлому,", 226: "положняк.",
    243: "Наркоимперией?", 244: None, 255: "Слышь,", 256: "брат,", 280: "Чё,", 341: "Фринга",
    392: "Эрмантраут.", 393: None, 417: "глянул", 427: "во", 428: "фринговской", 429: "мутке,",
    433: "угомонись,", 448: "Гомес", 474: "Эрмантраут.", 475: None,
}
FULL_SPEAKERS = [(84, 97, DEA), (98, 108, MIKE), (109, 116, DEA), (117, 121, MIKE), (122, 129, DEA),
                 (130, 131, MIKE), (132, 134, DEA), (135, 143, MIKE), (144, 152, DEA), (153, 160, MIKE),
                 (161, 169, DEA), (170, 171, MIKE), (172, 193, DEA), (194, 195, MIKE), (196, 242, DEA),
                 (243, 254, MIKE), (255, 279, DEA), (280, 290, MIKE), (291, 301, DEA), (302, 324, MIKE),
                 (325, 472, DEA), (473, 475, MIKE), (476, 542, DEA), (543, 555, MIKE)]
FULL_LAST_WORD = 555
# Невербальные ходы: явный интервал времени в «сырой» сцене вместо диапазона слов.
FULL_MOVES = [
    dict(n=7, side="white", w=(90, 97), category="best", eval_after=0.1, title="Частный сыщик",
         comment="Агенты вскрывают вторую профессию Майка: он частный сыщик. Вопрос о лицензии бьёт по легенде охранника."),
    dict(n=7, side="black", w=(98, 108), category="good", eval_after=-0.1, title="Все штаты сети",
         comment="Перечень штатов звучит буднично и проверяемо. Майк отвечает как человек, которому нечего скрывать."),
    dict(n=8, side="white", w=(122, 129), category="good", eval_after=0.1, title="Лицензия на оружие",
         comment="После Колорадо агенты переходят к оружию. Быстрая серия вопросов не оставляет Майку времени на паузу."),
    dict(n=8, side="black", w=(135, 143), category="best", eval_after=-0.2, title="Какой штат — нет",
         comment="Майк переворачивает вопрос: вместо списка штатов даёт понять, что оружие у него легально везде. Изящный уход."),
    dict(n=9, side="white", w=(144, 152), category="good", eval_after=0.0, title="Проверка по базе",
         comment="Агенты намекают, что готовы копать глубже. Майк не меняется в лице: угроза проверкой на него не действует."),
    dict(n=9, side="black", w=(153, 160), category="best", eval_after=-0.3, title="Скажите сами",
         comment="Майк возвращает вопрос обратно. Агенты и так знают ответ, а помогать им он не собирается."),
    dict(n=10, side="white", w=(161, 169), category="good", eval_after=-0.2, title="Бывший коп",
         comment="Первая точная догадка: в Майке узнают бывшего полицейского. Теперь разговор идёт между профессионалами."),
    dict(n=10, side="black", w=(170, 171), category="excellent", eval_after=-0.4, title="Филадельфия",
         comment="Короткий честный ответ без деталей. Майк не отрицает прошлое: ложь здесь слишком легко проверить."),
    dict(n=11, side="white", w=(172, 191), category="best", eval_after=-0.1, title="Кореша в Филли",
         comment="Агенты бьют в прошлое Майка через знакомых в Филадельфии. Это намёк вместо фактов, зато давит на самое личное."),
    dict(n=11, side="black", w=(194, 195), category="excellent", eval_after=-0.3, title="Не особенно",
         comment="Два слова без эмоций. Тема закрыта, а у агентов не остаётся ни факта, ни реакции."),
    dict(n=12, side="white", w=(199, 242), category="best", eval_after=0.0, title="Гас Фринг",
         comment="Агенты впервые называют Гаса Фринга. Версия такая: сеть ресторанов прикрывает наркоимперию, а Майк в ней не просто охранник."),
    dict(n=12, side="black", w=(243, 254), category="best", eval_after=-0.3, title="Ничего не знаю",
         comment="Полное отрицание без нервов. Майк слышит слово «наркоимперия» впервые и не задаёт встречных вопросов."),
    dict(n=13, side="white", w=(255, 279), category="good", eval_after=-0.1, title="Свидетель в лабе",
         comment="Агенты заявляют о свидетеле, но не называют ни имени, ни доказательств. Козырь это или блеф, пока неясно."),
    dict(n=13, side="black", t=(161.9, 166.9), quote="(молчит)", nonverbal=True, category="brilliant", eval_after=-0.6,
         title="Молчание",
         comment="На «по лёгкой или по тяжёлой» Майк не отвечает: руки лежат на столе, лицо неподвижно. Пауза давит сильнее любой реплики."),
    dict(n=14, side="white", t=(167.0, 171.8), quote="(Гомес молча смотрит, Хэнк трёт лицо)", nonverbal=True,
         category="good", eval_after=-0.4, title="Взгляд Гомеса",
         comment="Гомес молча давит взглядом, а Хэнк устало трёт лицо. Агенты ждут, что Майк заговорит первым, но ждут впустую."),
    dict(n=14, side="black", w=(280, 290), category="best", eval_after=-0.7, title="Блеф проверен",
         comment="Майк проверяет блеф прямым вопросом. Без наручников и ордера у агентов нет рычага, и это видно обоим."),
    dict(n=15, side="white", w=(295, 301), category="mistake", eval_after=-1.6, title="Рычага нет",
         comment="Агент сам подтверждает, что держать Майка нечем. «На данный момент» звучит как угроза, но позицию не спасает."),
    dict(n=15, side="black", w=(302, 324), category="excellent", eval_after=-1.9, title="Хочу уйти",
         comment="Майк использует их же ответ: раз не арестован, значит свободен. Возразить на такой ход нечем."),
    dict(n=16, side="white", w=(325, 337), category="best", eval_after=-1.6, title="Счёт внучки",
         comment="Конкретный факт вместо блефа: два миллиона на счёте внучки. Агенты бьют туда, где у Майка слабое место."),
    dict(n=16, side="black", w=(338, 354), quote="(молча слушает про офшорные счета)", nonverbal=True,
         category="excellent", eval_after=-1.8, title="Лицо без реакции",
         comment="Двенадцать офшорных счетов, список сотрудников, и ни одной реакции. Любая ремарка сейчас стала бы признанием."),
    dict(n=17, side="white", w=(355, 392), category="best", eval_after=-1.5, title="Имя внучки",
         comment="Агенты называют имя внучки. Переход от схемы к человеку: теперь молчание будет стоить Майку дороже."),
    dict(n=17, side="black", w=(394, 395), quote="(закрывает глаза)", nonverbal=True, category="inaccuracy",
         eval_after=-1.1, title="Закрытые глаза",
         comment="На словах о десятилетней внучке Майк на секунду закрывает глаза. Единственный эмоциональный сигнал за всю сцену, и агенты его видят."),
    dict(n=18, side="white", w=(396, 443), category="best", eval_after=-0.8, title="Дедулька",
         comment="Сначала абсурд: пятиклассница как главарь. Потом удар в сторону деда. Приём ломает защиту через иронию."),
    dict(n=18, side="black", t=(284.4, 285.9), quote="(молчит)", nonverbal=True, category="excellent",
         eval_after=-1.0, title="Без подтверждения",
         comment="Прямое обвинение, и снова тишина. Майк не подтверждает и не опровергает: каждое слово стало бы уликой."),
    dict(n=19, side="white", w=(444, 468), category="good", eval_after=-0.8, title="Незаконченное «если»",
         comment="Недосказанное «если…» оставляет Майку самому достроить условие. Давление работает сильнее прямой угрозы."),
    dict(n=19, side="black", w=(473, 474), category="excellent", eval_after=-1.0, title="Мистер Эрмантраут",
         comment="Холодная поправка вместо оправданий: Майк не принимает фамильярность и держит дистанцию."),
    dict(n=20, side="white", w=(476, 533), category="inaccuracy", eval_after=-1.4, title="Обещание «шоколада»",
         comment="Туманное обещание вместо сделки: ни условий, ни гарантий. Человеку вроде Майка это не продать."),
    dict(n=20, side="black", w=(543, 555), category="best", eval_after=-1.7, title="Ничего не знаю про деньги",
         comment="Ни да, ни нет, ни намёка. Майк закрывает партию на своих условиях: у DEA есть счёт внучки, но нет доказательств."),
]


def speaker_of(i: int, speakers: list[tuple[int, int, str]]) -> str:
    return next(s for a, b, s in speakers if a <= i <= b)


def main(full: bool) -> None:
    raw_path, out_path = (FULL_RAW, FULL_OUT) if full else (RAW, OUT)
    fixes = {**FIXES, **FULL_FIXES} if full else FIXES
    speakers = SPEAKERS + FULL_SPEAKERS if full else SPEAKERS
    last_word = FULL_LAST_WORD if full else LAST_WORD
    move_specs = MOVES + FULL_MOVES if full else MOVES

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    words: list[Word] = []
    index: dict[int, Word] = {}
    for i, r in enumerate(raw[: last_word + 1]):
        text = fixes.get(i, r["w"])
        if text is None:
            words[-1].t1 = r["t1"]  # слитое слово забирает время удалённого
            continue
        w = Word(t0=r["t0"], t1=r["t1"], w=text, spk=speaker_of(i, speakers))
        words.append(w)
        index[i] = w

    moves = []
    for spec in move_specs:
        m = dict(spec)
        if "t" in m:
            t0, t1 = m.pop("t")
            moves.append({**m, "t0": t0, "t1": t1})
            continue
        a, b = m.pop("w")
        span = [index[i] for i in range(a, b + 1) if i in index]
        quote = m.pop("quote", " ".join(w.w for w in span))
        moves.append({**m, "t0": span[0].t0, "t1": span[-1].t1, "quote": quote})

    prefix = "fixture/full_" if full else "fixture/"
    scene = Scene.model_validate({
        "meta": {
            "series": "Во все тяжкие",
            "title": "Майк против агентов DEA:\nдопрос как шахматная партия",
            "watermark": None,  # уже вшит в эталонный клип
            "clip": f"{prefix}clip.mp4",
            "background": f"{prefix}bg.mp4",
            "eval_start": 0.8,
        },
        "players": {
            "white": {"name": "DEA", "speakers": [DEA], "avatar": "fixture/avatar_white.png"},
            "black": {"name": "Майк", "speakers": [MIKE], "avatar": "fixture/avatar_black.png"},
        },
        "words": [w.model_dump() for w in words],
        "moves": moves,
        "summary": {"verdict": "МАТА НЕТ",
                    "line": "Майк удержал позицию: у DEA есть " + ("счёт внучки" if full else "подозрения") + ", но нет доказательств"},
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scene.model_dump_json(indent=1) + "\n", encoding="utf-8")
    print(f"{len(scene.moves)} ходов, {len(scene.words)} слов → {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main(full="--full" in sys.argv)
