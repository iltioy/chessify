"""Сквозной конвейер: видео → готовый ролик.

Каждый шаг пишет результат в папку задачи и пропускается, если результат уже есть, —
так любой шаг можно перезапустить, удалив его файл.
  render/public/jobs/<id>/  — медиа, которые читает шаблон (clip.mp4, bg.mp4, аватары)
  jobs/<id>/                — данные (audio.wav, words.json, scene.json)
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from chessify.analysis import analyze, load_words
from chessify.asr import ADAPTERS
from chessify.config import Config
from chessify.diarization import PyannoteDiarization, assign_speakers
from chessify.i18n import Lang, norm, pick
from chessify.llm import LLMRouter
from chessify.paths import JOBS_DIR, MUSIC_DIR, MUSIC_EXT, RENDER_DIR
from chessify.schema import Meta, Scene

if TYPE_CHECKING:
    from chessify.scenes import SceneCandidate

Log = Callable[[str], None]
Progress = Callable[[float], None]

BLUR_BG = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
           "gblur=sigma=40,eq=brightness=-0.1:saturation=0.85,fps=30")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def media_duration(path: Path) -> float | None:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


@cache
def has_nvenc() -> bool:
    """Пробное кодирование, а не список кодировщиков: в контейнере без доступа к видеоблоку GPU
    кодировщик в списке есть, но не работает."""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=c=black:s=256x256:d=0.5", "-c:v", "h264_nvenc", "-f", "null", "-"],
                           capture_output=True)
    return probe.returncode == 0


KICKER = {"ru": "Разбор сцены", "en": "Scene breakdown"}  # надзаголовок ролика


class Job:
    """ui_lang — язык журнала, language — язык ролика: речь, тексты модели и надписи."""

    def __init__(self, job_id: str, log: Log = print, ui_lang: str = "ru", language: str = "ru") -> None:
        self.id = job_id
        self.ui: Lang = norm(ui_lang)
        self.language: Lang = norm(language)
        self.data = JOBS_DIR / job_id
        self.media = RENDER_DIR / "public" / "jobs" / job_id
        self.data.mkdir(parents=True, exist_ok=True)
        self.media.mkdir(parents=True, exist_ok=True)
        self.log = log

    def say(self, ru: str, en: str) -> None:
        self.log(pick(ru, en, self.ui))

    def public(self, name: str) -> str:
        """Путь для шаблона Remotion (относительно render/public)."""
        return f"jobs/{self.id}/{name}"

    def normalize(self, source: Path, start: float | None, end: float | None) -> None:
        clip, audio, bg = self.media / "clip.mp4", self.data / "audio.wav", self.media / "bg.mp4"
        trim = (["-ss", str(start)] if start else []) + (["-to", str(end)] if end else [])
        encoder = ["-c:v", "h264_nvenc", "-cq", "20"] if has_nvenc() else ["-c:v", "libx264", "-crf", "18"]
        if not clip.exists():
            self.say("1/5 нормализация клипа", "1/5 normalizing the clip")
            ffmpeg(*trim, "-i", str(source), "-vf", "scale=-2:720,fps=30,setsar=1", *encoder,
                   "-c:a", "aac", "-b:a", "160k", str(clip))
        if not audio.exists():
            ffmpeg("-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(audio))
        if not bg.exists():
            self.say("1/5 размытый фон", "1/5 blurred background")
            ffmpeg("-i", str(clip), "-vf", BLUR_BG, "-an", *encoder, str(bg))

    def transcribe(self, cfg: Config, roles: dict[str, str], prefix: str = "") -> None:
        out = self.data / f"{prefix}words.json"
        if out.exists():
            return
        a = cfg.asr[roles["asr"]]
        self.say(f"2/5 распознавание речи ({a.model}, {a.device})", f"2/5 speech recognition ({a.model}, {a.device})")
        words = ADAPTERS[a.adapter](a.model, a.device, a.compute_type).transcribe(self.data / f"{prefix}audio.wav",
                                                                                   self.language)
        out.write_text(json.dumps([w.model_dump() for w in words], ensure_ascii=False, indent=1), encoding="utf-8")

    def diarize(self, cfg: Config, roles: dict[str, str], num_speakers: int | None, prefix: str = "") -> None:
        out = self.data / f"{prefix}words.spk.json"
        if out.exists():
            return
        words = load_words(self.data / f"{prefix}words.json")
        d = cfg.diarization[roles["diarization"]]
        try:
            self.say("3/5 разметка спикеров", "3/5 speaker diarization")
            turns = PyannoteDiarization(d.model, d.device, d.token_env).diarize(self.data / f"{prefix}audio.wav",
                                                                                 num_speakers)
            words = assign_speakers(words, turns)
        except (RuntimeError, ImportError) as e:
            # Без разметки конвейер не падает: стороны модель определит по смыслу реплик, но хуже.
            self.say(f"   разметка спикеров пропущена: {e}", f"   speaker diarization skipped: {e}")
        out.write_text(json.dumps([w.model_dump() for w in words], ensure_ascii=False, indent=1), encoding="utf-8")

    def proofread(self, router: LLMRouter, series: str, hint: str) -> None:
        """Вычитка расшифровки моделью: имена и явные ослышки. Ошибка вычитки не останавливает конвейер."""
        from chessify.proofread import proofread

        out = self.data / "words.fixed.json"
        if out.exists():
            return
        words = load_words(self.data / "words.spk.json")
        self.say("3/5 вычитка расшифровки", "3/5 proofreading the transcript")
        try:
            words, applied = proofread(router, words, series, hint, self.language)
            fixes = "".join(f"\n   {a} → {b}" for a, b in applied[:30])
            self.say(f"   исправлено слов: {len(applied)}{fixes}", f"   words fixed: {len(applied)}{fixes}")
        except Exception as e:  # noqa: BLE001
            self.say(f"   вычитка пропущена: {e}", f"   proofreading skipped: {e}")
        out.write_text(json.dumps([w.model_dump() for w in words], ensure_ascii=False, indent=1), encoding="utf-8")

    def analyze(self, router: LLMRouter, series: str, hint: str) -> Scene:
        out = self.data / "scene.json"
        if out.exists():
            return Scene.model_validate_json(out.read_text(encoding="utf-8"))
        self.say("4/5 анализ партии", "4/5 analyzing the game")
        meta = Meta(series=series, title="", clip=self.public("clip.mp4"), background=self.public("bg.mp4"),
                    language=self.language, kicker=KICKER[self.language])
        fixed = self.data / "words.fixed.json"
        scene = analyze(router, load_words(fixed if fixed.exists() else self.data / "words.spk.json"), meta, hint=hint)
        out.write_text(scene.model_dump_json(indent=1) + "\n", encoding="utf-8")
        t = router.total
        self.say(f"   {len(scene.moves)} ходов; токены {t.input_tokens}/{t.output_tokens}, ≈ ${t.cost_usd:.3f}",
                 f"   {len(scene.moves)} moves; tokens {t.input_tokens}/{t.output_tokens}, ≈ ${t.cost_usd:.3f}")
        return scene

    def avatars(self, scene: Scene) -> Scene:
        if all(p.avatar for p in (scene.players.white, scene.players.black)):
            return scene
        from chessify.faces import make_avatars

        self.say("4/5 аватары сторон", "4/5 player avatars")
        found = make_avatars(self.media / "clip.mp4", scene.moves, self.media)
        players = scene.players.model_copy(update={
            side.value: getattr(scene.players, side.value).model_copy(update={"avatar": self.public(path.name)})
            for side, path in found.items()
        })
        scene = scene.model_copy(update={"players": players})
        (self.data / "scene.json").write_text(scene.model_dump_json(indent=1) + "\n", encoding="utf-8")
        return scene

    def find_scenes(self, source: Path, cfg: Config, roles: dict[str, str], series: str,
                    hint: str = "") -> list["SceneCandidate"]:
        """Целая серия → кандидаты сцен-дуэлей (jobs/<id>/candidates.json)."""
        from chessify.scenes import SceneCandidate, find_scenes

        out = self.data / "candidates.json"
        if out.exists():
            return [SceneCandidate.model_validate(c) for c in json.loads(out.read_text(encoding="utf-8"))]
        audio = self.data / "episode_audio.wav"
        if not audio.exists():
            self.say("1/5 звук серии", "1/5 episode audio")
            ffmpeg("-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(audio))
        self.transcribe(cfg, roles, prefix="episode_")
        self.diarize(cfg, roles, None, prefix="episode_")
        self.say("4/5 поиск сцен-дуэлей", "4/5 looking for duel scenes")
        candidates = find_scenes(LLMRouter(cfg, roles), load_words(self.data / "episode_words.spk.json"), series,
                                 hint, video=source, duration=media_duration(source), lang=self.language)
        out.write_text(json.dumps([c.model_dump() for c in candidates], ensure_ascii=False, indent=1),
                       encoding="utf-8")
        self.say(f"   кандидатов: {len(candidates)}", f"   candidates: {len(candidates)}")
        return candidates

    def process(self, source: Path, cfg: Config, roles: dict[str, str], series: str, hint: str = "",
                start: float | None = None, end: float | None = None, speakers: int | None = None) -> Scene:
        """Шаги 1–4: от исходного видео до сцены с ходами и аватарами."""
        self.normalize(source, start, end)
        self.transcribe(cfg, roles)
        self.diarize(cfg, roles, speakers)
        router = LLMRouter(cfg, roles)
        self.proofread(router, series, hint)
        return self.avatars(self.analyze(router, series, hint))


def _render_hwaccel() -> bool:
    """CHESSIFY_RENDER_HWACCEL: on, off или auto (по умолчанию — при наличии NVIDIA GPU)."""
    mode = os.environ.get("CHESSIFY_RENDER_HWACCEL", "auto").lower()
    return mode == "on" or (mode == "auto" and shutil.which("nvidia-smi") is not None)


def add_music(scene: Scene, music: str | Path | None, volume: float | None = None) -> Scene:
    """Подключить трек из библиотеки (имя файла) или любой файл (копируется в библиотеку)."""
    if not music:
        return scene
    path = Path(music)
    if path.suffix.lower() not in MUSIC_EXT:
        raise ValueError(f"музыка: нужен аудиофайл ({', '.join(sorted(MUSIC_EXT))})")
    if path.is_file() and path.resolve().parent != MUSIC_DIR.resolve():
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, MUSIC_DIR / path.name)
    if not (MUSIC_DIR / path.name).is_file():
        raise ValueError(f"в библиотеке музыки нет {path.name}")
    update: dict = {"music": f"music/{path.name}"}
    if volume is not None:
        update["music_volume"] = volume
    return scene.model_copy(update={"meta": scene.meta.model_copy(update=update)})


def render_scene(scene: Scene, out: Path, preset: str = "final", length: str = "full",
                 log: Log = print, progress: Progress | None = None, ui_lang: str = "ru") -> Path:
    """Шаг 5: рендер через Remotion. length — full или пресет из condense.PRESETS."""
    from chessify.condense import PRESETS, condense, estimated_seconds

    if length != "full":
        if length not in PRESETS:
            raise ValueError(f"длина: full или {', '.join(PRESETS)}")
        scene = condense(scene, PRESETS[length])
    cards = sum(m.show_card for m in scene.moves)
    log(pick(f"5/5 рендер: {cards} ходов, ≈ {estimated_seconds(scene):.0f} с",
             f"5/5 rendering: {cards} moves, ≈ {estimated_seconds(scene):.0f} s", ui_lang))
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("npx не найден: установите Node.js")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"scene": scene.model_dump(mode="json"), "preset": preset}, f, ensure_ascii=False)
        props = f.name
    args = [npx, "remotion", "render", "ChessScene", str(out), f"--props={props}"]
    if _render_hwaccel():
        args.append("--hardware-acceleration=if-possible")
    try:
        proc = subprocess.Popen(args, cwd=RENDER_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        tail: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-30:]
            if progress and (m := re.search(r"Rendered (\d+)/(\d+)", line)):
                progress(int(m.group(1)) / int(m.group(2)))
        if proc.wait() != 0:
            raise RuntimeError("рендер Remotion упал:\n" + "\n".join(tail))
    finally:
        os.unlink(props)
    return out
