"""Готовит ассеты эталонной сцены из `video_chess.mp4` (сам ролик в git не хранится).

1. Вырезает окно клипа (без полосы вшитых субтитров) и интервалы, где автор референса
   держал карточки на стоп-кадре, — получается почти «сырая» сцена.
2. Рендерит размытый фон, WAV 16 кГц для распознавания и аватары.

Два варианта:
  по умолчанию — первые 100 с (ходы 1–6), короткий эталон для шаблона: render/public/fixture/
  --full       — вся партия (40 полуходов) для оценки анализа: render/public/fixture/full_*

Затем: chessify transcribe → scripts/build_reference_fixture.py [--full].
Запуск: uv run python scripts/build_reference_assets.py [--full]
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "video_chess.mp4"
OUT = ROOT / "render" / "public" / "fixture"

# Интервалы всех 40 карточек в референсе (секунды), найдены по появлению цветной полосы карточки.
CARD_INTERVALS = [
    (4.50, 8.50), (12.25, 16.25), (19.50, 23.50), (25.25, 29.25), (32.25, 36.00), (39.75, 43.75),
    (52.25, 55.75), (58.75, 62.25), (68.00, 71.75), (76.50, 80.50), (85.50, 88.75), (92.50, 96.50),
    (106.00, 110.00), (113.25, 117.00), (124.25, 128.25), (134.50, 138.50), (142.25, 146.25), (150.75, 154.00),
    (162.75, 166.75), (171.50, 175.25), (189.75, 194.00), (198.25, 201.50), (228.25, 232.50), (240.75, 244.50),
    (254.25, 258.00), (263.00, 267.25), (272.00, 276.00), (284.50, 288.25), (306.00, 310.25), (321.00, 324.75),
    (337.50, 341.25), (353.75, 358.00), (381.25, 385.00), (389.00, 393.75), (416.75, 420.75), (422.25, 426.00),
    (445.25, 449.00), (456.25, 459.50), (485.75, 489.50), (508.00, 512.00),
]
SHORT_END, FULL_END = 100.0, 512.0
# Окно клипа в кадре 720×1280 без нижней полосы субтитров, с сохранением 16:9.
CROP = "crop=566:318:77:256"
# Кадры для аватаров в «сырой» сцене: (время, область лица в 1280×720).
AVATARS = {"avatar_white.png": (31.0, "crop=300:300:690:170"), "avatar_black.png": (37.5, "crop=330:330:455:20")}
BLUR_BG = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
           "gblur=sigma=40,eq=brightness=-0.1:saturation=0.85,fps=30")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def main(full: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    end = FULL_END if full else SHORT_END
    prefix = "full_" if full else ""
    cut = "+".join(f"between(t,{a},{b})" for a, b in CARD_INTERVALS if a < end)
    clip = OUT / f"{prefix}clip.mp4"
    ffmpeg("-t", str(end), "-i", str(SOURCE),
           "-vf", f"{CROP},select='not({cut})',setpts=N/FRAME_RATE/TB,scale=1280:720:flags=lanczos,setsar=1",
           "-af", f"aselect='not({cut})',asetpts=N/SR/TB",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "128k", str(clip))
    ffmpeg("-i", str(clip), "-vf", BLUR_BG, "-an", "-c:v", "libx264", "-crf", "28", "-preset", "medium",
           str(OUT / f"{prefix}bg.mp4"))
    ffmpeg("-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(OUT / f"{prefix}audio.wav"))
    if not full:
        for name, (t, crop) in AVATARS.items():
            ffmpeg("-ss", str(t), "-i", str(clip), "-frames:v", "1", "-vf", f"{crop},scale=256:256", str(OUT / name))
    print(f"Ассеты → {OUT.relative_to(ROOT)} ({'полная партия' if full else 'ходы 1–6'})")


if __name__ == "__main__":
    main(full="--full" in sys.argv)
