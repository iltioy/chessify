"""Распознавание речи: адаптеры с общим интерфейсом.

Каждый адаптер возвращает список слов с таймкодами в секундах исходного клипа.
Спикеры размечаются отдельным шагом (diarization) и сливаются со словами по времени.
"""

import wave
from pathlib import Path
from typing import Protocol

import numpy as np

from chessify.schema import Word

SAMPLE_RATE = 16000


def load_wav(path: Path) -> np.ndarray:
    """WAV 16 кГц моно (его готовит шаг нормализации) → float32.

    Декодируем сами, без PyAV/torchcodec: меньше зависимостей от сборок ffmpeg, особенно на Windows.
    """
    with wave.open(str(path), "rb") as f:
        if f.getframerate() != SAMPLE_RATE or f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise ValueError(f"{path}: нужен WAV 16 кГц, моно, 16 бит")
        pcm = f.readframes(f.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class STTClient(Protocol):
    def transcribe(self, audio: Path, language: str) -> list[Word]: ...


class FasterWhisperSTT:
    """faster-whisper (CTranslate2). На целевой машине — CUDA, в среде разработки — CPU."""

    def __init__(self, model: str = "large-v3", device: str = "auto", compute_type: str = "default") -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio: Path, language: str) -> list[Word]:
        from faster_whisper import WhisperModel

        model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        segments, _ = model.transcribe(
            load_wav(audio),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    words.append(Word(t0=round(w.start, 3), t1=round(w.end, 3), w=text))
        del model  # освобождаем видеопамять до следующего шага конвейера
        return words


ADAPTERS: dict[str, type] = {
    "faster_whisper": FasterWhisperSTT,
}
