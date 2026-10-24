"""Разметка спикеров и слияние со словами.

Распознавание и разметка — разные модели; их результаты сводятся по времени: каждое слово
получает спикера, с чьим отрезком оно пересекается сильнее всего.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from chessify.asr import SAMPLE_RATE, load_wav
from chessify.schema import Word


@dataclass
class SpeakerTurn:
    t0: float
    t1: float
    speaker: str


class DiarizationClient(Protocol):
    def diarize(self, audio: Path, num_speakers: int | None = None) -> list[SpeakerTurn]: ...


def check_hf_token(model: str, token: str | None) -> dict:
    """Токен рабочий и условия модели приняты — для кнопки «Проверить» в настройках."""
    if not token:
        return {"ok": False, "lines": ["HF_TOKEN не задан"]}
    from huggingface_hub import auth_check, whoami
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

    try:
        lines = [f"Токен принадлежит {whoami(token=token)['name']}"]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "lines": [f"Токен не принят: {e}"]}
    try:
        auth_check(model, token=token)
    except GatedRepoError:
        return {"ok": False, "lines": [*lines, f"Условия модели не приняты: откройте https://huggingface.co/{model} "
                                               "и нажмите «Agree and access repository»"]}
    except HfHubHTTPError as e:
        return {"ok": False, "lines": [*lines, f"Нет доступа к {model}: {e}"]}
    return {"ok": True, "lines": [*lines, f"Доступ к {model} есть"]}


class PyannoteDiarization:
    """pyannote community-1 локально. Нужен токен Hugging Face с принятой лицензией модели."""

    def __init__(self, model: str, device: str = "auto", token_env: str | None = "HF_TOKEN") -> None:
        self.model = model
        self.device = device
        self.token = os.environ.get(token_env or "", "") or None

    def diarize(self, audio: Path, num_speakers: int | None = None) -> list[SpeakerTurn]:
        import torch
        from pyannote.audio import Pipeline

        if not self.token:
            raise RuntimeError("нужен HF_TOKEN («Настройки» веб-интерфейса или .env) и принятая лицензия модели на huggingface.co")
        pipeline = Pipeline.from_pretrained(self.model, token=self.token)
        device = "cuda" if self.device == "auto" and torch.cuda.is_available() else self.device
        if device != "auto":
            pipeline.to(torch.device(device))
        # Подаём уже загруженный сигнал, а не путь: не зависим от декодеров torchcodec/ffmpeg на Windows.
        waveform = torch.from_numpy(load_wav(audio)).unsqueeze(0)
        kwargs = {"num_speakers": num_speakers} if num_speakers else {}
        result = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, **kwargs)
        annotation = getattr(result, "speaker_diarization", result)
        turns = [SpeakerTurn(round(seg.start, 3), round(seg.end, 3), str(spk))
                 for seg, _, spk in annotation.itertracks(yield_label=True)]
        del pipeline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()  # освобождаем видеопамять до следующего шага
        return turns


def assign_speakers(words: list[Word], turns: list[SpeakerTurn]) -> list[Word]:
    """Спикер слова — с максимальным пересечением по времени; если пересечений нет — ближайший отрезок."""
    if not turns:
        return words
    out = []
    for w in words:
        best, best_overlap = None, 0.0
        for t in turns:
            overlap = min(w.t1, t.t1) - max(w.t0, t.t0)
            if overlap > best_overlap:
                best, best_overlap = t, overlap
        if best is None:
            mid = (w.t0 + w.t1) / 2
            best = min(turns, key=lambda t: min(abs(mid - t.t0), abs(mid - t.t1)))
        out.append(w.model_copy(update={"spk": best.speaker}))
    return out
