"""WER движков распознавания по эталону из субтитров референса.

    uv run python scripts/stt_wer.py jobs/<id>/words.json другой/words.json …

Эталон (`fixtures/reference/stt_reference.txt`) — субтитры референса на первые 190 с сцены
(render/public/fixture/full_audio.wav). Слова гипотезы берутся до 190 с, сравнение без регистра,
пунктуации и разницы «е/ё»; числа цифрами приводятся к словам.
"""

import json
import re
import sys
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "fixtures" / "reference" / "stt_reference.txt"
END = 190.0
NUM = {"14": "четырнадцать", "10": "десять", "15": "пятнадцать", "20": "двадцать", "3": "три", "2": "два", "1": "один"}


def tokens(words: list[str]) -> list[str]:
    out: list[str] = []
    for raw in words:
        w = raw.lower().replace("ё", "е")
        joins = w.startswith("-") and out  # «по» + «-твоему»
        w = re.sub(r"[^\w]", "", w)
        if not w:
            continue
        w = NUM.get(w, w)
        if joins:
            out[-1] += w
        else:
            out.append(w)
    return out


def errors(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """Замены, пропуски, вставки (расстояние Левенштейна по словам)."""
    n, m = len(ref), len(hyp)
    d = [[i + j if i * j == 0 else 0 for j in range(m + 1)] for i in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, sub, dele, ins = n, m, 0, 0, 0
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            sub += ref[i - 1] != hyp[j - 1]
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            dele, i = dele + 1, i - 1
        else:
            ins, j = ins + 1, j - 1
    return sub, dele, ins


def main() -> None:
    ref = tokens(REFERENCE.read_text(encoding="utf-8").replace("-", " -").split())
    for path in sys.argv[1:]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        hyp = tokens([w["w"] if w["w"].startswith("-") else w["w"].replace("-", " -")
                      for w in data if w["t0"] <= END])
        s, d, i = errors(ref, hyp)
        print(f"{path}: WER {100 * (s + d + i) / len(ref):.1f}% (замен {s}, пропусков {d}, вставок {i}; слов {len(ref)})")


if __name__ == "__main__":
    main()
