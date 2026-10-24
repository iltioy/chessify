"""Звуки карточки хода (синтез, без чужих сэмплов): render/public/sfx/card.wav и typing.wav.

Как в референсе: при появлении карточки — короткий двухтоновый «пинг», пока печатается
комментарий — щелчки клавиш примерно 11 раз в секунду с неровным ритмом.
Запуск: uv run python scripts/make_sfx.py
"""

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parents[1] / "render" / "public" / "sfx"
rng = np.random.default_rng(7)  # фиксированное зерно: файлы одинаковые при каждой сборке


def _write(path: Path, x: np.ndarray) -> None:
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((x * 32767).astype("<i2").tobytes())


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def ping() -> np.ndarray:
    t = _t(0.45)
    tone = 0.6 * np.sin(2 * np.pi * 1320 * t) + 0.3 * np.sin(2 * np.pi * 2640 * t)
    attack = np.minimum(1, t / 0.004)
    return 0.55 * tone * attack * np.exp(-t / 0.12)


def click() -> np.ndarray:
    t = _t(0.03)
    noise = rng.standard_normal(t.size)
    noise = np.diff(noise, prepend=0)  # грубый ФВЧ: щелчок, а не шипение
    body = np.sin(2 * np.pi * rng.uniform(170, 260) * t) * np.exp(-t / 0.008)
    x = 0.5 * noise * np.exp(-t / rng.uniform(0.003, 0.006)) + 0.5 * body
    return x / np.abs(x).max() * rng.uniform(0.55, 0.9)


def typing(seconds: float = 8.0) -> np.ndarray:
    out = np.zeros(int(seconds * RATE))
    pos = 0.0
    while pos < seconds - 0.05:
        c = click()
        i = int(pos * RATE)
        out[i : i + c.size] += c[: out.size - i]
        pos += rng.uniform(0.06, 0.12) if rng.random() > 0.08 else rng.uniform(0.14, 0.2)  # редкие паузы
    return out * 0.8


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "card.wav", ping())
    _write(OUT / "typing.wav", typing())
    print(f"готово: {OUT}")
